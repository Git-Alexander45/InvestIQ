"""Persist provider results. Existing history is never overwritten."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.data.providers.base import BarsResult, DividendDTO, FundamentalsDTO, HoldingsDTO, SplitDTO
from investiq.data.validation import Issue, validate_bars
from investiq.finance.fx import FxQuote
from investiq.models import (
    CorporateAction,
    DataQualityIssue,
    Dividend,
    EtfHolding,
    EtfHoldingsSnapshot,
    FundamentalsSnapshot,
    FxRate,
    Instrument,
    PriceBar,
)


def record_issues(session: Session, issues: list[Issue], instrument_id: int | None, cycle_id: int | None) -> None:
    for i in issues:
        session.add(DataQualityIssue(instrument_id=instrument_id, cycle_id=cycle_id, issue_type=i.issue_type,
                                     severity=i.severity, message=i.message, detail=i.detail))


def store_bars(session: Session, inst: Instrument, result: BarsResult, cycle_id: int | None = None) -> int:
    splits = {a.effective_date for a in session.execute(
        select(CorporateAction).where(CorporateAction.instrument_id == inst.id, CorporateAction.kind == "split")
    ).scalars()}
    clean, issues = validate_bars(result.bars, split_dates=splits)
    record_issues(session, issues, inst.id, cycle_id)
    if not clean:
        return 0
    existing = {r[0] for r in session.execute(
        select(PriceBar.ts).where(PriceBar.instrument_id == inst.id, PriceBar.interval == result.interval,
                                  PriceBar.source == result.source, PriceBar.ts >= clean[0].ts,
                                  PriceBar.ts <= clean[-1].ts)
    )}
    quality = "synthetic" if result.data_status == "synthetic" else "ok"
    flagged = {i.detail.get("ts") for i in issues if i.issue_type == "outlier"}
    added = 0
    for b in clean:
        if b.ts in existing:
            continue
        session.add(PriceBar(instrument_id=inst.id, interval=result.interval, ts=b.ts, source=result.source,
                             open=b.open, high=b.high, low=b.low, close=b.close, adj_close=b.adj_close,
                             volume=b.volume, currency=result.currency, data_status=result.data_status,
                             quality="suspect" if b.ts.isoformat() in flagged else quality))
        added += 1
    return added


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def store_fundamentals(session: Session, inst: Instrument, dto: FundamentalsDTO) -> FundamentalsSnapshot | None:
    latest = session.execute(
        select(FundamentalsSnapshot).where(FundamentalsSnapshot.instrument_id == inst.id,
                                           FundamentalsSnapshot.source == dto.source)
        .order_by(FundamentalsSnapshot.id.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is not None and _hash(latest.metrics) == _hash(dto.metrics):
        return None  # unchanged; history already holds this version
    snap = FundamentalsSnapshot(instrument_id=inst.id, as_of=dto.as_of, period_end=dto.period_end,
                                currency=dto.currency, source=dto.source, metrics=dto.metrics,
                                quality="synthetic" if dto.source == "synthetic" else "ok")
    session.add(snap)
    # Fill missing descriptive metadata from the provider profile (never overwrite owner data).
    prof = dto.profile or {}
    if not inst.sector and prof.get("sector"):
        inst.sector = prof["sector"]
    if not inst.industry and prof.get("industry"):
        inst.industry = prof["industry"]
    if not inst.country and prof.get("country") and len(str(prof["country"])) == 2:
        inst.country = str(prof["country"]).upper()
    return snap


def store_holdings(session: Session, inst: Instrument, dto: HoldingsDTO) -> EtfHoldingsSnapshot | None:
    latest = session.execute(
        select(EtfHoldingsSnapshot).where(EtfHoldingsSnapshot.etf_id == inst.id,
                                          EtfHoldingsSnapshot.source == dto.source)
        .order_by(EtfHoldingsSnapshot.id.desc()).limit(1)
    ).scalar_one_or_none()
    payload = sorted((h.symbol or "", h.name, round(h.weight_pct, 4)) for h in dto.holdings)
    if latest is not None:
        old = sorted((h.symbol or "", h.name, round(h.weight_pct, 4)) for h in latest.holdings)
        if old == payload:
            return None
    coverage = sum(h.weight_pct for h in dto.holdings)
    snap = EtfHoldingsSnapshot(etf_id=inst.id, as_of=dto.as_of, source=dto.source, coverage_pct=round(coverage, 3))
    session.add(snap)
    session.flush()
    for h in dto.holdings:
        session.add(EtfHolding(snapshot_id=snap.id, symbol=h.symbol, name=h.name[:255], weight_pct=h.weight_pct,
                               asset_class=h.asset_class, sector=h.sector, country=h.country, currency=h.currency))
    return snap


def store_dividends(session: Session, inst: Instrument, items: list[DividendDTO], source: str) -> int:
    existing = {d for (d,) in session.execute(
        select(Dividend.ex_date).where(Dividend.instrument_id == inst.id, Dividend.source == source))}
    n = 0
    for it in items:
        if it.ex_date in existing:
            continue
        session.add(Dividend(instrument_id=inst.id, ex_date=it.ex_date, pay_date=it.pay_date, amount=it.amount,
                             currency=it.currency, source=source))
        n += 1
    return n


def store_splits(session: Session, inst: Instrument, items: list[SplitDTO], source: str) -> int:
    existing = {d for (d,) in session.execute(
        select(CorporateAction.effective_date).where(CorporateAction.instrument_id == inst.id,
                                                     CorporateAction.kind == "split", CorporateAction.source == source))}
    n = 0
    for it in items:
        if it.effective_date in existing:
            continue
        session.add(CorporateAction(instrument_id=inst.id, effective_date=it.effective_date, kind="split",
                                    ratio=it.ratio, source=source))
        n += 1
    return n


def store_fx(session: Session, quotes: list[FxQuote]) -> int:
    if not quotes:
        return 0
    keys = {(r.base, r.quote, r.as_of, r.source) for r in session.execute(
        select(FxRate).where(FxRate.as_of >= min(q.as_of for q in quotes))).scalars()}
    n = 0
    for q in quotes:
        k = (q.base, q.quote, q.as_of, q.source)
        if k in keys:
            continue
        keys.add(k)
        session.add(FxRate(base=q.base, quote=q.quote, rate=q.rate, as_of=q.as_of, rate_type=q.rate_type,
                           source=q.source))
        n += 1
    return n


def today_utc() -> date:
    return datetime.now().astimezone().date()
