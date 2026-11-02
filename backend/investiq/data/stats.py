"""Price-derived statistics computed point-in-time from stored daily bars."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from investiq.finance.indicators import sma
from investiq.finance.returns import annualized_volatility, beta, max_drawdown, sharpe_ratio
from investiq.models import PriceBar


def _series(bars: list[PriceBar]) -> tuple[list[datetime], list[float], str]:
    use_adj = all(b.adj_close for b in bars) and bool(bars)
    values = [float(b.adj_close if use_adj else b.close) for b in bars]
    return [b.ts for b in bars], values, "total_return_adjusted" if use_adj else "price_only"


def _window(ts: list[datetime], values: list[float], as_of: datetime, days: int) -> list[float]:
    cutoff = as_of - timedelta(days=days)
    return [v for t, v in zip(ts, values, strict=True) if t >= cutoff]


def _ann_return(window: list[float], years: float) -> float | None:
    if len(window) < 2 or window[0] <= 0:
        return None
    return ((window[-1] / window[0]) ** (1 / years) - 1) * 100


def price_stats(bars: list[PriceBar], as_of: datetime, market_bars: list[PriceBar] | None = None,
                risk_free_annual: float = 0.0) -> dict[str, Any] | None:
    if len(bars) < 20:
        return None
    ts, values, basis = _series(bars)
    rets = np.diff(values) / np.asarray(values[:-1])
    y1 = _window(ts, values, as_of, 365)
    y3 = _window(ts, values, as_of, 365 * 3)
    span_days = (ts[-1] - ts[0]).days
    out: dict[str, Any] = {
        "last_price": bars[-1].close, "last_date": bars[-1].ts.date().isoformat(), "currency": bars[-1].currency,
        "data_status": bars[-1].data_status, "return_basis": basis, "history_days": span_days,
    }
    r1 = np.diff(y1) / np.asarray(y1[:-1]) if len(y1) > 2 else np.array([])
    out["volatility_1y_pct"] = None if r1.size < 20 else round(annualized_volatility(r1) * 100, 3)
    out["max_drawdown_3y_pct"] = round(max_drawdown(y3) * 100, 3) if len(y3) > 20 else None
    out["return_1y_pct"] = round((y1[-1] / y1[0] - 1) * 100, 3) if span_days >= 360 and len(y1) > 1 else None
    out["return_3y_ann_pct"] = round(_ann_return(y3, 3), 3) if span_days >= 365 * 3 - 10 else None
    y5 = _window(ts, values, as_of, 365 * 5)
    out["return_5y_ann_pct"] = round(_ann_return(y5, 5), 3) if span_days >= 365 * 5 - 10 else None
    r3 = np.diff(y3) / np.asarray(y3[:-1]) if len(y3) > 2 else np.array([])
    s3 = sharpe_ratio(r3, risk_free_annual) if span_days >= 365 * 3 - 10 else None
    out["sharpe_3y"] = None if s3 is None else round(s3, 3)
    sma200 = sma(values, 200)[-1] if len(values) >= 200 else None
    out["price_vs_sma200_pct"] = None if not sma200 else round((values[-1] / sma200 - 1) * 100, 3)
    recent = bars[-60:]
    vols = [b.volume * b.close for b in recent if b.volume]
    out["avg_dollar_volume_m"] = round(float(np.mean(vols)) / 1e6, 3) if vols else None
    out["daily_returns"] = [float(x) for x in rets[-756:]]
    out["daily_dates"] = [t.date().isoformat() for t in ts[1:][-756:]]
    if market_bars and len(market_bars) > 60:
        mts, mvals, _ = _series(market_bars)
        m_by_date = dict(zip((t.date() for t in mts), mvals, strict=True))
        aligned = [(v, m_by_date[t.date()]) for t, v in zip(ts, values, strict=True) if t.date() in m_by_date]
        if len(aligned) > 60:
            a = np.array([x[0] for x in aligned])
            m = np.array([x[1] for x in aligned])
            ar, mr = np.diff(a) / a[:-1], np.diff(m) / m[:-1]
            b_ = beta(ar[-756:], mr[-756:])
            out["beta"] = None if b_ is None else round(b_, 3)
            if np.std(ar[-756:]) > 0 and np.std(mr[-756:]) > 0:
                out["corr_to_equities"] = round(float(np.corrcoef(ar[-756:], mr[-756:])[0, 1]), 3)
    return out


def align_returns(stats_by_symbol: dict[str, dict[str, Any]]) -> dict[str, list[float]]:
    """Align daily returns of several instruments on common dates."""
    date_sets = [set(s["daily_dates"]) for s in stats_by_symbol.values() if s and s.get("daily_dates")]
    if not date_sets:
        return {}
    common = sorted(set.intersection(*date_sets))
    out = {}
    for sym, s in stats_by_symbol.items():
        if not s or not s.get("daily_dates"):
            continue
        lookup = dict(zip(s["daily_dates"], s["daily_returns"], strict=True))
        out[sym] = [lookup[d] for d in common]
    return out
