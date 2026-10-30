"""Declarative base, portable column types and the append-only guard.

Historical records (analyses, grades, recommendations, trades, notes, ...) are append-only:
the ORM refuses UPDATE and DELETE on them, and on PostgreSQL a database trigger enforces the
same rule (see the initial migration). A change is recorded by inserting a new version.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC timestamps on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime stored; use timezone-aware UTC datetimes")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType, datetime: UTCDateTime}

    # Subclasses set this to True to forbid UPDATE/DELETE through the ORM.
    __append_only__: bool = False
    # Subclasses may whitelist columns that are allowed to change (e.g. a status field
    # on a job record). Historical content columns must never be listed here.
    __mutable_columns__: frozenset[str] = frozenset()


class AppendOnlyViolation(RuntimeError):
    pass


def append_only_tables() -> list[str]:
    return sorted(
        m.class_.__tablename__
        for m in Base.registry.mappers
        if getattr(m.class_, "__append_only__", False) and not m.class_.__mutable_columns__
    )


def protected_tables() -> list[str]:
    """Tables whose rows may never be deleted (append-only and status-mutable alike)."""
    return sorted(
        m.class_.__tablename__ for m in Base.registry.mappers if getattr(m.class_, "__append_only__", False)
    )


@event.listens_for(Session, "before_flush")
def _enforce_append_only(session: Session, flush_context: Any, instances: Any) -> None:
    from sqlalchemy import inspect

    for obj in session.deleted:
        if getattr(obj, "__append_only__", False):
            raise AppendOnlyViolation(f"{type(obj).__name__} rows are permanent and cannot be deleted")
    for obj in session.dirty:
        if not getattr(obj, "__append_only__", False):
            continue
        state = inspect(obj)
        changed = {a.key for a in state.attrs if a.history.has_changes()}
        illegal = changed - set(obj.__mutable_columns__)
        if illegal:
            raise AppendOnlyViolation(
                f"{type(obj).__name__} is append-only; refusing to modify {sorted(illegal)}. "
                "Insert a new version instead."
            )
