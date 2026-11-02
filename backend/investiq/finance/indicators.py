"""Technical indicators for charts. All series are oldest-first; leading values are None."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

Series = list[float | None]


def sma(values: Sequence[float], period: int) -> Series:
    if period <= 0:
        raise ValueError("period must be positive")
    out: Series = []
    window_sum = 0.0
    for i, v in enumerate(values):
        window_sum += v
        if i >= period:
            window_sum -= values[i - period]
        out.append(window_sum / period if i >= period - 1 else None)
    return out


def ema(values: Sequence[float], period: int) -> Series:
    if period <= 0:
        raise ValueError("period must be positive")
    out: Series = []
    k = 2 / (period + 1)
    prev: float | None = None
    for i, v in enumerate(values):
        if i < period - 1:
            out.append(None)
            continue
        if prev is None:
            prev = sum(values[i - period + 1 : i + 1]) / period
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """Wilder's RSI."""
    out: Series = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0)
        losses += max(-change, 0)
    avg_gain, avg_loss = gains / period, losses / period

    def _value(g: float, l_: float) -> float:
        if l_ == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / l_)

    out[period] = _value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        out[i] = _value(avg_gain, avg_loss)
    return out


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, Series]:
    fast_e, slow_e = ema(values, fast), ema(values, slow)
    line: Series = [f - s if f is not None and s is not None else None for f, s in zip(fast_e, slow_e, strict=True)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig: Series = [None] * len(values)
    if first is not None:
        tail = [v for v in line[first:] if v is not None]
        sig_tail = ema(tail, signal)
        sig[first:] = sig_tail
    hist: Series = [m - s if m is not None and s is not None else None for m, s in zip(line, sig, strict=True)]
    return {"macd": line, "signal": sig, "histogram": hist}


def bollinger(values: Sequence[float], period: int = 20, num_std: float = 2.0) -> dict[str, Series]:
    mid = sma(values, period)
    upper: Series = []
    lower: Series = []
    for i, m in enumerate(mid):
        if m is None:
            upper.append(None)
            lower.append(None)
            continue
        window = values[i - period + 1 : i + 1]
        var = sum((x - m) ** 2 for x in window) / period
        sd = var**0.5
        upper.append(m + num_std * sd)
        lower.append(m - num_std * sd)
    return {"middle": mid, "upper": upper, "lower": lower}


def resample_ohlcv(bars: Sequence[dict], period: str) -> list[dict]:
    """Aggregate daily bars into weekly ("1wk", ISO week) or monthly ("1mo") bars."""
    if period not in {"1wk", "1mo"}:
        raise ValueError("period must be 1wk or 1mo")
    buckets: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for bar in bars:
        ts: datetime = bar["ts"]
        key = tuple(ts.isocalendar()[:2]) if period == "1wk" else (ts.year, ts.month)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(bar)
    out = []
    for key in order:
        group = buckets[key]
        out.append({
            "ts": group[0]["ts"],
            "open": group[0]["open"],
            "high": max(b["high"] for b in group),
            "low": min(b["low"] for b in group),
            "close": group[-1]["close"],
            "volume": sum((b.get("volume") or 0) for b in group),
        })
    return out
