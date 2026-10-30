"""The owner's real holdings, entered manually (no brokerage connection, no credentials).
Each edit appends an entry; quantity 0 closes a position. History is never rewritten."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.data import repository as repo
from investiq.finance.fx import MissingFxRate
from investiq.models import Instrument, OwnerHoldingEntry
from investiq.reports.pricing import price_block
from investiq.services import portfolio_view
from investiq.services.audit import audit

router = APIRouter(tags=["holdings"])
ACCOUNTS = Literal["TFSA", "RRSP", "FHSA", "NON_REGISTERED"]


@router.get("/holdings")
def holdings(s: Session = Depends(db)) -> dict[str, Any]:
    now = datetime.now(UTC)
    fx = repo.fx_table(s, now.date())
    items, total = [], 0.0
    for h in portfolio_view.owner_holdings(s):
        inst = s.get(Instrument, h.instrument_id)
        bar = repo.last_bar(s, inst.id, now)
        pb = price_block(bar.close, bar.currency, bar.ts.date().isoformat(), bar.source, bar.data_status, fx) if bar else None
        value = pb["cad"] * h.quantity if pb and pb.get("cad") is not None else None
        try:
            cost_cad = fx.convert(h.average_cost, h.cost_currency, "CAD")[0] * h.quantity
        except MissingFxRate:
            cost_cad = None  # shown as unavailable rather than guessed
        total += value or 0.0
        items.append({**row(h), "symbol": inst.symbol, "exchange": inst.exchange, "name": inst.name, "price": pb,
                      "value_cad": None if value is None else round(value, 2),
                      "cost_cad": None if cost_cad is None else round(cost_cad, 2),
                      "gain_cad": None if value is None or cost_cad is None else round(value - cost_cad, 2)})
    return {"holdings": items, "total_value_cad": round(total, 2),
            "note": "Entered by you. InvestIQ never connects to or trades in your brokerage accounts."}


class HoldingIn(BaseModel):
    instrument_id: int
    account_type: ACCOUNTS = "TFSA"
    quantity: float = Field(ge=0, le=1e9)
    average_cost: float = Field(ge=0, le=1e7)
    cost_currency: Literal["CAD", "USD"]
    note: str | None = Field(None, max_length=1000)


@router.post("/holdings")
def enter_holding(body: HoldingIn, s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Instrument, body.instrument_id) is None:
        raise not_found("instrument")
    if body.quantity > 0 and body.average_cost <= 0:
        raise HTTPException(422, "average cost is required for an open position")
    e = OwnerHoldingEntry(portfolio_id=portfolio_view.owner_portfolio(s).id, **body.model_dump())
    s.add(e)
    s.flush()
    audit(s, "holding.entered", actor="owner", entity_type="owner_holding_entry", entity_id=e.id,
          instrument_id=body.instrument_id, quantity=body.quantity, account=body.account_type)
    return row(e)


@router.get("/holdings/history")
def holding_history(s: Session = Depends(db)) -> list[dict[str, Any]]:
    out = []
    for e in s.execute(select(OwnerHoldingEntry).order_by(OwnerHoldingEntry.id.desc())).scalars():
        inst = s.get(Instrument, e.instrument_id)
        out.append({**row(e), "symbol": inst.symbol, "exchange": inst.exchange})
    return out
