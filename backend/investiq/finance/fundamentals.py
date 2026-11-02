"""Derive comparable metrics from normalised provider fundamentals.

Providers map their payloads into the canonical ``metrics`` keys below (all annual, in the
reporting currency). Anything a provider cannot supply is simply absent: derived metrics are
then ``None`` and the scoring engine records reduced coverage instead of inventing values.

Canonical inputs (optional):
  revenue_history, eps_history, fcf_history, gross_profit_history, operating_income_history,
  dividend_per_share_history: list of {"year": int, "value": float}, oldest first
  total_debt, cash, total_equity, current_assets, current_liabilities, interest_expense,
  ebitda, net_income, shares_outstanding, market_cap, enterprise_value, roic_pct, beta,
  pe_ttm, forward_pe, ev_ebitda, dividend_yield_pct, payout_ratio_pct
ETF inputs (optional):
  aum, expense_ratio_pct, holdings_count, distribution_yield_pct, avg_duration_years,
  credit_quality ("government", "investment_grade", "mixed", "high_yield"),
  structure ("physical", "futures", "synthetic", "equity_holdings"), weighted_pe,
  weighted_revenue_growth_pct
"""

from __future__ import annotations

from typing import Any

import numpy as np

from investiq.finance.returns import growth_cagr


def _series(metrics: dict[str, Any], key: str) -> list[float]:
    raw = metrics.get(key) or []
    out = []
    for item in raw:
        v = item.get("value") if isinstance(item, dict) else item
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _num(metrics: dict[str, Any], key: str) -> float | None:
    v = metrics.get(key)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _pct_change(series: list[float]) -> float | None:
    if len(series) < 2 or series[-2] <= 0:
        return None
    return (series[-1] / series[-2] - 1) * 100


def _cagr_pct(series: list[float], years: int) -> float | None:
    if len(series) < years + 1:
        return None
    g = growth_cagr(series[-(years + 1)], series[-1], years)
    return None if g is None else g * 100


def derive(metrics: dict[str, Any]) -> dict[str, float | None]:
    revenue = _series(metrics, "revenue_history")
    eps = _series(metrics, "eps_history")
    fcf = _series(metrics, "fcf_history")
    gross = _series(metrics, "gross_profit_history")
    opinc = _series(metrics, "operating_income_history")
    dps = _series(metrics, "dividend_per_share_history")

    d: dict[str, float | None] = {}
    d["revenue_growth_1y_pct"] = _pct_change(revenue)
    d["revenue_cagr_3y_pct"] = _cagr_pct(revenue, 3)
    d["eps_growth_1y_pct"] = _pct_change(eps)
    d["eps_cagr_3y_pct"] = _cagr_pct(eps, 3)
    d["fcf_cagr_3y_pct"] = _cagr_pct(fcf, 3)
    d["dividend_cagr_5y_pct"] = _cagr_pct(dps, 5)
    d["dividend_growth_years"] = float(_consecutive_increases(dps)) if dps else None

    latest_rev = revenue[-1] if revenue else None
    d["fcf_margin_pct"] = (fcf[-1] / latest_rev * 100) if fcf and latest_rev else None
    d["gross_margin_pct"] = (gross[-1] / latest_rev * 100) if gross and latest_rev else None
    d["operating_margin_pct"] = (opinc[-1] / latest_rev * 100) if opinc and latest_rev else None
    if gross and len(gross) >= 3 and len(revenue) >= len(gross):
        margins = [g / r * 100 for g, r in zip(gross[-len(revenue):], revenue[-len(gross):], strict=False) if r]
        d["gross_margin_stability_pp"] = float(np.std(margins)) if len(margins) >= 3 else None
    else:
        d["gross_margin_stability_pp"] = None

    debt, cash, equity = _num(metrics, "total_debt"), _num(metrics, "cash"), _num(metrics, "total_equity")
    ebitda = _num(metrics, "ebitda")
    d["debt_to_equity"] = (debt / equity) if debt is not None and equity and equity > 0 else None
    if equity is not None and equity <= 0 and debt:
        d["debt_to_equity"] = 10.0  # negative equity with debt: treat as extremely leveraged
    d["net_debt_to_ebitda"] = ((debt or 0) - (cash or 0)) / ebitda if ebitda and ebitda > 0 and debt is not None else None
    ca, cl = _num(metrics, "current_assets"), _num(metrics, "current_liabilities")
    d["current_ratio"] = ca / cl if ca is not None and cl else None
    interest = _num(metrics, "interest_expense")
    op_latest = opinc[-1] if opinc else None
    if interest is not None and op_latest is not None:
        d["interest_coverage"] = op_latest / abs(interest) if interest != 0 else 100.0
    else:
        d["interest_coverage"] = None

    mcap = _num(metrics, "market_cap")
    d["fcf_yield_pct"] = (fcf[-1] / mcap * 100) if fcf and mcap else None
    pe = _num(metrics, "pe_ttm")
    d["pe"] = pe if pe is not None and pe > 0 else None
    d["forward_pe"] = _num(metrics, "forward_pe")
    d["ev_ebitda"] = _num(metrics, "ev_ebitda")
    growth = d["eps_cagr_3y_pct"] if d["eps_cagr_3y_pct"] is not None else d["revenue_cagr_3y_pct"]
    pe_for_peg = d["forward_pe"] or d["pe"]
    d["peg"] = pe_for_peg / growth if pe_for_peg and growth and growth > 0 else None
    d["roic_pct"] = _num(metrics, "roic_pct")
    d["beta_reported"] = _num(metrics, "beta")
    d["dividend_yield_pct"] = _num(metrics, "dividend_yield_pct")
    payout = _num(metrics, "payout_ratio_pct")
    d["payout_ratio_pct"] = payout
    net_income = _num(metrics, "net_income")
    if payout is None and dps and net_income and _num(metrics, "shares_outstanding"):
        d["payout_ratio_pct"] = dps[-1] * _num(metrics, "shares_outstanding") / net_income * 100  # type: ignore[operator]
    if fcf and dps and _num(metrics, "shares_outstanding") and fcf[-1] > 0:
        d["fcf_payout_pct"] = dps[-1] * _num(metrics, "shares_outstanding") / fcf[-1] * 100  # type: ignore[operator]
    else:
        d["fcf_payout_pct"] = None

    # ETF / fund metrics pass through.
    for key in ("aum", "expense_ratio_pct", "holdings_count", "distribution_yield_pct", "avg_duration_years",
                "weighted_pe", "weighted_revenue_growth_pct", "yield_to_maturity_pct"):
        d[key] = _num(metrics, key)
    for key in ("credit_quality", "structure"):
        d[key] = metrics.get(key)  # type: ignore[assignment]
    return d


def _consecutive_increases(series: list[float]) -> int:
    count = 0
    for prev, cur in zip(series[-2::-1], series[::-1], strict=False):
        if cur > prev:
            count += 1
        else:
            break
    return count
