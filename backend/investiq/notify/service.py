"""In-app notification centre plus optional desktop delivery. Deterministic events only: no AI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.models import Notification
from investiq.notify import desktop
from investiq.services.preferences import get_pref

KINDS = ("important_news", "watchlist", "grade_change", "new_opportunity", "portfolio_risk", "research_complete",
         "paper_milestone", "job_failed", "price_alert")


def notify(session: Session, kind: str, title: str, body: str, *, severity: str = "info", entity_type: str | None = None,
           entity_id: int | None = None, dedupe_key: str | None = None, desktop_sender=desktop.send) -> Notification | None:
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind {kind}")
    if dedupe_key:
        since = datetime.now(UTC) - timedelta(hours=24)
        if session.execute(select(Notification.id).where(Notification.dedupe_key == dedupe_key,
                                                         Notification.created_at >= since)).first():
            return None
    prefs = get_pref(session, "notifications")
    n = Notification(kind=kind, severity=severity, title=title[:255], body=body, entity_type=entity_type,
                     entity_id=entity_id, dedupe_key=dedupe_key, deliveries={"in_app": "stored"})
    if prefs.desktop_enabled and prefs.kinds.get(kind, True):
        res = desktop_sender(title, body)
        n.deliveries = {"in_app": "stored", "desktop": "shown" if res.delivered else res.detail}
    else:
        n.deliveries = {"in_app": "stored", "desktop": "disabled in preferences"}
    session.add(n)
    session.flush()
    return n


def mark_read(session: Session, ids: list[int]) -> int:
    count = 0
    for n in session.execute(select(Notification).where(Notification.id.in_(ids), Notification.read_at.is_(None))).scalars():
        n.read_at = datetime.now(UTC)
        count += 1
    return count
