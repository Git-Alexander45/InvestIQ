"""Manual brokerage-availability workflow for Wealthsimple and Questrade.

InvestIQ never logs in to a brokerage and never asks for credentials. The owner checks the
brokerage app or website and records what they saw (or imports a CSV of such checks)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.data import repository as repo
from investiq.models import BrokerageVerification, Instrument, Recommendation, ResearchCycle
from investiq.models.brokerage import BROKERAGES, STATUSES
from investiq.research.locking import DONE
from investiq.services.audit import audit
from investiq.services.preferences import get_pref

router = APIRouter(tags=["brokerage"])
MAX_CSV_BYTES = 1_000_000
HOW_TO = {
    "wealthsimple": "In the Wealthsimple app, search the ticker, confirm the exchange and currency shown, and whether "
                    "it can be bought in your TFSA.",
    "questrade": "In Questrade (Edge or web), look up the symbol with its exchange suffix, confirm it is tradable and "
                 "eligible in your TFSA account.",
}


@router.get("/brokerage/pending")
def pending(s: Session = Depends(db)) -> dict[str, Any]:
    """Investments the research would consider but that still need verification at either brokerage."""
    c = s.execute(select(ResearchCycle).where(ResearchCycle.status.in_(DONE)).order_by(ResearchCycle.id.desc()).limit(1)
                  ).scalar_one_or_none()
    if c is None:
        return {"items": [], "how_to": HOW_TO}
    days = get_pref(s, "brokerage").reverify_after_days
    items = []
    for rec in s.execute(select(Recommendation).where(Recommendation.cycle_id == c.id,
                                                      Recommendation.assessment.in_(("BUY", "WATCH", "HOLD")))).scalars():
        st = repo.brokerage_status(s, rec.instrument_id, datetime.now(UTC), days)
        if all(v["status"] == "VERIFIED" for v in st.values()):
            continue
        inst = s.get(Instrument, rec.instrument_id)
        items.append({"instrument_id": inst.id, "symbol": inst.symbol, "exchange": inst.exchange, "name": inst.name,
                      "assessment": rec.assessment, "quant_assessment": rec.quant_assessment, "status": st})
    items.sort(key=lambda x: x["assessment"] != "WATCH")
    return {"items": items, "how_to": HOW_TO}


@router.get("/brokerage/{instrument_id}")
def status(instrument_id: int, s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Instrument, instrument_id) is None:
        raise not_found("instrument")
    hist = s.execute(select(BrokerageVerification).where(BrokerageVerification.instrument_id == instrument_id)
                     .order_by(BrokerageVerification.id.desc())).scalars()
    return {"current": repo.brokerage_status(s, instrument_id, datetime.now(UTC),
                                             get_pref(s, "brokerage").reverify_after_days),
            "history": [row(h) for h in hist]}


class VerifyIn(BaseModel):
    instrument_id: int
    brokerage: Literal["wealthsimple", "questrade"]
    status: Literal["VERIFIED", "UNVERIFIED", "UNAVAILABLE"]
    ticker: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=16)
    security_type: str | None = Field(None, max_length=32)
    trading_currency: Literal["CAD", "USD"] | None = None
    tfsa_eligible: bool | None = None
    account_restrictions: str | None = Field(None, max_length=1000)
    evidence_note: str = Field(min_length=3, max_length=2000, description="what you saw, e.g. 'Listed in WS app, "
                                                                          "TSX, CAD, buyable in TFSA'")
    checked_on: date | None = None


def _record(s: Session, body: VerifyIn, source: str) -> BrokerageVerification:
    when = datetime.combine(body.checked_on, time(12), UTC) if body.checked_on else datetime.now(UTC)
    if when > datetime.now(UTC):
        raise HTTPException(422, "checked_on cannot be in the future")
    v = BrokerageVerification(instrument_id=body.instrument_id, brokerage=body.brokerage, status=body.status,
                              ticker=body.ticker.upper(), exchange=body.exchange.upper(), security_type=body.security_type,
                              trading_currency=body.trading_currency, tfsa_eligible=body.tfsa_eligible,
                              account_restrictions=body.account_restrictions, evidence_source=source,
                              evidence_note=body.evidence_note, verified_by="owner", verified_at=when)
    s.add(v)
    s.flush()
    audit(s, "brokerage.verified", actor="owner", entity_type="brokerage_verification", entity_id=v.id,
          instrument_id=body.instrument_id, brokerage=body.brokerage, status=body.status, source=source)
    return v


@router.post("/brokerage/verify")
def verify(body: VerifyIn, s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Instrument, body.instrument_id) is None:
        raise not_found("instrument")
    return row(_record(s, body, "manual_app_check"))


CSV_COLUMNS = ["symbol", "exchange", "brokerage", "status", "ticker", "trading_currency", "tfsa_eligible",
               "evidence_note", "checked_on"]


@router.get("/brokerage-csv-template")
def template() -> dict[str, Any]:
    return {"columns": CSV_COLUMNS, "example": "RY,TSX,wealthsimple,VERIFIED,RY,CAD,true,Seen in WS app 2026-10-29,2026-10-29",
            "allowed": {"brokerage": list(BROKERAGES), "status": list(STATUSES)}}


@router.post("/brokerage/import")
async def import_csv(file: UploadFile = File(...), s: Session = Depends(db)) -> dict[str, Any]:
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV larger than 1 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise HTTPException(422, f"missing columns: {missing}")
    results, imported = [], 0
    for n, r in enumerate(reader, start=2):
        try:
            inst = repo.instrument_by_symbol(s, r["symbol"].strip(), r["exchange"].strip().upper())
            if inst is None:
                raise ValueError("unknown symbol/exchange (add it to the universe first)")
            tfsa = {"true": True, "yes": True, "false": False, "no": False}.get((r["tfsa_eligible"] or "").strip().lower())
            body = VerifyIn(instrument_id=inst.id, brokerage=r["brokerage"].strip().lower(),
                            status=r["status"].strip().upper(), ticker=r["ticker"].strip() or inst.symbol,
                            exchange=r["exchange"].strip(), trading_currency=(r["trading_currency"] or "").strip().upper()
                            or None, tfsa_eligible=tfsa, evidence_note=r["evidence_note"].strip(),
                            checked_on=date.fromisoformat(r["checked_on"].strip()) if r["checked_on"].strip() else None)
            with s.begin_nested():
                _record(s, body, "csv_import")
            imported += 1
            results.append({"line": n, "ok": True})
        except Exception as exc:  # noqa: BLE001 - each row is reported individually
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            results.append({"line": n, "ok": False, "error": str(detail)[:300]})
    return {"imported": imported, "rows": results}
