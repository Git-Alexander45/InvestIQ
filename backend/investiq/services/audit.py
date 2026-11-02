from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from investiq.models import AuditLog


def audit(session: Session, action: str, *, actor: str = "system", entity_type: str | None = None,
          entity_id: Any = None, **detail: Any) -> None:
    session.add(AuditLog(actor=actor, action=action, entity_type=entity_type,
                         entity_id=None if entity_id is None else str(entity_id), detail=detail))
