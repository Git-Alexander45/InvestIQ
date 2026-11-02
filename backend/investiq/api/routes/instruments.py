"""Instrument search, research detail, and chart data with indicators."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from investiq.api.deps import db, not_found, row
from investiq.config import get_settings
from investiq.data import ingest, registry
from investiq.data import repository as repo
from investiq.data.providers.base import InstrumentRef, ProviderError
from investiq.finance import indicators as ind
from investiq.models import (
    Analysis,
    GradeChange,
    Instrument,
    NewsAssessment,
    NewsItem,
    PersonalNote,
    Prediction,
    PriceBar,
    Recommendation,
    SavedInvestment,
    Score,
)
from investiq.reports.pricing import price_block
from investiq.research.facts import etf_stats
from investiq.services.preferences import get_pref

log = logging.getLogger(__name__)
router = APIRouter(tags=["instruments"])
INTRADAY = ("1min", "5min", "15min", "1h")
TIMEFRAMES = {"1D": 1, "5D": 5, "1M": 31, "3M": 92, "6M": 183, "YTD": None, "1Y": 366, "3Y": 1096, "5Y": 1827,
              "MAX": 365 * 40}


@router.get("/instruments")
def search(q: str | None = Query(None, max_length=64), asset_class: str | None = None,
           security_type: str | None = None, limit: int = Query(50, ge=1, le=500),
           s: Session = Depends(db)) -> list[dict[str, Any]]:
    stmt = select(Instrument).where(Instrument.active.is_(True))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Instrument.symbol.ilike(like), Instrument.name.ilike(like)))
    if asset_class:
        stmt = stmt.where(Instrument.asset_class == asset_class)
    if security_type:
        stmt = stmt.where(Instrument.security_type == security_type)
    rows = s.execute(stmt.order_by(Instrument.symbol).limit(limit)).scalars().all()
    latest = _latest_scores(s, [r.id for r in rows])
    return [{**row(r, {"provider_symbols"}), "score": latest.get(r.id)} for r in rows]


def _latest_scores(s: Session, ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    sub = (select(Score.instrument_id, func.max(Score.id).label("mid")).where(Score.instrument_id.in_(ids))
           .group_by(Score.instrument_id).subquery())
    out = {}
    for sc in s.execute(select(Score).join(sub, Score.id == sub.c.mid)).scalars():
        out[sc.instrument_id] = {"overall": sc.overall, "grade": sc.grade, "confidence": sc.confidence,
                                 "coverage": sc.coverage, "as_of": sc.as_of.isoformat()}
    return out


@router.get("/instruments/{instrument_id}")
def detail(instrument_id: int, s: Session = Depends(db)) -> dict[str, Any]:
    inst = s.get(Instrument, instrument_id)
    if inst is None:
        raise not_found("instrument")
    now = datetime.now(UTC)
    score = s.execute(select(Score).where(Score.instrument_id == inst.id).order_by(Score.id.desc()).limit(1)
                      ).scalar_one_or_none()
    rec = s.execute(select(Recommendation).where(Recommendation.instrument_id == inst.id)
                    .order_by(Recommendation.id.desc()).limit(1)).scalar_one_or_none()
    analysis = s.execute(select(Analysis).where(Analysis.instrument_id == inst.id)
                         .order_by(Analysis.id.desc()).limit(3)).scalars().all()
    bar = repo.last_bar(s, inst.id, now)
    fx = repo.fx_table(s, now.date())
    fs = repo.latest_fundamentals(s, inst.id, now)
    etf = None
    if inst.security_type in ("etf", "mutual_fund"):
        est, cons, countries = etf_stats(s, inst, now)
        if est:
            top = sorted(cons or [], key=lambda c: -c.weight_pct)[:25]
            etf = {**est, "countries": countries,
                   "top_holdings": [{"name": c.name, "key": c.key, "weight_pct": c.weight_pct, "sector": c.sector,
                                     "country": c.country} for c in top]}
    bprefs = get_pref(s, "brokerage")
    saved = s.execute(select(SavedInvestment).where(SavedInvestment.instrument_id == inst.id,
                                                    SavedInvestment.archived.is_(False))).scalars().all()
    return {
        "instrument": row(inst, {"provider_symbols"}),
        "price": price_block(bar.close, bar.currency, bar.ts.date().isoformat(), bar.source, bar.data_status, fx)
        if bar else None,
        "score": row(score) if score else None,
        "recommendation": row(rec) if rec else None,
        "analyses": [row(a, {"evidence_pack"}) for a in analysis],
        "fundamentals": {"as_of": fs.as_of.isoformat(), "period_end": fs.period_end.isoformat() if fs.period_end else None,
                         "source": fs.source, "currency": fs.currency, "metrics": fs.metrics} if fs else None,
        "etf": etf,
        "brokerage": repo.brokerage_status(s, inst.id, now, bprefs.reverify_after_days),
        "saved_in_watchlists": [x.watchlist_id for x in saved],
        "notes": [row(n) for n in s.execute(select(PersonalNote).where(PersonalNote.instrument_id == inst.id)
                                            .order_by(PersonalNote.id.desc()).limit(50)).scalars()],
    }


@router.get("/instruments/{instrument_id}/history")
def history(instrument_id: int, limit: int = Query(120, le=2000), s: Session = Depends(db)) -> dict[str, Any]:
    if s.get(Instrument, instrument_id) is None:
        raise not_found("instrument")
    scores = s.execute(select(Score).where(Score.instrument_id == instrument_id).order_by(Score.id.desc()).limit(limit)
                       ).scalars().all()
    grades = s.execute(select(GradeChange).where(GradeChange.instrument_id == instrument_id)
                       .order_by(GradeChange.id.desc()).limit(limit)).scalars().all()
    recs = s.execute(select(Recommendation).where(Recommendation.instrument_id == instrument_id)
                     .order_by(Recommendation.id.desc()).limit(limit)).scalars().all()
    preds = s.execute(select(Prediction).where(Prediction.instrument_id == instrument_id)
                      .order_by(Prediction.id.desc()).limit(limit)).scalars().all()
    return {"scores": [{"id": x.id, "as_of": x.as_of.isoformat(), "overall": x.overall, "grade": x.grade,
                        "confidence": x.confidence, "coverage": x.coverage, "cycle_id": x.cycle_id} for x in scores],
            "grade_changes": [row(g) for g in grades],
            "recommendations": [row(r, {"portfolio_fit"}) for r in recs],
            "predictions": [row(p) for p in preds]}


@router.get("/instruments/{instrument_id}/news")
def instrument_news(instrument_id: int, days: int = Query(30, le=365), s: Session = Depends(db)) -> list[dict]:
    inst = s.get(Instrument, instrument_id)
    if inst is None:
        raise not_found("instrument")
    since = datetime.now(UTC) - timedelta(days=days)
    out = []
    pairs = s.execute(select(NewsItem, NewsAssessment).join(NewsAssessment, NewsAssessment.news_item_id == NewsItem.id)
                      .where(NewsItem.collected_at >= since).order_by(NewsItem.id.desc())).all()
    for item, a in pairs:
        if inst.symbol in (a.affected_symbols or []):
            out.append({"item": row(item), "assessment": row(a)})
    return out[:200]


@router.get("/instruments/{instrument_id}/bars")
def chart(instrument_id: int, interval: Literal["1min", "5min", "15min", "1h", "1d", "1wk", "1mo"] = "1d",
          range_: str = Query("1Y", alias="range"), indicators: str = Query("", max_length=200),
          s: Session = Depends(db)) -> dict[str, Any]:
    inst = s.get(Instrument, instrument_id)
    if inst is None:
        raise not_found("instrument")
    if range_ not in TIMEFRAMES:
        raise HTTPException(422, f"range must be one of {list(TIMEFRAMES)}")
    now = datetime.now(UTC)
    days = TIMEFRAMES[range_]
    start = datetime(now.year, 1, 1, tzinfo=UTC) if days is None else now - timedelta(days=days)
    warmup = timedelta(days=400)  # so 200-day averages exist at the left edge of the chart
    notes: list[str] = []
    if interval in INTRADAY:
        rows = _intraday(s, inst, interval, start, now, notes)
        data = [_bar_dict(b) for b in rows]
    else:
        rows = repo.daily_bars(s, inst.id, now, lookback_days=(now - start + warmup).days)
        data = [_bar_dict(b) for b in rows]
        if interval in ("1wk", "1mo"):
            data = ind.resample_ohlcv(data, interval)
    closes = [b["close"] for b in data]
    series: dict[str, Any] = {}
    for name in [x.strip().lower() for x in indicators.split(",") if x.strip()]:
        if name.startswith("sma") and name[3:].isdigit():
            series[name] = ind.sma(closes, int(name[3:]))
        elif name.startswith("ema") and name[3:].isdigit():
            series[name] = ind.ema(closes, int(name[3:]))
        elif name == "rsi" or (name.startswith("rsi") and name[3:].isdigit()):
            series[name] = ind.rsi(closes, int(name[3:] or 14))
        elif name == "macd":
            series[name] = ind.macd(closes)
        elif name in ("bb", "bollinger"):
            series["bollinger"] = ind.bollinger(closes)
        else:
            raise HTTPException(422, f"unknown indicator '{name}'")
    keep = [i for i, b in enumerate(data) if b["ts"] >= start]
    first = keep[0] if keep else len(data)
    out_bars = [{**b, "ts": b["ts"].isoformat()} for b in data[first:]]

    def cut(v: Any) -> Any:
        return {k: cut(x) for k, x in v.items()} if isinstance(v, dict) else v[first:]

    meta = {}
    if rows:
        last = rows[-1]
        meta = {"source": last.source, "data_status": last.data_status, "currency": last.currency,
                "last_ts": last.ts.isoformat()}
    if inst.security_type == "etf" and interval in INTRADAY:
        notes.append("Intraday data for funds may be delayed by the provider.")
    return {"instrument_id": inst.id, "symbol": inst.symbol, "interval": interval, "range": range_,
            "bars": out_bars, "indicators": {k: cut(v) for k, v in series.items()}, "meta": meta, "notes": notes,
            "supported_intervals": supported_intervals(s)}


def _bar_dict(b: PriceBar) -> dict[str, Any]:
    return {"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}


def supported_intervals(s: Session) -> list[str]:
    """Daily/weekly/monthly always (from stored daily bars); intraday only if the configured price
    provider supports it."""
    out = ["1d", "1wk", "1mo"]
    try:
        p = registry.build(get_settings(), get_pref(s, "market_data"))
        out = [i for i in INTRADAY if p.prices is not None and i in getattr(p.prices, "supported_intervals", ())] + out
    except Exception as exc:  # noqa: BLE001 - a misconfigured provider simply offers no intraday data
        log.info("intraday intervals unavailable: %s", type(exc).__name__)
    return out


def _intraday(s: Session, inst: Instrument, interval: str, start: datetime, end: datetime, notes: list[str]
              ) -> list[PriceBar]:
    """Intraday bars are fetched on demand (and stored) only when the provider supports them."""
    p = registry.build(get_settings(), get_pref(s, "market_data"))
    if p.prices is None or interval not in getattr(p.prices, "supported_intervals", ()):
        raise HTTPException(422, f"{interval} data is not available from the configured price provider")
    start = max(start, end - timedelta(days=30))
    stored = repo.bars(s, inst.id, interval, start, end)
    if not stored or (end - stored[-1].ts) > timedelta(minutes=30):
        try:
            res = p.prices.bars(InstrumentRef(inst.symbol, inst.exchange, inst.currency, dict(inst.provider_symbols or {})),
                                interval, start.date(), end.date())
            ingest.store_bars(s, inst, res)
            s.flush()
        except ProviderError as exc:
            notes.append(f"Could not refresh intraday data: {exc}")
        stored = repo.bars(s, inst.id, interval, start, end)
    if stored and stored[-1].data_status != "real_time":
        notes.append(f"Intraday prices are {stored[-1].data_status.replace('_', ' ')} ({stored[-1].source}).")
    return stored


class InstrumentIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-]+$")
    exchange: Literal["TSX", "TSXV", "NEO", "CBOE_CA", "NYSE", "NASDAQ", "NYSEARCA", "BATS", "LSE", "XETRA", "EURONEXT",
                      "SIX", "TSE", "HKEX", "ASX", "OTHER"]
    name: str = Field(min_length=1, max_length=255)
    asset_class: Literal["equity", "bond", "commodity", "precious_metal", "cash_equivalent", "multi_asset"]
    security_type: Literal["common_stock", "adr", "etf", "mutual_fund", "reit", "preferred", "trust"]
    currency: Literal["CAD", "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "HKD"]
    country: str | None = Field(None, min_length=2, max_length=2)
    sector: str | None = Field(None, max_length=64)
    region: str | None = Field(None, max_length=32)


@router.post("/instruments", status_code=201)
def add_instrument(body: InstrumentIn, s: Session = Depends(db)) -> dict[str, Any]:
    """Add a security to the research universe (identity facts only; data comes from providers)."""
    from investiq.services.audit import audit

    sym, ex = body.symbol.upper(), body.exchange
    if s.execute(select(Instrument).where(Instrument.symbol == sym, Instrument.exchange == ex)).scalar_one_or_none():
        raise HTTPException(409, f"{sym}:{ex} is already in the universe")
    inst = Instrument(**{**body.model_dump(), "symbol": sym, "country": body.country.upper() if body.country else None},
                      metadata_source="owner entered")
    s.add(inst)
    s.flush()
    audit(s, "instrument.added", actor="owner", entity_type="instrument", entity_id=inst.id, symbol=sym, exchange=ex)
    return row(inst, {"provider_symbols"})
