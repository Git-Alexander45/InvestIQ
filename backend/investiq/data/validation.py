"""Data-quality checks. Problems are recorded, never silently "fixed" with invented values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from investiq.data.providers.base import BarDTO


@dataclass
class Issue:
    issue_type: str  # invalid, outlier, stale, missing, discrepancy
    severity: str  # info, warning, error
    message: str
    detail: dict


def validate_bars(bars: list[BarDTO], *, max_daily_move: float = 0.4,
                  split_dates: set[date] | None = None) -> tuple[list[BarDTO], list[Issue]]:
    """Drop structurally invalid bars, flag suspicious ones. Returns (clean_bars, issues)."""
    clean: list[BarDTO] = []
    issues: list[Issue] = []
    seen: set[datetime] = set()
    split_dates = split_dates or set()
    prev: BarDTO | None = None
    for b in sorted(bars, key=lambda x: x.ts):
        if b.ts in seen:
            issues.append(Issue("invalid", "warning", f"duplicate bar at {b.ts.isoformat()}", {"ts": b.ts.isoformat()}))
            continue
        if min(b.open, b.high, b.low, b.close) <= 0:
            issues.append(Issue("invalid", "warning", f"non-positive price at {b.ts.date()}", {"ts": b.ts.isoformat()}))
            continue
        if b.high < max(b.open, b.close) - 1e-9 or b.low > min(b.open, b.close) + 1e-9 or b.high < b.low:
            issues.append(Issue("invalid", "warning", f"inconsistent OHLC at {b.ts.date()}", {"ts": b.ts.isoformat()}))
            continue
        if b.volume is not None and b.volume < 0:
            issues.append(Issue("invalid", "warning", f"negative volume at {b.ts.date()}", {"ts": b.ts.isoformat()}))
            continue
        if prev is not None and b.ts.date() not in split_dates:
            move = b.close / prev.close - 1
            if abs(move) > max_daily_move:
                issues.append(Issue("outlier", "warning",
                                    f"{move:+.0%} move on {b.ts.date()} without a recorded split (kept, flagged)",
                                    {"ts": b.ts.isoformat(), "move": move}))
        seen.add(b.ts)
        clean.append(b)
        prev = b
    return clean, issues


def business_days_between(a: date, b: date) -> int:
    if b <= a:
        return 0
    days, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def staleness(last: date | None, today: date, stale_after_business_days: int) -> Issue | None:
    if last is None:
        return Issue("missing", "warning", "no price data", {})
    lag = business_days_between(last, today)
    if lag > stale_after_business_days:
        return Issue("stale", "warning", f"latest price is {lag} business days old ({last.isoformat()})",
                     {"last": last.isoformat(), "lag_business_days": lag})
    return None


def discrepancy(a_value: float, b_value: float, a_source: str, b_source: str, tolerance_pct: float) -> Issue | None:
    if a_value <= 0 or b_value <= 0:
        return None
    diff = abs(a_value / b_value - 1) * 100
    if diff > tolerance_pct:
        return Issue("discrepancy", "warning",
                     f"{a_source} ({a_value:.4f}) and {b_source} ({b_value:.4f}) differ by {diff:.2f}%",
                     {"a": a_value, "b": b_value, "a_source": a_source, "b_source": b_source, "diff_pct": diff})
    return None
