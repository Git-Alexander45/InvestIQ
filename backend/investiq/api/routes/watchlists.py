"""Watchlists, saved investments, personal notes and price alerts. Nothing is deleted: items are
archived (hidden) and notes are versioned."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.models import Alert, Instrument, PersonalNote, SavedInvestment, Score, Watchlist
from investiq.services.audit import audit

router = APIRouter(tags=["watchlists"])


@router.get("/watchlists")
def watchlists(include_archived: bool = False, s: Session = Depends(db)) -> list[dict[str, Any]]:
    out = []
    for w in s.execute(select(Watchlist).order_by(Watchlist.id)).scalars():
        if w.archived and not include_archived:
            continue
        items = []
        for si in s.execute(select(SavedInvestment).where(SavedInvestment.watchlist_id == w.id)).scalars():
            if si.archived and not include_archived:
                continue
            inst = s.get(Instrument, si.instrument_id)
            sc = s.execute(select(Score).where(Score.instrument_id == inst.id).order_by(Score.id.desc()).limit(1)
                           ).scalar_one_or_none()
            items.append({**row(si), "symbol": inst.symbol, "exchange": inst.exchange, "name": inst.name,
                          "grade": sc.grade if sc else None, "overall": sc.overall if sc else None})
        out.append({**row(w), "items": items})
    return out


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)


@router.post("/watchlists")
def create_watchlist(body: WatchlistIn, s: Session = Depends(db)) -> dict[str, Any]:
    w = Watchlist(name=body.name.strip(), description=body.description)
    s.add(w)
    try:
        s.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "a watchlist with this name exists") from exc
    audit(s, "watchlist.created", actor="owner", entity_type="watchlist", entity_id=w.id)
    return row(w)


class WatchlistPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    archived: bool | None = None


@router.patch("/watchlists/{watchlist_id}")
def update_watchlist(watchlist_id: int, body: WatchlistPatch, s: Session = Depends(db)) -> dict[str, Any]:
    w = s.get(Watchlist, watchlist_id)
    if w is None:
        raise not_found("watchlist")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(w, k, v)
    audit(s, "watchlist.updated", actor="owner", entity_type="watchlist", entity_id=w.id, **body.model_dump(exclude_none=True))
    return row(w)


class SaveIn(BaseModel):
    instrument_id: int
    saved_from: str | None = Field(None, max_length=64)


@router.post("/watchlists/{watchlist_id}/items")
def save_item(watchlist_id: int, body: SaveIn, s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Watchlist, watchlist_id) is None:
        raise not_found("watchlist")
    if s.get(Instrument, body.instrument_id) is None:
        raise not_found("instrument")
    existing = s.execute(select(SavedInvestment).where(SavedInvestment.watchlist_id == watchlist_id,
                                                       SavedInvestment.instrument_id == body.instrument_id)
                         ).scalar_one_or_none()
    if existing is not None:
        existing.archived = False  # re-saving restores an archived item
        return row(existing)
    si = SavedInvestment(watchlist_id=watchlist_id, instrument_id=body.instrument_id, saved_from=body.saved_from)
    s.add(si)
    s.flush()
    audit(s, "watchlist.saved", actor="owner", entity_type="saved_investment", entity_id=si.id,
          instrument_id=body.instrument_id)
    return row(si)


class ArchiveIn(BaseModel):
    archived: bool


@router.patch("/saved/{saved_id}")
def archive_item(saved_id: int, body: ArchiveIn, s: Session = Depends(db)) -> dict[str, Any]:
    si = s.get(SavedInvestment, saved_id)
    if si is None:
        raise not_found("saved investment")
    si.archived = body.archived
    audit(s, "watchlist.archived" if body.archived else "watchlist.restored", actor="owner",
          entity_type="saved_investment", entity_id=si.id)
    return row(si)


class NoteIn(BaseModel):
    instrument_id: int
    kind: Literal["note", "why_i_like_it", "thesis"] = "note"
    body: str = Field(min_length=1, max_length=20_000)
    supersedes_id: int | None = None


@router.post("/notes")
def add_note(body: NoteIn, s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Instrument, body.instrument_id) is None:
        raise not_found("instrument")
    if body.supersedes_id is not None:
        prev = s.get(PersonalNote, body.supersedes_id)
        if prev is None or prev.instrument_id != body.instrument_id:
            raise HTTPException(422, "supersedes_id must be an earlier note on the same instrument")
    n = PersonalNote(instrument_id=body.instrument_id, kind=body.kind, body=body.body, supersedes_id=body.supersedes_id)
    s.add(n)
    s.flush()
    return row(n)


@router.get("/notes")
def notes(instrument_id: int, s: Session = Depends(db)) -> list[dict[str, Any]]:
    return [row(n) for n in s.execute(select(PersonalNote).where(PersonalNote.instrument_id == instrument_id)
                                      .order_by(PersonalNote.id.desc())).scalars()]


class AlertIn(BaseModel):
    instrument_id: int
    kind: Literal["price_above", "price_below", "pct_move_day"]
    threshold: float = Field(gt=0, le=1_000_000)


@router.get("/alerts")
def alerts(s: Session = Depends(db)) -> list[dict[str, Any]]:
    out = []
    for a in s.execute(select(Alert).order_by(Alert.id.desc())).scalars():
        inst = s.get(Instrument, a.instrument_id)
        out.append({**row(a), "symbol": inst.symbol})
    return out


@router.post("/alerts")
def create_alert(body: AlertIn, s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Instrument, body.instrument_id) is None:
        raise not_found("instrument")
    a = Alert(instrument_id=body.instrument_id, kind=body.kind, threshold=body.threshold)
    s.add(a)
    s.flush()
    audit(s, "alert.created", actor="owner", entity_type="alert", entity_id=a.id)
    return row(a)


class AlertPatch(BaseModel):
    active: bool


@router.patch("/alerts/{alert_id}")
def toggle_alert(alert_id: int, body: AlertPatch, s: Session = Depends(db)) -> dict[str, Any]:
    a = s.get(Alert, alert_id)
    if a is None:
        raise not_found("alert")
    a.active = body.active
    return row(a)
