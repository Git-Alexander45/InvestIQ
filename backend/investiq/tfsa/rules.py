"""Canadian TFSA analysis.

Rules encoded here are general tax facts with known limits, not tax advice:

* Qualified investments include securities listed on a *designated stock exchange* (Income Tax
  Act s.204 / Finance Canada list). The list below must be re-checked against the official page
  (``DESIGNATED_EXCHANGES_SOURCE``); anything not on it is reported as UNKNOWN, never assumed.
* A TFSA is not recognised as a retirement account under the Canada-US tax treaty, so US
  withholding tax (generally 15% on dividends for Canadian residents) is not recovered inside a
  TFSA. Foreign withholding inside a fund is also unrecoverable. InvestIQ estimates this drag.
* Contribution room is never inferred. It is shown only when the owner has entered it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from investiq.scoring.curves import scale
from investiq.scoring.engine import Facts, ScoreResult

DESIGNATED_EXCHANGES_SOURCE = "https://www.canada.ca/en/department-finance/services/designated-stock-exchanges.html"
# Exchange codes as used by InvestIQ. Re-verify periodically against the official list.
DESIGNATED_EXCHANGES = {
    "TSX", "TSXV", "CSE", "NEO", "CBOE_CA",  # Canada
    "NYSE", "NYSEARCA", "NYSEAMERICAN", "NASDAQ", "CBOE_US", "BATS",  # United States
    "LSE", "XETRA", "FWB", "EURONEXT", "SIX", "TSE", "HKEX", "ASX", "SGX",
}
NOT_QUALIFIED_VENUES = {"OTC", "OTCMKTS", "PINK", "GREY"}

US_DIVIDEND_WITHHOLDING = 0.15
OTHER_FOREIGN_WITHHOLDING_ASSUMPTION = 0.10  # broad assumption for non-US foreign dividends


@dataclass
class TfsaResult:
    qualified_status: str  # LIKELY_QUALIFIED, NOT_QUALIFIED, UNKNOWN
    qualified_evidence: str
    eligible: bool
    score: float | None
    withholding_drag_pct: float | None  # estimated annual return drag, percentage points
    notes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    components: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def qualified_status(exchange: str) -> tuple[str, str]:
    ex = exchange.upper()
    if ex in NOT_QUALIFIED_VENUES:
        return "NOT_QUALIFIED", f"{ex} is not a designated stock exchange"
    if ex in DESIGNATED_EXCHANGES:
        return "LIKELY_QUALIFIED", (f"Listed on {ex}, which InvestIQ's list records as a designated stock exchange "
                                    f"(verify: {DESIGNATED_EXCHANGES_SOURCE})")
    return "UNKNOWN", f"{ex} is not in InvestIQ's designated-exchange list; verify before holding in a TFSA"


def withholding_drag(facts: Facts, country_exposure: dict[str, float] | None) -> tuple[float | None, list[str]]:
    """Estimated annual drag (percentage points of return) from unrecoverable foreign withholding."""
    inst = facts.instrument
    f = facts.fundamentals or {}
    yld = f.get("dividend_yield_pct") or f.get("distribution_yield_pct")
    assumptions: list[str] = []
    if yld is None:
        return None, ["No yield data: withholding drag not estimated."]
    if yld <= 0:
        return 0.0, assumptions
    if inst.security_type in ("etf", "mutual_fund"):
        if not country_exposure:
            return None, ["No look-through country data: withholding drag not estimated."]
        total = sum(country_exposure.values()) or 100.0
        us = country_exposure.get("US", 0.0) / total
        other = sum(v for k, v in country_exposure.items() if k not in ("US", "CA", "Unknown")) / total
        rate = us * US_DIVIDEND_WITHHOLDING + other * OTHER_FOREIGN_WITHHOLDING_ASSUMPTION
        if inst.exchange in ("NYSE", "NYSEARCA", "NASDAQ", "CBOE_US", "BATS") and other > 0:
            # US-listed fund of foreign stocks: foreign tax at the fund plus 15% US on distributions.
            rate = us * US_DIVIDEND_WITHHOLDING + other * (1 - (1 - OTHER_FOREIGN_WITHHOLDING_ASSUMPTION) *
                                                          (1 - US_DIVIDEND_WITHHOLDING))
            assumptions.append("US-listed fund holding non-US stocks: two layers of withholding assumed.")
        assumptions.append(f"US dividends withheld at {US_DIVIDEND_WITHHOLDING:.0%}; other foreign dividends "
                           f"assumed {OTHER_FOREIGN_WITHHOLDING_ASSUMPTION:.0%} (actual rates vary by country).")
        assumptions.append("Assumes the fund's yield is spread in proportion to country weights.")
        return round(yld * rate, 4), assumptions
    country = inst.country or "Unknown"
    if country == "CA":
        return 0.0, ["Canadian issuer: no foreign withholding."]
    if country == "US":
        assumptions.append("US issuer: 15% US withholding is not recovered in a TFSA.")
        return round(yld * US_DIVIDEND_WITHHOLDING, 4), assumptions
    if country == "Unknown":
        return None, ["Issuer country unknown: withholding drag not estimated."]
    assumptions.append(f"Foreign issuer ({country}): withholding assumed {OTHER_FOREIGN_WITHHOLDING_ASSUMPTION:.0%}; "
                       "actual rates vary and are not recovered in a TFSA.")
    return round(yld * OTHER_FOREIGN_WITHHOLDING_ASSUMPTION, 4), assumptions


def evaluate(facts: Facts, score: ScoreResult, *, country_exposure: dict[str, float] | None = None,
             top10_pct: float | None = None) -> TfsaResult:
    inst = facts.instrument
    status, evidence = qualified_status(inst.exchange)
    notes: list[str] = []
    drag, assumptions = withholding_drag(facts, country_exposure)
    if inst.is_leveraged or inst.is_inverse:
        return TfsaResult(status, evidence, False, None, drag,
                          ["Leveraged/inverse products are excluded from TFSA candidates."], assumptions)
    if status == "NOT_QUALIFIED":
        return TfsaResult(status, evidence, False, None, drag, ["Not a qualified investment."], assumptions)
    if status == "UNKNOWN":
        notes.append("Qualified-investment status unknown; excluded until verified.")
        return TfsaResult(status, evidence, False, None, drag, notes, assumptions)

    comps: dict[str, Any] = {"overall": score.overall}
    parts = [(score.overall, 0.6)]
    mer = inst.mer_pct if inst.mer_pct is not None else (facts.fundamentals or {}).get("expense_ratio_pct")
    if mer is not None:
        s = scale(mer, [(0.05, 100), (0.25, 80), (0.6, 50), (1.0, 25), (2.0, 0)])
        parts.append((s, 0.15))
        comps["mer_pct"] = mer
    if drag is not None:
        s = scale(drag, [(0, 100), (0.15, 80), (0.3, 55), (0.6, 25), (1.0, 5)])
        parts.append((s, 0.15))
        comps["withholding_drag_pct"] = drag
    else:
        notes.append("Foreign withholding drag could not be estimated.")
    if top10_pct is not None or inst.security_type not in ("etf", "mutual_fund"):
        conc = 100.0 if inst.security_type not in ("etf", "mutual_fund") else (top10_pct or 0)
        s = scale(conc, [(20, 100), (40, 75), (60, 45), (100, 20)])
        parts.append((s, 0.10))
        comps["concentration_pct"] = conc
        if inst.security_type not in ("etf", "mutual_fund"):
            notes.append("Single company: concentration risk inside the TFSA.")
    total_w = sum(w for _, w in parts)
    tfsa_score = round(sum(v * w for v, w in parts) / total_w, 2)
    if inst.exchange in ("TSX", "NEO", "CBOE_CA", "TSXV") and country_exposure:
        foreign = sum(v for k, v in country_exposure.items() if k not in ("CA", "Unknown"))
        if foreign > 50:
            notes.append(f"Canadian-listed, but about {foreign:.0f}% of underlying exposure is outside Canada.")
    if inst.currency != "CAD":
        notes.append(f"Trades in {inst.currency}: currency conversion costs apply when buying from CAD.")
    if inst.currency_hedged is False:
        notes.append("Unhedged: CAD returns depend on exchange-rate moves.")
    return TfsaResult(status, evidence, True, tfsa_score, drag, notes, assumptions, comps)


def pick_candidates(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """rows: [{"symbol", "tfsa_score", "growth", "dividend", "primary_eligible", ...}]"""
    eligible = [r for r in rows if r.get("tfsa_score") is not None]

    def best(key: str) -> dict[str, Any] | None:
        pool = [r for r in eligible if r.get(key) is not None]
        pool.sort(key=lambda r: (not r.get("primary_eligible", False), -(r[key] or 0)))
        return pool[0] if pool else None

    return {"best_overall": best("tfsa_score"), "best_growth": best("growth"), "best_dividend": best("dividend")}
