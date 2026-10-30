"""Duplicate-run prevention and "is the daily cycle due?" logic (sleep/shutdown catch-up)."""

from __future__ import annotations

import os
import socket
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from investiq.models import ResearchCycle
from investiq.services.preferences import get_pref

STALE_AFTER = timedelta(minutes=45)
MAX_ATTEMPTS_PER_DAY = 3
DONE = ("succeeded", "succeeded_degraded")


class CycleNotDue(Exception):
    pass


def owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def latest_occurrence(now: datetime, time_local: str, tz: str) -> tuple[date, datetime]:
    """The most recent scheduled run time at or before ``now`` and the research day it belongs to."""
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    t = time.fromisoformat(time_local)
    today_run = datetime.combine(local.date(), t, zone)
    if local >= today_run:
        return local.date(), today_run.astimezone(UTC)
    prev = local.date() - timedelta(days=1)
    return prev, datetime.combine(prev, t, zone).astimezone(UTC)


def due_cycle_date(session: Session, now: datetime | None = None) -> date | None:
    """Research day that should run now, or None. A missed run (computer asleep or off) becomes due
    as soon as the application is next running, without double-running a completed day."""
    now = now or datetime.now(UTC)
    sched = get_pref(session, "research_schedule")
    if not sched.enabled:
        return None
    cycle_date, _ = latest_occurrence(now, sched.time_local, sched.timezone)
    rows = list(session.execute(select(ResearchCycle).where(ResearchCycle.cycle_date == cycle_date,
                                                            ResearchCycle.kind == "daily")).scalars())
    if any(r.status in DONE for r in rows):
        return None
    if any(r.status == "running" and now - r.heartbeat_at < STALE_AFTER for r in rows):
        return None
    if len(rows) >= MAX_ATTEMPTS_PER_DAY:
        return None
    last_success = session.execute(select(ResearchCycle.cycle_date).where(ResearchCycle.status.in_(DONE))
                                   .order_by(ResearchCycle.cycle_date.desc()).limit(1)).scalar_one_or_none()
    if not sched.catch_up_if_missed and last_success is not None and last_success < cycle_date - timedelta(days=1):
        return None
    return cycle_date


def acquire(session: Session, cycle_date: date, triggered_by: str, now: datetime | None = None,
            force: bool = False) -> ResearchCycle:
    """Create the running cycle row. Raises CycleNotDue if another run is active or the day is done."""
    now = now or datetime.now(UTC)
    rows = list(session.execute(select(ResearchCycle).where(ResearchCycle.cycle_date == cycle_date,
                                                            ResearchCycle.kind == "daily")
                                .order_by(ResearchCycle.attempt)).scalars())
    for r in rows:
        if r.status == "running":
            if now - r.heartbeat_at < STALE_AFTER:
                raise CycleNotDue(f"cycle {r.id} is already running (owner {r.lock_owner})")
            r.status, r.finished_at = "abandoned", now
            r.error = (r.error or "") + " Abandoned: no heartbeat (process stopped or computer slept)."
        elif r.status in DONE and not force:
            raise CycleNotDue(f"research for {cycle_date} already completed (cycle {r.id})")
    if not force and len([r for r in rows if r.status != "abandoned"]) >= MAX_ATTEMPTS_PER_DAY:
        raise CycleNotDue(f"maximum attempts reached for {cycle_date}")
    attempt = (rows[-1].attempt + 1) if rows else 1
    cycle = ResearchCycle(cycle_date=cycle_date, kind="daily", attempt=attempt, status="running",
                          triggered_by=triggered_by, started_at=now, heartbeat_at=now, lock_owner=owner())
    session.add(cycle)
    try:
        session.commit()
    except IntegrityError as exc:  # a concurrent process inserted the same attempt first
        session.rollback()
        raise CycleNotDue("another process started this cycle at the same moment") from exc
    return cycle


def heartbeat(session: Session, cycle: ResearchCycle) -> None:
    cycle.heartbeat_at = datetime.now(UTC)
    session.commit()
