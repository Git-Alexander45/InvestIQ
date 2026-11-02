"""Database-level protection of historical records on SQLite (the Windows desktop app).

Mirrors 0002 for SQLite: append-only tables reject UPDATE and DELETE, every other historical
table rejects DELETE. The ORM guard in ``investiq.db.base`` remains the first line of defence.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _lists() -> tuple[list[str], list[str]]:
    # Same frozen lists as 0002 (loaded from that file so the two can never drift apart).
    path = Path(__file__).with_name("0002_history_protection.py")
    spec = importlib.util.spec_from_file_location("investiq_migration_0002", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FULLY_APPEND_ONLY, mod.NO_DELETE


def _reject(table: str, op_name: str) -> str:
    return f"SELECT RAISE(ABORT, 'InvestIQ: {op_name} on {table} is not permitted; historical records are permanent');"


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    append_only, no_delete = _lists()
    for table in append_only:
        op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_append_only_upd BEFORE UPDATE ON {table} "
                   f"BEGIN {_reject(table, 'UPDATE')} END;")
        op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_append_only_del BEFORE DELETE ON {table} "
                   f"BEGIN {_reject(table, 'DELETE')} END;")
    for table in no_delete:
        op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
                   f"BEGIN {_reject(table, 'DELETE')} END;")


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    append_only, no_delete = _lists()
    for table in append_only:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_upd")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_del")
    for table in no_delete:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
