"""In-app notification centre."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, row
from investiq.models import Notification
from investiq.notify.service import mark_read

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = Query(200, le=2000), s: Session = Depends(db)
                  ) -> list[dict[str, Any]]:
    q = select(Notification).order_by(Notification.id.desc()).limit(limit)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return [row(n) for n in s.execute(q).scalars()]


class ReadIn(BaseModel):
    ids: list[int] = Field(max_length=1000)


@router.post("/notifications/read")
def read(body: ReadIn, s: Session = Depends(db)) -> dict[str, int]:
    return {"marked": mark_read(s, body.ids)}
