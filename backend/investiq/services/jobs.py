"""Due-job runner shared by Windows Task Scheduler (``investiq run-cycle --if-due``) and the
in-process scheduler thread of the API server. Locking in ``research.locking`` makes it safe for
both to fire at the same moment: only one research cycle can run per day."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.db.session import get_engine, get_session
from investiq.models import BackupRecord, JobRun
from investiq.research import locking
from investiq.research.cycle import run_cycle

log = logging.getLogger(__name__)
BACKUP_EVERY = timedelta(hours=20)


def _job(session: Session, name: str, now: datetime) -> JobRun:
    j = JobRun(job=name, run_date=now.date(), status="running", started_at=now)
    session.add(j)
    session.commit()
    return j


def backup_if_due(session: Session, now: datetime | None = None) -> dict[str, Any]:
    from investiq.services import backup

    now = now or datetime.now(UTC)
    last = session.execute(select(BackupRecord).where(BackupRecord.status != "failed")
                           .order_by(BackupRecord.created_at.desc()).limit(1)).scalar_one_or_none()
    if last is not None and now - last.created_at < BACKUP_EVERY:
        return {"status": "not_due", "last_backup": last.created_at.isoformat()}
    engine = get_engine()
    if engine.dialect.name == "sqlite" and engine.url.database in (None, "", ":memory:"):
        return {"status": "skipped", "reason": "in-memory database"}
    j = _job(session, "backup", now)
    try:
        rec = backup.create_backup(session, engine, reason="daily")
        backup.verify_backup(session, rec)
        j.status, j.detail = ("succeeded" if rec.status == "verified" else "failed"), {"backup_id": rec.id}
    except Exception as exc:  # noqa: BLE001 - recorded and surfaced as a notification
        session.rollback()
        j.status, j.error = "failed", str(exc)[:2000]
        from investiq.notify.service import notify

        notify(session, "job_failed", "Daily backup failed", str(exc)[:400], severity="error",
               dedupe_key=f"backup:{now.date()}")
    j.finished_at = datetime.now(UTC)
    session.commit()
    return {"status": j.status, "error": j.error, **j.detail}


def run_due(session: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    out: dict[str, Any] = {}
    due = locking.due_cycle_date(session, now)
    if due is None:
        out["cycle"] = "not due"
    else:
        try:
            c = run_cycle(session, triggered_by="scheduler", now=now, cycle_date=due)
            out["cycle"] = {"id": c.id, "date": c.cycle_date.isoformat(), "status": c.status}
        except locking.CycleNotDue as exc:
            out["cycle"] = f"skipped: {exc}"
    out["backup"] = backup_if_due(session, now)
    return out


class Scheduler(threading.Thread):
    """Polls once a minute while the API server runs. Missed runs (sleep, shutdown) are caught
    up on the first poll after the computer is running again."""

    def __init__(self, poll_seconds: int = 60) -> None:
        super().__init__(name="investiq-scheduler", daemon=True)
        self.poll = poll_seconds
        self._halt = threading.Event()
        self.last_result: dict[str, Any] | None = None
        self.last_poll: datetime | None = None

    def run(self) -> None:
        while not self._halt.is_set():
            self.tick()
            self._halt.wait(self.poll)

    def tick(self) -> None:
        s = get_session()
        try:
            self.last_poll = datetime.now(UTC)
            self.last_result = run_due(s, self.last_poll)
        except Exception:  # noqa: BLE001 - the scheduler must survive any single failure
            log.exception("scheduler tick failed")
            s.rollback()
        finally:
            s.close()

    def stop(self) -> None:
        self._halt.set()
