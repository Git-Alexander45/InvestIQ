"""Watchlists, saved investments, personal notes and alerts. Nothing here is ever deleted."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base, utcnow


class Watchlist(Base):
    __tablename__ = "watchlists"
    __append_only__ = True
    __mutable_columns__ = frozenset({"name", "description", "archived"})

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SavedInvestment(Base):
    __tablename__ = "saved_investments"
    __append_only__ = True
    __mutable_columns__ = frozenset({"archived"})
    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    saved_at: Mapped[datetime] = mapped_column(default=utcnow)
    saved_from: Mapped[str | None] = mapped_column(String(64))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class PersonalNote(Base):
    """Owner's own words: notes, why they like it, their thesis. Versioned by insertion."""

    __tablename__ = "personal_notes"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # note, why_i_like_it, thesis
    body: Mapped[str] = mapped_column(Text)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("personal_notes.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __append_only__ = True
    __mutable_columns__ = frozenset({"active", "last_triggered_at", "last_value"})

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # price_above, price_below, pct_move_day, grade_change
    threshold: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column()
    last_value: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
