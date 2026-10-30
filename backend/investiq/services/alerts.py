"""Deterministic price alerts (no AI): price above/below a threshold, or a large daily move."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.data import repository as repo
from investiq.models import Alert, Instrument
from investiq.notify.service import notify


def check_alerts(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    fired = 0
    for a in session.execute(select(Alert).where(Alert.active.is_(True))).scalars():
        bars = repo.daily_bars(session, a.instrument_id, now, lookback_days=10)
        if not bars:
            continue
        last = bars[-1]
        inst = session.get(Instrument, a.instrument_id)
        hit, msg = False, ""
        if a.kind == "price_above" and a.threshold is not None and last.close >= a.threshold:
            hit, msg = True, f"{inst.symbol} closed at {last.close:.2f} {last.currency}, above {a.threshold:.2f}"
        elif a.kind == "price_below" and a.threshold is not None and last.close <= a.threshold:
            hit, msg = True, f"{inst.symbol} closed at {last.close:.2f} {last.currency}, below {a.threshold:.2f}"
        elif a.kind == "pct_move_day" and a.threshold is not None and len(bars) >= 2:
            move = (last.close / bars[-2].close - 1) * 100
            if abs(move) >= a.threshold:
                hit, msg = True, f"{inst.symbol} moved {move:+.1f}% on {last.ts.date()}"
        if not hit:
            continue
        if a.last_triggered_at and now - a.last_triggered_at < timedelta(hours=20):
            continue
        a.last_triggered_at = now
        a.last_value = last.close
        notify(session, "price_alert", f"Alert: {inst.symbol}", msg + f" (source {last.source}, {last.data_status})",
               entity_type="instrument", entity_id=inst.id, dedupe_key=f"alert:{a.id}:{last.ts.date()}")
        fired += 1
    session.flush()
    return fired
