"""Health, dashboard summary, backups, export and audit log."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.ai import budget
from investiq.api.deps import db, not_found, row
from investiq.config import get_settings
from investiq.db.session import get_engine
from investiq.models import AuditLog, BackupRecord, Notification, Portfolio, ResearchCycle
from investiq.paper import performance
from investiq.services import backup
from investiq.services.audit import audit
from investiq.services.health import health

router = APIRouter(tags=["system"])


@router.get("/status")
def status(request: Request, s: Session = Depends(db)) -> dict[str, Any]:
    return health(s, getattr(request.app.state, "scheduler", None))


@router.get("/dashboard")
def dashboard(s: Session = Depends(db)) -> dict[str, Any]:
    from investiq.api.routes.research import leaderboards

    last = s.execute(select(ResearchCycle).order_by(ResearchCycle.id.desc()).limit(1)).scalar_one_or_none()
    boards = leaderboards(None, s)
    unread = s.execute(select(func.count(Notification.id)).where(Notification.read_at.is_(None))).scalar_one()
    paper = []
    for p in s.execute(select(Portfolio).where(Portfolio.kind.in_(("paper", "benchmark")))
                       .order_by(Portfolio.kind.desc(), Portfolio.code)).scalars():
        m = performance.metrics(s, p)
        paper.append({k: m.get(k) for k in ("portfolio", "name", "kind", "value_cad", "total_return_pct",
                                            "max_drawdown_pct", "observations")})
    return {"last_cycle": row(last) if last else None,
            "top": {k: v[:5] for k, v in boards["boards"].items()},
            "unread_notifications": unread, "ai_budget": budget.status(s).as_dict(), "paper": paper}


@router.get("/backups")
def backups(s: Session = Depends(db)) -> dict[str, Any]:
    rows = s.execute(select(BackupRecord).order_by(BackupRecord.id.desc()).limit(100)).scalars()
    return {"backups": [row(b) for b in rows], "disk": backup.disk_usage()}


@router.post("/backups")
def create_backup(s: Session = Depends(db)) -> dict[str, Any]:
    try:
        rec = backup.create_backup(s, get_engine(), reason="manual (dashboard)")
    except backup.BackupError as exc:
        raise HTTPException(500, str(exc)) from exc
    backup.verify_backup(s, rec)
    return row(rec)


@router.post("/backups/{backup_id}/verify")
def verify(backup_id: int, s: Session = Depends(db)) -> dict[str, Any]:
    rec = s.get(BackupRecord, backup_id)
    if rec is None:
        raise not_found("backup")
    return row(backup.verify_backup(s, rec))


@router.post("/backups/{backup_id}/restore-test")
def restore_test(backup_id: int, s: Session = Depends(db)) -> dict[str, Any]:
    rec = s.get(BackupRecord, backup_id)
    if rec is None:
        raise not_found("backup")
    try:
        return backup.restore_test(s, get_engine(), rec)
    except backup.BackupError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/export")
def export(s: Session = Depends(db)) -> dict[str, Any]:
    path = backup.export_data(get_engine(), Path(get_settings().data_dir) / "exports")
    audit(s, "data.exported", actor="owner", path=str(path))
    return {"file": path.name}


@router.get("/export/{name}")
def download_export(name: str) -> FileResponse:
    folder = (Path(get_settings().data_dir) / "exports").resolve()
    target = (folder / name).resolve()
    if target.parent != folder or not target.name.startswith("investiq-export-") or not target.exists():
        raise not_found("export")  # also blocks path traversal
    return FileResponse(target, filename=target.name, media_type="application/zip")


@router.get("/audit")
def audit_log(days: int = Query(30, le=3650), limit: int = Query(500, le=5000), s: Session = Depends(db)
              ) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = s.execute(select(AuditLog).where(AuditLog.ts >= since).order_by(AuditLog.id.desc()).limit(limit)).scalars()
    return [row(a) for a in rows]
