"""AI usage, preferences, notifications, email delivery, reports, audit log and backups."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base, utcnow


class AiRequest(Base):
    __tablename__ = "ai_requests"
    __append_only__ = True
    __mutable_columns__ = frozenset(
        {"status", "input_tokens", "output_tokens", "cost_usd", "cost_cad", "latency_ms", "error",
         "stop_reason", "provider_request_id", "served_model"}
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    task: Mapped[str] = mapped_column(String(48), index=True)
    role: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(16))  # low_cost, premium, reviewer
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    served_model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))  # reserved, ok, error, invalid_output, blocked_budget, refusal
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cad: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    usd_cad_rate: Mapped[float] = mapped_column(Float)
    usd_cad_source: Mapped[str] = mapped_column(String(160))
    cost_cad: Mapped[float] = mapped_column(Float, default=0.0)
    pricing_version: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    stop_reason: Mapped[str | None] = mapped_column(String(24))
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    budget_month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class BudgetLedger(Base):
    """One row per calendar month; locked during reservation to serialise budget checks."""

    __tablename__ = "ai_budget_months"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PreferenceVersion(Base):
    """Owner preferences. Every change is a new row; the latest per key is current."""

    __tablename__ = "preference_versions"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[dict[str, Any]] = mapped_column()
    changed_by: Mapped[str] = mapped_column(String(64), default="owner")
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __append_only__ = True
    __mutable_columns__ = frozenset({"read_at", "deliveries"})

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(12), default="info")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), index=True)
    deliveries: Mapped[dict[str, Any]] = mapped_column(default=dict)
    read_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Report(Base):
    __tablename__ = "reports"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # daily, failure
    subject: Mapped[str] = mapped_column(String(255))
    html: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    __append_only__ = True
    __mutable_columns__ = frozenset({"status", "error", "sent_at", "provider_message_id", "attempts"})

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"))
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("research_cycles.id"))
    kind: Mapped[str] = mapped_column(String(24))
    to_address: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, sent, failed, skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class BackupRecord(Base):
    __tablename__ = "backups"
    __append_only__ = True
    __mutable_columns__ = frozenset({"verified_at", "restore_tested_at", "status", "verification"})

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1024))
    method: Mapped[str] = mapped_column(String(24))  # pg_dump, sqlite_backup
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    row_counts: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="created")  # created, verified, failed
    verification: Mapped[dict[str, Any]] = mapped_column(default=dict)
    verified_at: Mapped[datetime | None] = mapped_column()
    restore_tested_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class JobRun(Base):
    """Non-research background jobs (backups, alert checks, prediction evaluation)."""

    __tablename__ = "job_runs"
    __append_only__ = True
    __mutable_columns__ = frozenset({"status", "finished_at", "detail", "error"})

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(48), index=True)
    run_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
