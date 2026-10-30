"""Paper portfolios (simulation only) and benchmarks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.models import (
    Instrument,
    PaperCashEntry,
    PaperDividend,
    PaperFill,
    PaperOrder,
    Portfolio,
    PortfolioMilestone,
    PortfolioSnapshot,
)
from investiq.paper import performance

router = APIRouter(tags=["paper"])
NOTICE = "Simulation only: virtual money, no real orders are ever placed."


@router.get("/paper")
def overview(s: Session = Depends(db)) -> dict[str, Any]:
    return {**performance.comparison(s), "notice": NOTICE}


@router.get("/paper/{code}")
def portfolio(code: str, limit: int = Query(200, le=5000), s: Session = Depends(db)) -> dict[str, Any]:
    p = s.execute(select(Portfolio).where(Portfolio.code == code.upper(), Portfolio.kind.in_(("paper", "benchmark")))
                  ).scalar_one_or_none()
    if p is None:
        raise not_found("portfolio")
    snap = s.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == p.id)
                     .order_by(PortfolioSnapshot.as_of.desc()).limit(1)).scalar_one_or_none()
    symbols = {i.id: i.symbol for i in s.execute(select(Instrument)).scalars()}

    def named(r: Any) -> dict[str, Any]:
        d = row(r)
        if "instrument_id" in d:
            d["symbol"] = symbols.get(d["instrument_id"])
        return d

    q = lambda m, order: s.execute(select(m).where(m.portfolio_id == p.id).order_by(order.desc()).limit(limit)).scalars()  # noqa: E731
    return {"portfolio": row(p), "metrics": performance.metrics(s, p), "latest_snapshot": row(snap) if snap else None,
            "orders": [named(x) for x in q(PaperOrder, PaperOrder.id)],
            "fills": [named(x) for x in q(PaperFill, PaperFill.id)],
            "cash_ledger": [row(x) for x in q(PaperCashEntry, PaperCashEntry.id)],
            "dividends": [named(x) for x in q(PaperDividend, PaperDividend.id)],
            "milestones": [row(x) for x in q(PortfolioMilestone, PortfolioMilestone.id)],
            "notice": NOTICE}
