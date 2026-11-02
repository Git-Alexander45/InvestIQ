"""Ten leaderboards, each with its own evaluation method (documented in ``BOARDS``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from investiq.scoring.curves import scale
from investiq.scoring.engine import Facts, ScoreResult

EMERGING_THEMES = {
    "artificial_intelligence", "semiconductors", "robotics", "automation", "cybersecurity", "biotechnology",
    "healthcare_technology", "energy_transition", "nuclear", "infrastructure", "advanced_manufacturing",
    "space", "quantum_computing",
}
DEFENSIVE_SECTORS = {"Utilities", "Consumer Staples", "Health Care", "Healthcare"}
NORTH_AMERICA = {"CA", "US"}


@dataclass
class Candidate:
    instrument_id: int
    facts: Facts
    score: ScoreResult
    score_id: int | None = None
    assessment: str = "WATCH"
    primary_eligible: bool = False
    tfsa: dict[str, Any] | None = None
    intl_exposure_pct: float | None = None  # look-through non-North-America weight for funds
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BoardSpec:
    key: str
    title: str
    method: str
    eligible: Callable[[Candidate], bool]
    rank_value: Callable[[Candidate], float | None]


def _is_fund(c: Candidate) -> bool:
    return c.facts.instrument.security_type in ("etf", "mutual_fund")


def _cat(c: Candidate, name: str) -> float:
    v = c.score.score_of(name)
    return 50.0 if v is None else v


def _growth_stock(c: Candidate) -> float:
    return 0.5 * _cat(c, "growth") + 0.5 * c.score.overall


def _growth_etf(c: Candidate) -> float:
    return 0.4 * _cat(c, "diversification") + 0.3 * _cat(c, "growth_exposure") + 0.3 * c.score.overall


def _undervalued(c: Candidate) -> float | None:
    # Quality floor guards against value traps: weak balance sheets are excluded.
    strength = c.score.score_of("financial_strength")
    if strength is not None and strength < 50:
        return None
    return 0.6 * _cat(c, "valuation") + 0.4 * c.score.overall


def _dividend(c: Candidate) -> float | None:
    f = c.facts.fundamentals or {}
    yld = f.get("dividend_yield_pct") or f.get("distribution_yield_pct")
    if not yld or yld <= 0:
        return None
    parts = [scale(yld, [(0.5, 20), (2, 55), (3.5, 80), (6, 85), (9, 40)])]  # very high yields are suspect
    if f.get("dividend_cagr_5y_pct") is not None:
        parts.append(scale(f["dividend_cagr_5y_pct"], [(-5, 0), (0, 25), (5, 65), (10, 90), (15, 100)]))
    payout = f.get("fcf_payout_pct") if f.get("fcf_payout_pct") is not None else f.get("payout_ratio_pct")
    if payout is not None:
        parts.append(scale(payout, [(20, 90), (50, 85), (75, 55), (100, 20), (130, 0)]))
    return 0.6 * (sum(parts) / len(parts)) + 0.4 * c.score.overall


def _international(c: Candidate) -> bool:
    inst = c.facts.instrument
    if _is_fund(c):
        return (c.intl_exposure_pct or 0) >= 50 or (inst.region or "") in ("europe", "asia", "emerging_markets",
                                                                          "international", "global_ex_na")
    return bool(inst.country) and inst.country not in NORTH_AMERICA


def _defensive_value(c: Candidate) -> float:
    return 0.5 * _cat(c, "risk") + 0.5 * c.score.overall


def _defensive_eligible(c: Candidate) -> bool:
    inst = c.facts.instrument
    if inst.asset_class in ("bond", "cash_equivalent"):
        return True
    if inst.sector in DEFENSIVE_SECTORS:
        return True
    vol = (c.facts.price_stats or {}).get("volatility_1y_pct")
    return vol is not None and vol < 15


BOARDS: list[BoardSpec] = [
    BoardSpec("best_overall", "Best overall investment opportunities",
              "Overall grade across all asset-class models; primary-eligible (verified at both brokerages) listed first.",
              lambda c: True, lambda c: c.score.overall + (1000 if c.primary_eligible else 0)),
    BoardSpec("aggressive_growth_stocks", "Best aggressive-growth stocks",
              "Individual stocks ranked 50% growth category, 50% overall grade.",
              lambda c: c.score.model == "equity", _growth_stock),
    BoardSpec("diversified_growth_etfs", "Best diversified growth ETFs",
              "Equity ETFs ranked 40% diversification, 30% holdings growth exposure, 30% overall.",
              lambda c: c.score.model == "etf_equity", _growth_etf),
    BoardSpec("undervalued", "Best undervalued investments",
              "60% valuation, 40% overall; requires financial strength of at least 50 to avoid value traps.",
              lambda c: c.score.categories.get("valuation") is not None and c.score.categories["valuation"].available,
              _undervalued),
    BoardSpec("emerging_industries", "Best emerging-industry opportunities",
              "Companies and funds tagged with an emerging-industry research theme, ranked by overall grade. "
              "A promising industry does not make a promising company: the company's own grade decides.",
              lambda c: bool(set(c.facts.instrument.themes) & EMERGING_THEMES), lambda c: c.score.overall),
    BoardSpec("dividend_growth", "Best dividend-growth investments",
              "Yield (capped for suspiciously high yields), 5-year dividend growth and payout sustainability (60%), "
              "plus overall grade (40%).",
              lambda c: True, _dividend),
    BoardSpec("international", "Best international investments",
              "Non-North-American issuers, or funds with at least 50% look-through exposure outside Canada/US.",
              _international, lambda c: c.score.overall),
    BoardSpec("defensive", "Best defensive investments",
              "Bonds, cash equivalents, defensive sectors or low-volatility assets; 50% risk score, 50% overall.",
              _defensive_eligible, _defensive_value),
    BoardSpec("commodities_precious_metals", "Best commodity and precious-metal opportunities",
              "Commodity and precious-metal model: structure, cost, diversification benefit, trend and risk.",
              lambda c: c.score.model == "commodity", lambda c: c.score.overall),
    BoardSpec("tfsa", "Best Canadian TFSA investments",
              "TFSA suitability score: qualified-investment status, MER, foreign withholding drag, leverage, "
              "concentration, currency exposure and overall grade.",
              lambda c: c.tfsa is not None and c.tfsa.get("eligible", False), lambda c: (c.tfsa or {}).get("score")),
]


def build_boards(candidates: list[Candidate], size: int = 10) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for spec in BOARDS:
        rows = []
        for c in candidates:
            if c.assessment == "AVOID" or not spec.eligible(c):
                continue
            value = spec.rank_value(c)
            if value is None:
                continue
            rows.append((value, c))
        rows.sort(key=lambda t: (-t[0], t[1].facts.instrument.symbol))
        out[spec.key] = [
            {"rank": i + 1, "instrument_id": c.instrument_id, "score_id": c.score_id, "symbol": c.facts.instrument.symbol,
             "exchange": c.facts.instrument.exchange, "board_score": round(v - (1000 if spec.key == "best_overall" and
                                                                                c.primary_eligible else 0), 2),
             "grade": c.score.grade, "assessment": c.assessment, "primary_eligible": c.primary_eligible,
             "method": spec.method}
            for i, (v, c) in enumerate(rows[:size])
        ]
    return out


BOARD_TITLES = {b.key: b.title for b in BOARDS}
