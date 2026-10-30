"""Hard monthly AI spending limit (CAD).

Before every AI request the router *reserves* the worst-case cost (conservative input estimate +
the full ``max_tokens`` output, which also bounds thinking tokens) converted to CAD. The request is
refused if already-spent + outstanding reservations + this reservation would exceed the limit.
After the call the reservation is replaced by the actual cost. The limit is never raised by code.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from investiq.data.repository import fx_table
from investiq.finance.fx import MissingFxRate
from investiq.models import AiRequest, BudgetLedger
from investiq.services.preferences import get_pref

_LOCAL_LOCK = threading.Lock()
OWNER_TZ = ZoneInfo("America/Toronto")


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class UsdCad:
    rate: float
    source: str


def budget_month(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.astimezone(OWNER_TZ).strftime("%Y-%m")


def usd_cad(session: Session, on: date | None = None) -> UsdCad:
    on = on or datetime.now(UTC).date()
    try:
        q = fx_table(session, on, lookback_days=10).get("USD", "CAD")
        return UsdCad(q.rate, f"{q.source} ({q.as_of.isoformat()})")
    except MissingFxRate:
        fallback = get_pref(session, "ai_budget").usd_cad_fallback_rate
        return UsdCad(fallback, "configured conservative fallback (no recent Bank of Canada rate stored)")


@dataclass
class BudgetStatus:
    month: str
    limit_cad: float
    spent_cad: float
    reserved_cad: float
    remaining_cad: float
    paused: bool
    premium_paused: bool
    requests: int
    blocked: int

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def status(session: Session, month: str | None = None) -> BudgetStatus:
    month = month or budget_month()
    prefs = get_pref(session, "ai_budget")
    spent = session.execute(
        select(func.coalesce(func.sum(AiRequest.cost_cad), 0.0)).where(AiRequest.budget_month == month,
                                                                        AiRequest.status != "reserved")
    ).scalar_one()
    reserved = session.execute(
        select(func.coalesce(func.sum(AiRequest.reserved_cad), 0.0)).where(AiRequest.budget_month == month,
                                                                           AiRequest.status == "reserved")
    ).scalar_one()
    count = session.execute(select(func.count(AiRequest.id)).where(AiRequest.budget_month == month)).scalar_one()
    blocked = session.execute(select(func.count(AiRequest.id)).where(
        AiRequest.budget_month == month, AiRequest.status == "blocked_budget")).scalar_one()
    remaining = prefs.monthly_limit_cad - spent - reserved
    premium_floor = prefs.monthly_limit_cad * prefs.premium_reserve_pct / 100
    return BudgetStatus(month=month, limit_cad=prefs.monthly_limit_cad, spent_cad=round(float(spent), 6),
                        reserved_cad=round(float(reserved), 6), remaining_cad=round(float(remaining), 6),
                        paused=remaining <= 0.0005, premium_paused=remaining <= premium_floor + 0.0005,
                        requests=count, blocked=blocked)


def _lock_month(session: Session, month: str) -> None:
    if session.get(BudgetLedger, month) is None:
        session.add(BudgetLedger(month=month))
        session.flush()
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(select(BudgetLedger).where(BudgetLedger.month == month).with_for_update())


def reserve(session: Session, *, amount_cad: float, tier: str, request: AiRequest) -> AiRequest:
    """Atomically check the budget and record a reservation (or a blocked request)."""
    with _LOCAL_LOCK:
        _lock_month(session, request.budget_month)
        st = status(session, request.budget_month)
        floor = 0.0
        if tier == "premium":
            prefs = get_pref(session, "ai_budget")
            floor = prefs.monthly_limit_cad * prefs.premium_reserve_pct / 100
        if st.remaining_cad - amount_cad < floor - 1e-9:
            request.status = "blocked_budget"
            request.reserved_cad = 0.0
            request.error = (f"AI budget: reservation {amount_cad:.4f} CAD exceeds remaining {st.remaining_cad:.4f} CAD"
                             f" of {st.limit_cad:.2f} CAD for {st.month}")
            session.add(request)
            session.commit()
            raise BudgetExceeded(request.error)
        request.status = "reserved"
        request.reserved_cad = amount_cad
        session.add(request)
        session.commit()
        return request


def settle(session: Session, request: AiRequest, *, status_: str, input_tokens: int, output_tokens: int,
           cost_usd: float, usd_cad_rate: float) -> None:
    request.status = status_
    request.input_tokens = input_tokens
    request.output_tokens = output_tokens
    request.cost_usd = round(cost_usd, 8)
    request.cost_cad = round(cost_usd * usd_cad_rate, 8)
    session.commit()


def daily_usage(session: Session, month: str | None = None) -> list[dict]:
    month = month or budget_month()
    rows = session.execute(
        select(AiRequest.created_at, AiRequest.cost_cad, AiRequest.task, AiRequest.model, AiRequest.status)
        .where(AiRequest.budget_month == month)
    ).all()
    by_day: dict[str, dict] = {}
    for created, cost, task, model, st in rows:
        day = created.astimezone(OWNER_TZ).date().isoformat()
        d = by_day.setdefault(day, {"date": day, "cost_cad": 0.0, "requests": 0, "by_task": {}, "by_model": {}})
        if st != "reserved":
            d["cost_cad"] += cost or 0.0
            d["by_task"][task] = d["by_task"].get(task, 0.0) + (cost or 0.0)
            d["by_model"][model] = d["by_model"].get(model, 0.0) + (cost or 0.0)
        d["requests"] += 1
    return [by_day[k] for k in sorted(by_day)]
