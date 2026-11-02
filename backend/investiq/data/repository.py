"""Point-in-time read helpers. Every query takes ``as_of`` so nothing from the future leaks in."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from investiq.finance.fx import FxQuote, FxTable
from investiq.models import (
    BrokerageVerification,
    Dividend,
    EtfHoldingsSnapshot,
    FundamentalsSnapshot,
    FxRate,
    Instrument,
    PriceBar,
)

SOURCE_PREFERENCE = ["fmp", "twelvedata", "sec_edgar", "synthetic"]


def end_of(d: date) -> datetime:
    return datetime.combine(d, time.max, UTC)


def daily_bars(session: Session, instrument_id: int, as_of: datetime, lookback_days: int = 365 * 5 + 30,
               source: str | None = None) -> list[PriceBar]:
    start = as_of - timedelta(days=lookback_days)
    q = select(PriceBar).where(PriceBar.instrument_id == instrument_id, PriceBar.interval == "1d",
                               PriceBar.ts <= as_of, PriceBar.ts >= start)
    if source:
        q = q.where(PriceBar.source == source)
    rows = list(session.execute(q.order_by(PriceBar.ts)).scalars())
    if source or not rows:
        return rows
    # One series per instrument: prefer the highest-priority source present.
    sources = {r.source for r in rows}
    best = next((s for s in SOURCE_PREFERENCE if s in sources), sorted(sources)[0])
    return [r for r in rows if r.source == best]


def bars(session: Session, instrument_id: int, interval: str, start: datetime, end: datetime) -> list[PriceBar]:
    rows = list(session.execute(
        select(PriceBar).where(PriceBar.instrument_id == instrument_id, PriceBar.interval == interval,
                               PriceBar.ts >= start, PriceBar.ts <= end).order_by(PriceBar.ts)
    ).scalars())
    sources = {r.source for r in rows}
    if len(sources) > 1:
        best = next((s for s in SOURCE_PREFERENCE if s in sources), sorted(sources)[0])
        rows = [r for r in rows if r.source == best]
    return rows


def last_bar(session: Session, instrument_id: int, as_of: datetime) -> PriceBar | None:
    rows = daily_bars(session, instrument_id, as_of, lookback_days=30)
    return rows[-1] if rows else None


def bar_on_or_after(session: Session, instrument_id: int, ts: datetime, max_days: int = 10) -> PriceBar | None:
    rows = list(session.execute(
        select(PriceBar).where(PriceBar.instrument_id == instrument_id, PriceBar.interval == "1d",
                               PriceBar.ts >= ts, PriceBar.ts <= ts + timedelta(days=max_days))
        .order_by(PriceBar.ts)
    ).scalars())
    if not rows:
        return None
    sources = {r.source for r in rows}
    best = next((s for s in SOURCE_PREFERENCE if s in sources), sorted(sources)[0])
    return next(r for r in rows if r.source == best)


def latest_fundamentals(session: Session, instrument_id: int, as_of: datetime) -> FundamentalsSnapshot | None:
    rows = list(session.execute(
        select(FundamentalsSnapshot).where(FundamentalsSnapshot.instrument_id == instrument_id,
                                           FundamentalsSnapshot.as_of <= as_of)
        .order_by(FundamentalsSnapshot.as_of.desc(), FundamentalsSnapshot.id.desc()).limit(10)
    ).scalars())
    if not rows:
        return None
    for src in SOURCE_PREFERENCE:
        for r in rows:
            if r.source == src:
                return r
    return rows[0]


def latest_holdings(session: Session, etf_id: int, as_of: date) -> EtfHoldingsSnapshot | None:
    return session.execute(
        select(EtfHoldingsSnapshot).where(EtfHoldingsSnapshot.etf_id == etf_id, EtfHoldingsSnapshot.as_of <= as_of)
        .order_by(EtfHoldingsSnapshot.as_of.desc(), EtfHoldingsSnapshot.id.desc()).limit(1)
    ).scalar_one_or_none()


def dividends_between(session: Session, instrument_id: int, start: date, end: date) -> list[Dividend]:
    return list(session.execute(
        select(Dividend).where(Dividend.instrument_id == instrument_id, Dividend.ex_date > start,
                               Dividend.ex_date <= end).order_by(Dividend.ex_date)
    ).scalars())


def fx_table(session: Session, as_of: date, lookback_days: int = 14) -> FxTable:
    rows = session.execute(
        select(FxRate).where(FxRate.as_of <= as_of, FxRate.as_of >= as_of - timedelta(days=lookback_days))
        .order_by(FxRate.as_of)
    ).scalars()
    return FxTable([FxQuote(r.base, r.quote, r.rate, r.as_of, r.source, r.rate_type) for r in rows])


def brokerage_status(session: Session, instrument_id: int, as_of: datetime | None = None,
                     reverify_after_days: int | None = None) -> dict[str, dict]:
    """Latest verification per brokerage. Missing or expired evidence => UNVERIFIED."""
    as_of = as_of or datetime.now(UTC)
    rows = session.execute(
        select(BrokerageVerification).where(BrokerageVerification.instrument_id == instrument_id,
                                            BrokerageVerification.verified_at <= as_of)
        .order_by(BrokerageVerification.verified_at.desc(), BrokerageVerification.id.desc())
    ).scalars()
    out: dict[str, dict] = {}
    for r in rows:
        if r.brokerage in out:
            continue
        status = r.status
        expired = (reverify_after_days is not None and status != "UNAVAILABLE"
                   and (as_of - r.verified_at).days > reverify_after_days)
        out[r.brokerage] = {
            "status": "UNVERIFIED" if expired else status,
            "recorded_status": r.status, "expired": expired, "verified_at": r.verified_at.isoformat(),
            "ticker": r.ticker, "exchange": r.exchange, "evidence_source": r.evidence_source,
            "evidence_note": r.evidence_note, "tfsa_eligible": r.tfsa_eligible, "verification_id": r.id,
        }
    for b in ("wealthsimple", "questrade"):
        out.setdefault(b, {"status": "UNVERIFIED", "recorded_status": None, "expired": False,
                           "evidence_note": "No verification recorded"})
    return out


def instrument_by_symbol(session: Session, symbol: str, exchange: str | None = None) -> Instrument | None:
    q = select(Instrument).where(Instrument.symbol == symbol.upper())
    if exchange:
        q = q.where(Instrument.exchange == exchange.upper())
    return session.execute(q.limit(1)).scalar_one_or_none()
