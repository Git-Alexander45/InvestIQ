"""Reference data and market data: instruments, prices, FX, fundamentals, ETF holdings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from investiq.db.base import Base, utcnow

# Underlying exposure class. The vehicle (stock, ETF, ...) is recorded in ``security_type``.
ASSET_CLASSES = ("equity", "bond", "commodity", "precious_metal", "cash_equivalent", "multi_asset")
SECURITY_TYPES = ("common_stock", "adr", "cdr", "preferred", "etf", "mutual_fund", "bond", "gic")
FUND_TYPES = ("etf", "mutual_fund")
DATA_STATUSES = ("live", "delayed", "end_of_day", "reference", "synthetic")
QUALITY_STATUSES = ("ok", "stale", "suspect", "missing", "discrepancy", "synthetic")


class Instrument(Base):
    """A tradable security identified by symbol + exchange (the exact listing matters)."""

    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "exchange"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16))  # e.g. TSX, NYSE, NASDAQ, NEO, LSE
    name: Mapped[str] = mapped_column(String(255))
    asset_class: Mapped[str] = mapped_column(String(24), index=True)
    security_type: Mapped[str] = mapped_column(String(32), default="common_stock")
    currency: Mapped[str] = mapped_column(String(3))  # trading currency
    country: Mapped[str | None] = mapped_column(String(2))  # issuer / domicile ISO-3166 alpha-2
    region: Mapped[str | None] = mapped_column(String(24))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))
    themes: Mapped[list[Any]] = mapped_column(default=list)  # emerging-industry research tags
    is_reit: Mapped[bool] = mapped_column(Boolean, default=False)
    is_leveraged: Mapped[bool] = mapped_column(Boolean, default=False)
    is_inverse: Mapped[bool] = mapped_column(Boolean, default=False)
    is_speculative: Mapped[bool] = mapped_column(Boolean, default=False)
    currency_hedged: Mapped[bool | None] = mapped_column(Boolean)
    underlying_currency: Mapped[str | None] = mapped_column(String(3))
    mer_pct: Mapped[float | None] = mapped_column(Float)  # management expense ratio, percent
    provider_symbols: Mapped[dict[str, Any]] = mapped_column(default=dict)  # per data provider
    metadata_source: Mapped[str] = mapped_column(String(128), default="manual")
    listed_on: Mapped[date | None] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)  # kept for survivorship-bias-free tests
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def display(self) -> str:
        return f"{self.symbol}:{self.exchange}"


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (Index("ix_price_bars_lookup", "instrument_id", "interval", "ts"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True)  # 1min,5min,15min,1h,1d,1wk,1mo
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    data_status: Mapped[str] = mapped_column(String(16), default="end_of_day")
    quality: Mapped[str] = mapped_column(String(16), default="ok")
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)


class Quote(Base):
    """Point-in-time price observations (append-only)."""

    __tablename__ = "quotes"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    as_of: Mapped[datetime] = mapped_column()
    source: Mapped[str] = mapped_column(String(32))
    data_status: Mapped[str] = mapped_column(String(16))
    quality: Mapped[str] = mapped_column(String(16), default="ok")
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("base", "quote", "as_of", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    base: Mapped[str] = mapped_column(String(3))
    quote: Mapped[str] = mapped_column(String(3))
    rate: Mapped[float] = mapped_column(Float)  # 1 base = rate quote
    as_of: Mapped[date] = mapped_column(Date, index=True)
    rate_type: Mapped[str] = mapped_column(String(32), default="daily_reference")
    source: Mapped[str] = mapped_column(String(64))
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)


class FundamentalsSnapshot(Base):
    """Fundamental metrics as known at ``as_of`` (point-in-time; append-only)."""

    __tablename__ = "fundamentals_snapshots"
    __append_only__ = True
    __table_args__ = (Index("ix_fund_instr_asof", "instrument_id", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    as_of: Mapped[datetime] = mapped_column()  # when this information became available to us
    period_end: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(32))
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    quality: Mapped[str] = mapped_column(String(16), default="ok")
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)


class EtfHoldingsSnapshot(Base):
    __tablename__ = "etf_holdings_snapshots"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))
    coverage_pct: Mapped[float | None] = mapped_column(Float)  # sum of weights captured
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)
    holdings: Mapped[list[EtfHolding]] = relationship(back_populates="snapshot", lazy="selectin")


class EtfHolding(Base):
    __tablename__ = "etf_holdings"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("etf_holdings_snapshots.id"), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    weight_pct: Mapped[float] = mapped_column(Float)
    asset_class: Mapped[str | None] = mapped_column(String(24))
    sector: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(2))
    currency: Mapped[str | None] = mapped_column(String(3))
    snapshot: Mapped[EtfHoldingsSnapshot] = relationship(back_populates="holdings")


class Dividend(Base):
    __tablename__ = "dividends"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("instrument_id", "ex_date", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    ex_date: Mapped[date] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)  # per share, trading currency
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(32))
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("instrument_id", "effective_date", "kind", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    effective_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(24))  # split, reverse_split, symbol_change, delisting
    ratio: Mapped[float | None] = mapped_column(Float)  # new shares per old share
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source: Mapped[str] = mapped_column(String(32))
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, index=True)
    issue_type: Mapped[str] = mapped_column(String(24))  # stale, missing, discrepancy, outlier, invalid
    severity: Mapped[str] = mapped_column(String(12), default="warning")
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    detected_at: Mapped[datetime] = mapped_column(default=utcnow)
