"""News feed with assessments (impact, confirmation, affected securities)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, row
from investiq.models import NewsSource
from investiq.news.service import latest_assessments

router = APIRouter(tags=["news"])


@router.get("/news")
def news(days: int = Query(3, ge=1, le=90), topic: str | None = Query(None, max_length=32),
         symbol: str | None = Query(None, max_length=16), official_only: bool = False,
         min_importance: float = Query(0.0, ge=0, le=1), s: Session = Depends(db)) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    out = []
    for item, a in latest_assessments(s, since):
        if topic and a.topic != topic:
            continue
        if symbol and symbol.upper() not in (a.affected_symbols or []):
            continue
        if official_only and not item.official:
            continue
        if a.importance < min_importance:
            continue
        out.append({"item": row(item), "assessment": row(a)})
    out.sort(key=lambda x: (x["assessment"]["importance"] or 0, x["item"]["published_at"] or ""), reverse=True)
    return out[:500]


@router.get("/news/sources")
def sources(s: Session = Depends(db)) -> list[dict[str, Any]]:
    return [row(x) for x in s.execute(select(NewsSource).order_by(NewsSource.key)).scalars()]
