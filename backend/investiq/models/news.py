"""News and developments. Only metadata, links and our own short summaries are stored;
full copyrighted article bodies are never persisted."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base, utcnow


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(24))  # rss, api
    url: Mapped[str] = mapped_column(String(512))
    category: Mapped[str] = mapped_column(String(32))  # central_bank, government, company, markets, ...
    official: Mapped[bool] = mapped_column(default=False)
    license_note: Mapped[str] = mapped_column(String(255), default="headline+link only")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class NewsCluster(Base):
    """Groups duplicate and related reports of the same development."""

    __tablename__ = "news_clusters"
    __append_only__ = True
    __mutable_columns__ = frozenset({"item_count", "last_seen_at"})

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    item_count: Mapped[int] = mapped_column(default=1)


class NewsItem(Base):
    __tablename__ = "news_items"
    __append_only__ = True
    __mutable_columns__ = frozenset({"cluster_id", "duplicate_of_id"})

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text)  # short excerpt/our summary, never full text
    published_at: Mapped[datetime | None] = mapped_column(index=True)
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)
    title_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str | None] = mapped_column(String(32))
    official: Mapped[bool] = mapped_column(default=False)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("news_clusters.id"), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("news_items.id"))
    cycle_id: Mapped[int | None] = mapped_column(index=True)


class NewsAssessment(Base):
    """Structured interpretation of a development (rules engine or AI), append-only."""

    __tablename__ = "news_assessments"
    __append_only__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True)
    method: Mapped[str] = mapped_column(String(64))  # "rules:v1" or "ai:<model>:<prompt_version>"
    topic: Mapped[str] = mapped_column(String(48))  # central_bank, tariffs, earnings, ...
    what_happened: Mapped[str] = mapped_column(Text)
    event_time: Mapped[datetime | None] = mapped_column()
    confirmation: Mapped[str] = mapped_column(String(16))  # confirmed, reported, rumour, unknown
    impact: Mapped[str] = mapped_column(String(12))  # positive, negative, mixed, uncertain
    horizon: Mapped[str] = mapped_column(String(12))  # short_term, long_term, unclear
    confidence: Mapped[float] = mapped_column(Float)
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    affected_symbols: Mapped[list[Any]] = mapped_column(default=list)
    affected_sectors: Mapped[list[Any]] = mapped_column(default=list)
    affected_etfs: Mapped[list[Any]] = mapped_column(default=list)
    evidence: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
