"""Brokerage availability evidence. Status is never assumed from an exchange listing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base, utcnow

BROKERAGES = ("wealthsimple", "questrade")
STATUSES = ("VERIFIED", "UNVERIFIED", "UNAVAILABLE")


class BrokerageVerification(Base):
    __tablename__ = "brokerage_verifications"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    brokerage: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(12))
    ticker: Mapped[str] = mapped_column(String(32))  # exact ticker as shown by the brokerage
    exchange: Mapped[str] = mapped_column(String(16))
    security_type: Mapped[str | None] = mapped_column(String(32))
    trading_currency: Mapped[str | None] = mapped_column(String(3))
    tfsa_eligible: Mapped[bool | None] = mapped_column(Boolean)
    account_restrictions: Mapped[str | None] = mapped_column(Text)
    evidence_source: Mapped[str] = mapped_column(String(64))  # manual_app_check, csv_import, ...
    evidence_note: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    verified_by: Mapped[str] = mapped_column(String(64), default="owner")
    verified_at: Mapped[datetime] = mapped_column(default=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
