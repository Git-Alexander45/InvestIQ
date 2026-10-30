"""Portfolio-level diversification engine.

Answers "how diversified is this portfolio really?" using look-through ETF holdings when
reliable holdings data exists, and "what happens to the portfolio if we add X?".
Owning several ETFs is not treated as diversification by itself: overlap is measured.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from investiq.finance import overlap as ov
from investiq.finance.regions import currency_of, region_of
from investiq.finance.returns import correlation_matrix, max_drawdown
from investiq.scoring.assessment import FitResult


@dataclass
class Position:
    instrument_id: int
    symbol: str
    exchange: str
    name: str
    asset_class: str
    security_type: str
    value_cad: float
    currency: str
    country: str | None = None
    sector: str | None = None
    is_speculative: bool = False
    currency_hedged: bool | None = None
    constituents: list[ov.Constituent] | None = None
    holdings_as_of: str | None = None
    daily_returns: list[float] | None = None  # aligned, oldest first

    @property
    def is_fund(self) -> bool:
        return self.security_type in ("etf", "mutual_fund")


@dataclass
class DiversificationReport:
    total_value_cad: float
    cash_cad: float
    weights: dict[str, float]
    by_asset_class: dict[str, float]
    by_vehicle: dict[str, float]
    by_region: dict[str, float]
    by_country: dict[str, float]
    by_sector: dict[str, float]
    by_trading_currency: dict[str, float]
    by_underlying_currency: dict[str, float]
    top_companies: list[dict[str, Any]]
    etf_overlap: dict[str, dict[str, float]]
    effective_positions: float
    effective_companies: float
    lookthrough_coverage_pct: float
    correlations: dict[str, dict[str, float | None]] | None
    portfolio_volatility_pct: float | None
    portfolio_max_drawdown_pct: float | None
    factor_exposure: dict[str, Any]
    flags: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _pct(d: dict[str, float], total: float) -> dict[str, float]:
    if total <= 0:
        return {}
    return {k: round(v / total * 100, 3) for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if v > 0}


def analyse(positions: list[Position], cash_cad: float, limits: dict[str, float],
            market_returns: list[float] | None = None) -> DiversificationReport:
    invested = sum(p.value_cad for p in positions)
    total = invested + max(cash_cad, 0.0)
    weights = {p.symbol: (p.value_cad / total * 100 if total else 0.0) for p in positions}

    asset, vehicle, trading_ccy = defaultdict(float), defaultdict(float), defaultdict(float)
    for p in positions:
        asset[p.asset_class] += p.value_cad
        vehicle["fund" if p.is_fund else "direct"] += p.value_cad
        trading_ccy[p.currency] += p.value_cad
    if cash_cad > 0:
        asset["cash"] += cash_cad
        vehicle["cash"] += cash_cad
        trading_ccy["CAD"] += cash_cad

    lt_input = []
    for p in positions:
        itself = ov.Constituent(ov.normalise_key(p.symbol, p.name), p.name, 100.0, p.sector, p.country,
                                currency_of(p.country) or p.currency, p.asset_class if not p.is_fund else "etf")
        if p.is_fund and not p.constituents:
            itself.asset_class = "etf"
        lt_input.append((weights[p.symbol], p.constituents if p.is_fund else None, itself))
    exp = ov.look_through(lt_input)

    # Underlying currency: hedged funds count as CAD exposure.
    underlying_ccy: dict[str, float] = defaultdict(float)
    for p in positions:
        w = weights[p.symbol]
        if p.currency_hedged:
            underlying_ccy["CAD"] += w
        elif p.is_fund and p.constituents:
            captured = sum(c.weight_pct for c in p.constituents) or 100.0
            for c in p.constituents:
                underlying_ccy[c.currency or currency_of(c.country) or "Unknown"] += w * c.weight_pct / captured
        else:
            underlying_ccy[currency_of(p.country) or p.currency] += w
    if total:
        underlying_ccy["CAD"] += cash_cad / total * 100

    regions: dict[str, float] = defaultdict(float)
    for country, w in exp.by_country.items():
        regions[region_of(country)] += w
    if total and cash_cad > 0:
        regions["cash"] += cash_cad / total * 100

    companies = [{"key": k, "name": exp.company_names.get(k, k), "weight_pct": round(v, 3)}
                 for k, v in list(exp.by_company.items())[:15]]
    fund_holdings = {p.symbol: p.constituents for p in positions if p.is_fund and p.constituents}
    overlap = ov.overlap_matrix(fund_holdings) if len(fund_holdings) >= 2 else {}

    correlations = vol = mdd = None
    series = {p.symbol: p.daily_returns for p in positions if p.daily_returns and len(p.daily_returns) >= 60}
    if len(series) >= 1 and invested > 0:
        n = min(len(s) for s in series.values())
        mat = np.array([s[-n:] for s in series.values()])
        w = np.array([weights[k] for k in series]) / 100.0
        port = w @ mat  # weights are fractions of total value; cash contributes zero return
        vol = float(np.std(port, ddof=1) * np.sqrt(252) * 100) if n > 2 else None
        mdd = max_drawdown(np.cumprod(1 + port)) * 100
        correlations = correlation_matrix({k: v[-n:] for k, v in series.items()}) if len(series) >= 2 else None
        factor = _factor_exposure(port, market_returns)
    else:
        factor = {"note": "insufficient price history for factor estimates"}
    factor["style"] = _style_tilt(positions, weights)

    report = DiversificationReport(
        total_value_cad=round(total, 2), cash_cad=round(cash_cad, 2),
        weights={k: round(v, 3) for k, v in weights.items()},
        by_asset_class=_pct(asset, total), by_vehicle=_pct(vehicle, total),
        by_region={k: round(v, 3) for k, v in sorted(regions.items(), key=lambda kv: -kv[1])},
        by_country=exp.by_country, by_sector=exp.by_sector,
        by_trading_currency=_pct(trading_ccy, total),
        by_underlying_currency={k: round(v, 3) for k, v in sorted(underlying_ccy.items(), key=lambda kv: -kv[1])},
        top_companies=companies, etf_overlap=overlap,
        effective_positions=round(ov.effective_number(weights.values()), 2),
        effective_companies=round(ov.effective_number(exp.by_company.values()), 2),
        lookthrough_coverage_pct=round(100 - exp.unexplained_pct / max(sum(weights.values()), 1e-9) * 100, 2)
        if weights else 100.0,
        correlations=correlations, portfolio_volatility_pct=None if vol is None else round(vol, 3),
        portfolio_max_drawdown_pct=None if mdd is None else round(mdd, 3), factor_exposure=factor,
    )
    report.flags = _flags(report, positions, limits)
    return report


def _factor_exposure(port: np.ndarray, market: list[float] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if market and len(market) >= 60:
        n = min(len(market), len(port))
        m = np.asarray(market[-n:])
        p = port[-n:]
        var = np.var(m, ddof=1)
        if var > 0:
            out["market_beta"] = round(float(np.cov(p, m, ddof=1)[0, 1] / var), 3)
    out["note"] = "Market beta from daily returns; style tilts are holdings-based approximations."
    return out


def _style_tilt(positions: list[Position], weights: dict[str, float]) -> dict[str, float]:
    growth = value = defensive = 0.0
    for p in positions:
        w = weights[p.symbol]
        sector = (p.sector or "").lower()
        if sector in ("technology", "information technology", "communication services", "consumer discretionary"):
            growth += w
        elif sector in ("financials", "energy", "materials", "industrials"):
            value += w
        elif sector in ("utilities", "consumer staples", "health care", "healthcare") or p.asset_class in ("bond",
                                                                                                            "cash_equivalent"):
            defensive += w
    return {"growth_sectors_pct": round(growth, 2), "cyclical_value_sectors_pct": round(value, 2),
            "defensive_pct": round(defensive, 2)}


def _flags(r: DiversificationReport, positions: list[Position], limits: dict[str, float]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for p in positions:
        w = r.weights[p.symbol]
        if not p.is_fund and p.asset_class == "equity":
            cap = limits["max_speculative_position_pct"] if p.is_speculative else limits["max_stock_position_pct"]
            if w > cap:
                flags.append({"type": "position_size", "severity": "warning", "symbol": p.symbol,
                              "message": f"{p.symbol} is {w:.1f}% of the portfolio (guideline {cap:.0f}%)."})
        elif p.is_fund and w > limits["max_etf_position_pct"]:
            flags.append({"type": "position_size", "severity": "info", "symbol": p.symbol,
                          "message": f"{p.symbol} is {w:.1f}% of the portfolio (guideline {limits['max_etf_position_pct']:.0f}%)."})
    for sector, w in r.by_sector.items():
        if sector != "Unknown" and w > limits["sector_flag_pct"]:
            sev = "warning" if w > limits["sector_max_pct"] else "info"
            flags.append({"type": "sector_concentration", "severity": sev, "sector": sector,
                          "message": f"{sector} exposure is {w:.1f}% (flag above {limits['sector_flag_pct']:.0f}%)."})
    for country, w in r.by_country.items():
        if country != "Unknown" and w > limits["country_flag_pct"]:
            flags.append({"type": "country_concentration", "severity": "info", "country": country,
                          "message": f"{country} exposure is {w:.1f}% of the portfolio."})
    for c in r.top_companies:
        if c["weight_pct"] > limits["single_company_lookthrough_flag_pct"]:
            flags.append({"type": "company_lookthrough", "severity": "warning", "company": c["name"],
                          "message": f"Look-through exposure to {c['name']} is {c['weight_pct']:.1f}% across holdings."})
    seen = set()
    for a, row in r.etf_overlap.items():
        for b, v in row.items():
            if a < b and (a, b) not in seen and v > limits["etf_overlap_flag_pct"]:
                seen.add((a, b))
                flags.append({"type": "etf_overlap", "severity": "warning", "funds": [a, b],
                              "message": f"{a} and {b} overlap by {v:.0f}% of holdings weight."})
    if r.lookthrough_coverage_pct < 80:
        flags.append({"type": "data_coverage", "severity": "info",
                      "message": f"Only {r.lookthrough_coverage_pct:.0f}% of fund weight has look-through holdings data."})
    return flags


def what_if(positions: list[Position], cash_cad: float, candidate: Position, weight_pct: float,
            limits: dict[str, float]) -> tuple[FitResult, DiversificationReport, DiversificationReport]:
    """Evaluate adding ``candidate`` at ``weight_pct`` of total value, funded from cash (or scaled down)."""
    before = analyse(positions, cash_cad, limits)
    total = before.total_value_cad
    add_value = total * weight_pct / 100
    funded_cash = cash_cad - add_value
    new_positions = [Position(**{**p.__dict__}) for p in positions]
    if funded_cash < 0:
        # Not enough cash: scale existing positions down proportionally (pure what-if).
        scale_f = (total - add_value) / max(sum(p.value_cad for p in positions), 1e-9) if positions else 0
        for p in new_positions:
            p.value_cad *= scale_f
        funded_cash = 0.0
    existing = next((p for p in new_positions if p.instrument_id == candidate.instrument_id), None)
    if existing:
        existing.value_cad += add_value
    else:
        new_positions.append(Position(**{**candidate.__dict__, "value_cad": add_value}))
    after = analyse(new_positions, funded_cash, limits)
    before_keys = {(f["type"], f["severity"], f.get("sector"), f.get("company"), f.get("symbol"), tuple(f.get("funds", [])))
                   for f in before.flags}
    new_flags = [f for f in after.flags
                 if (f["type"], f["severity"], f.get("sector"), f.get("company"), f.get("symbol"), tuple(f.get("funds", [])))
                 not in before_keys and f["severity"] == "warning"]
    fit = FitResult(acceptable=not new_flags, flags=[f["message"] for f in new_flags],
                    detail={"weight_pct": weight_pct,
                            "effective_companies_before": before.effective_companies,
                            "effective_companies_after": after.effective_companies,
                            "sector_after": dict(list(after.by_sector.items())[:5])})
    return fit, before, after
