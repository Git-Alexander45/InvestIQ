"""System health: what is configured, what ran, what is due. Never returns secret values."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from investiq import __version__
from investiq.ai import budget
from investiq.config import get_settings
from investiq.models import BackupRecord, EmailDelivery, ResearchCycle
from investiq.research import locking
from investiq.services.backup import disk_usage
from investiq.services.preferences import get_pref


def _configured() -> dict[str, bool]:
    s = get_settings()
    return {
        "anthropic": bool(s.secret("anthropic_api_key")),
        "fmp": bool(s.secret("fmp_api_key")),
        "twelvedata": bool(s.secret("twelvedata_api_key")),
        "sec_edgar_user_agent": bool(s.sec_user_agent),
        "smtp": bool(s.smtp_host),
        "resend": bool(s.secret("resend_api_key")),
        "api_token": bool(s.secret("api_token")),
    }


def next_run(session: Session, now: datetime) -> datetime:
    sched = get_pref(session, "research_schedule")
    _, last = locking.latest_occurrence(now, sched.time_local, sched.timezone)
    _, upcoming = locking.latest_occurrence(now + timedelta(days=1), sched.time_local, sched.timezone)
    return upcoming if upcoming > now else last


def health(session: Session, scheduler: Any = None) -> dict[str, Any]:
    from investiq.db.migrate import current_revision, head_revision

    now = datetime.now(UTC)
    s = get_settings()
    out: dict[str, Any] = {"version": __version__, "time_utc": now.isoformat(), "env": s.env}
    try:
        session.execute(text("SELECT 1"))
        out["database"] = {"ok": True, "dialect": session.bind.dialect.name}
        rev, head = current_revision(session.bind), head_revision()
        out["database"].update(revision=rev, head=head, migrations_pending=rev != head)
    except Exception as exc:  # noqa: BLE001
        out["database"] = {"ok": False, "error": type(exc).__name__}
        return out
    last = session.execute(select(ResearchCycle).order_by(ResearchCycle.id.desc()).limit(1)).scalar_one_or_none()
    out["last_cycle"] = None if last is None else {
        "id": last.id, "date": last.cycle_date.isoformat(), "status": last.status, "attempt": last.attempt,
        "started_at": last.started_at.isoformat(), "finished_at": last.finished_at.isoformat() if last.finished_at else None,
        "degraded": last.degraded_reasons, "error": last.error}
    sched = get_pref(session, "research_schedule")
    due = locking.due_cycle_date(session, now)
    out["schedule"] = {"enabled": sched.enabled, "time_local": sched.time_local, "timezone": sched.timezone,
                       "due_now": due.isoformat() if due else None, "next_run_utc": next_run(session, now).isoformat(),
                       "in_process_scheduler": None if scheduler is None else {
                           "alive": scheduler.is_alive(),
                           "last_poll": scheduler.last_poll.isoformat() if scheduler.last_poll else None}}
    out["configured"] = _configured()
    md = get_pref(session, "market_data")
    out["market_data"] = md.model_dump()
    out["synthetic_mode"] = "synthetic" in (md.price_provider, md.fundamentals_provider, md.etf_holdings_provider,
                                            md.fx_provider)
    out["ai_budget"] = budget.status(session).as_dict()
    b = session.execute(select(BackupRecord).order_by(BackupRecord.id.desc()).limit(1)).scalar_one_or_none()
    out["last_backup"] = None if b is None else {"id": b.id, "status": b.status, "created_at": b.created_at.isoformat(),
                                                  "restore_tested_at": b.restore_tested_at.isoformat()
                                                  if b.restore_tested_at else None}
    out["backups"] = disk_usage()
    e = session.execute(select(EmailDelivery).order_by(EmailDelivery.id.desc()).limit(1)).scalar_one_or_none()
    out["last_email"] = None if e is None else {"status": e.status, "provider": e.provider, "error": e.error,
                                                "at": (e.sent_at or now).isoformat()}
    warnings = []
    if out["database"]["migrations_pending"]:
        warnings.append("Database migrations are pending: run 'investiq migrate'.")
    if out["synthetic_mode"]:
        warnings.append("SYNTHETIC market data is active: results are not real.")
    if not any(out["configured"][k] for k in ("fmp", "twelvedata")) and not out["synthetic_mode"]:
        warnings.append("No market-data API key configured: research cannot collect prices.")
    if not out["configured"]["anthropic"]:
        warnings.append("No Anthropic API key: AI analysis is skipped; quantitative research still runs.")
    if out["last_backup"] is None or out["last_backup"]["status"] == "failed":
        warnings.append("No verified backup yet.")
    if last is not None and last.status == "failed":
        warnings.append(f"The last research cycle ({last.cycle_date}) failed.")
    out["warnings"] = warnings
    return out
