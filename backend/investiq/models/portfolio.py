"""Owner portfolios (manually entered) and the paper-trading / benchmark simulation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base, utcnow


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # OWNER, A, B, C, D, BM_GLOBAL, ...
    kind: Mapped[str] = mapped_column(String(16))  # owner, paper, benchmark
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    base_currency: Mapped[str] = mapped_column(String(3), default="CAD")
    account_type: Mapped[str] = mapped_column(String(16), default="TFSA")  # TFSA, RRSP, NON_REGISTERED
    initial_cash: Mapped[float] = mapped_column(Float, default=0.0)
    inception_date: Mapped[date | None] = mapped_column(Date)
    strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    policy: Mapped[dict[str, Any]] = mapped_column(default=dict)  # allocation/risk policy
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class OwnerHoldingEntry(Base):
    """Manually entered holding state. Each edit inserts a new entry; latest wins."""

    __tablename__ = "owner_holding_entries"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(16), default="TFSA")
    quantity: Mapped[float] = mapped_column(Float)  # 0 closes the position
    average_cost: Mapped[float] = mapped_column(Float)
    cost_currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str | None] = mapped_column(Text)
    entered_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __append_only__ = True
    __mutable_columns__ = frozenset({"status", "status_reason"})

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(4))  # BUY, SELL
    quantity: Mapped[float] = mapped_column(Float)
    decision_at: Mapped[datetime] = mapped_column()
    decision_price: Mapped[float] = mapped_column(Float)
    decision_price_as_of: Mapped[datetime] = mapped_column()
    decision_context: Mapped[dict[str, Any]] = mapped_column(default=dict)  # info available then
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, filled, cancelled
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperFill(Base):
    __tablename__ = "paper_fills"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("paper_orders.id"), unique=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[float] = mapped_column(Float)
    market_price: Mapped[float] = mapped_column(Float)  # reference bar price before slippage
    fill_price: Mapped[float] = mapped_column(Float)  # trading currency, after slippage
    currency: Mapped[str] = mapped_column(String(3))
    fx_rate_to_cad: Mapped[float] = mapped_column(Float)
    fx_as_of: Mapped[date] = mapped_column(Date)
    gross_cad: Mapped[float] = mapped_column(Float)
    commission_cad: Mapped[float] = mapped_column(Float, default=0.0)
    fx_fee_cad: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_cad: Mapped[float] = mapped_column(Float, default=0.0)
    filled_at: Mapped[datetime] = mapped_column()
    price_source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperCashEntry(Base):
    __tablename__ = "paper_cash_ledger"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    ts: Mapped[datetime] = mapped_column()
    amount_cad: Mapped[float] = mapped_column(Float)  # signed
    kind: Mapped[str] = mapped_column(String(16))  # deposit, buy, sell, fee, dividend, withholding
    reference: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperPositionAdjustment(Base):
    """Share-count changes not caused by trades: splits, dividend reinvestment."""

    __tablename__ = "paper_position_adjustments"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    ts: Mapped[datetime] = mapped_column()
    quantity_delta: Mapped[float] = mapped_column(Float)
    cost_delta_cad: Mapped[float] = mapped_column(Float, default=0.0)
    kind: Mapped[str] = mapped_column(String(16))  # split, drip
    reference: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperDividend(Base):
    __tablename__ = "paper_dividends"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("portfolio_id", "dividend_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    dividend_id: Mapped[int] = mapped_column(ForeignKey("dividends.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    shares: Mapped[float] = mapped_column(Float)
    gross_cad: Mapped[float] = mapped_column(Float)
    withholding_cad: Mapped[float] = mapped_column(Float)
    net_cad: Mapped[float] = mapped_column(Float)
    reinvested: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("portfolio_id", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    cash_cad: Mapped[float] = mapped_column(Float)
    market_value_cad: Mapped[float] = mapped_column(Float)
    total_value_cad: Mapped[float] = mapped_column(Float)
    holdings: Mapped[list[Any]] = mapped_column(default=list)
    priced_with: Mapped[dict[str, Any]] = mapped_column(default=dict)  # price/fx provenance
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PortfolioMilestone(Base):
    __tablename__ = "portfolio_milestones"
    __append_only__ = True
    __table_args__ = (UniqueConstraint("portfolio_id", "kind", "threshold"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    kind: Mapped[str] = mapped_column(String(24))
    threshold: Mapped[float] = mapped_column(Float)
    reached_at: Mapped[datetime] = mapped_column(default=utcnow)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class TfsaProfile(Base):
    """Owner-entered TFSA facts. Contribution room is never inferred."""

    __tablename__ = "tfsa_profiles"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    contribution_room_cad: Mapped[float | None] = mapped_column(Float)
    room_as_of: Mapped[date | None] = mapped_column(Date)
    source_note: Mapped[str | None] = mapped_column(Text)  # e.g. "CRA My Account, 2026-01-15"
    entered_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExternalCost(Base):
    """Non-AI service costs (market data, email, hosting), tracked separately from AI tokens."""

    __tablename__ = "external_costs"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))  # market_data, email, hosting, other
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    period: Mapped[str] = mapped_column(String(16))  # monthly, annual, one_time
    note: Mapped[str | None] = mapped_column(Text)
    started_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


