"""AI spending (hard monthly CAD budget) and owner-entered external service costs."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.ai import budget
from investiq.api.deps import db, row
from investiq.models import AiRequest, ExternalCost
from investiq.services.audit import audit

router = APIRouter(tags=["costs"])


@router.get("/ai/costs")
def ai_costs(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), s: Session = Depends(db)) -> dict[str, Any]:
    st = budget.status(s, month)
    by_task = s.execute(select(AiRequest.task, func.count(AiRequest.id), func.coalesce(func.sum(AiRequest.cost_cad), 0.0))
                        .where(AiRequest.budget_month == st.month).group_by(AiRequest.task)).all()
    months = s.execute(select(AiRequest.budget_month, func.coalesce(func.sum(AiRequest.cost_cad), 0.0))
                       .where(AiRequest.status != "reserved").group_by(AiRequest.budget_month)
                       .order_by(AiRequest.budget_month)).all()
    return {"status": st.as_dict(), "daily": budget.daily_usage(s, st.month),
            "by_task": [{"task": t, "requests": n, "cost_cad": round(float(c), 6)} for t, n, c in by_task],
            "by_month": [{"month": m, "cost_cad": round(float(c), 6)} for m, c in months],
            "policy": "Hard monthly limit in CAD. When reached, AI analysis pauses; it is never raised automatically."}


@router.get("/ai/requests")
def ai_requests(limit: int = Query(200, le=5000), s: Session = Depends(db)) -> list[dict[str, Any]]:
    return [row(r) for r in s.execute(select(AiRequest).order_by(AiRequest.id.desc()).limit(limit)).scalars()]


class ExternalCostIn(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    category: Literal["market_data", "email", "ai", "hosting", "other"]
    amount: float = Field(ge=0, le=1_000_000)
    currency: Literal["CAD", "USD"]
    period: Literal["monthly", "annual", "one_time"]
    note: str | None = Field(None, max_length=2000)
    started_on: date | None = None


@router.get("/external-costs")
def external_costs(s: Session = Depends(db)) -> list[dict[str, Any]]:
    return [row(c) for c in s.execute(select(ExternalCost).order_by(ExternalCost.id.desc())).scalars()]


@router.post("/external-costs")
def add_external_cost(body: ExternalCostIn, s: Session = Depends(db)) -> dict[str, Any]:
    c = ExternalCost(**body.model_dump())
    s.add(c)
    s.flush()
    audit(s, "external_cost.recorded", actor="owner", entity_type="external_cost", entity_id=c.id)
    return row(c)
