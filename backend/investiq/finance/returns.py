"""Return and risk statistics on price / value series."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

import numpy as np

TRADING_DAYS = 252


def simple_returns(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size < 2:
        return np.array([], dtype=float)
    if np.any(arr[:-1] <= 0):
        raise ValueError("values must be positive to compute returns")
    return arr[1:] / arr[:-1] - 1.0


def total_return(start_value: float, end_value: float) -> float:
    if start_value <= 0:
        raise ValueError("start value must be positive")
    return end_value / start_value - 1.0


def cagr(start_value: float, end_value: float, start: date, end: date) -> float | None:
    days = (end - start).days
    if days <= 0 or start_value <= 0 or end_value <= 0:
        return None
    years = days / 365.25
    if years < 1 / 365.25:
        return None
    return (end_value / start_value) ** (1 / years) - 1.0


def growth_cagr(first: float | None, last: float | None, years: float) -> float | None:
    """CAGR between two fundamentals values (e.g. revenue); None when undefined (non-positive)."""
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1.0


def annualized_volatility(returns: Sequence[float], periods_per_year: int = TRADING_DAYS) -> float | None:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return None
    return float(np.std(r, ddof=1) * math.sqrt(periods_per_year))


def max_drawdown(values: Sequence[float]) -> float:
    """Most negative peak-to-trough decline, as a negative fraction (0.0 when none)."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(arr)
    drawdowns = arr / peaks - 1.0
    return float(drawdowns.min())


def sharpe_ratio(returns: Sequence[float], risk_free_annual: float = 0.0,
                 periods_per_year: int = TRADING_DAYS) -> float | None:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return None
    excess = r - risk_free_annual / periods_per_year
    sd = np.std(excess, ddof=1)
    if sd == 0:
        return None
    return float(np.mean(excess) / sd * math.sqrt(periods_per_year))


def sortino_ratio(returns: Sequence[float], risk_free_annual: float = 0.0,
                  periods_per_year: int = TRADING_DAYS) -> float | None:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return None
    excess = r - risk_free_annual / periods_per_year
    downside = excess[excess < 0]
    if downside.size < 2:
        return None
    dd = math.sqrt(float(np.mean(downside**2)))
    if dd == 0:
        return None
    return float(np.mean(excess) / dd * math.sqrt(periods_per_year))


def beta(asset_returns: Sequence[float], market_returns: Sequence[float]) -> float | None:
    a = np.asarray(asset_returns, dtype=float)
    m = np.asarray(market_returns, dtype=float)
    n = min(a.size, m.size)
    if n < 20:
        return None
    a, m = a[-n:], m[-n:]
    var = np.var(m, ddof=1)
    if var == 0:
        return None
    return float(np.cov(a, m, ddof=1)[0, 1] / var)


def correlation_matrix(series: dict[str, Sequence[float]], min_overlap: int = 20) -> dict[str, dict[str, float | None]]:
    """Pairwise correlations on aligned return series (aligned by the caller, same length)."""
    keys = list(series)
    out: dict[str, dict[str, float | None]] = {k: {} for k in keys}
    for i, a in enumerate(keys):
        for b in keys[i:]:
            x = np.asarray(series[a], dtype=float)
            y = np.asarray(series[b], dtype=float)
            n = min(x.size, y.size)
            if n < min_overlap:
                value = None
            elif a == b:
                value = 1.0
            else:
                x, y = x[-n:], y[-n:]
                if np.std(x) == 0 or np.std(y) == 0:
                    value = None
                else:
                    value = float(np.corrcoef(x, y)[0, 1])
            out[a][b] = value
            out[b][a] = value
    return out


def win_rate(pnls: Sequence[float]) -> float | None:
    closed = [p for p in pnls if p is not None]
    if not closed:
        return None
    return sum(1 for p in closed if p > 0) / len(closed)


def portfolio_volatility(weights: Sequence[float], cov_annual: np.ndarray) -> float:
    w = np.asarray(weights, dtype=float)
    return float(math.sqrt(max(w @ cov_annual @ w, 0.0)))
