"""Database-level protection of historical records (PostgreSQL) and optional TimescaleDB.

On PostgreSQL, triggers make append-only tables reject UPDATE/DELETE, and make every other
historical table reject DELETE. This protects history even from ad-hoc SQL sessions.
SQLite relies on the ORM guard in ``investiq.db.base`` (SQLite is for tests/dev only).

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Frozen lists (do not import from the models: migrations must stay stable over time).
FULLY_APPEND_ONLY = [
    "analyses", "audit_log", "backtest_runs", "brokerage_verifications", "corporate_actions",
    "data_quality_issues", "dividends", "etf_holdings", "etf_holdings_snapshots", "external_costs",
    "fundamentals_snapshots", "fx_rates", "grade_changes", "leaderboard_entries", "news_assessments",
    "owner_holding_entries", "paper_cash_ledger", "paper_dividends", "paper_fills",
    "paper_position_adjustments", "personal_notes", "portfolio_milestones", "portfolio_snapshots",
    "prediction_evaluations", "predictions", "preference_versions", "quotes", "recommendations",
    "reports", "scores", "strategy_promotions", "strategy_versions", "tfsa_profiles",
]
NO_DELETE = [
    "ai_requests", "alerts", "backups", "cycle_steps", "email_deliveries", "job_runs", "news_clusters",
    "news_items", "notifications", "paper_orders", "research_cycles", "saved_investments", "watchlists",
    "instruments", "portfolios", "price_bars", "news_sources",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION investiq_reject_change() RETURNS trigger AS $$
        BEGIN
            IF current_setting('investiq.allow_history_change', true) = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'InvestIQ: % on % is not permitted; historical records are permanent',
                TG_OP, TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in FULLY_APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION investiq_reject_change();"
        )
    for table in NO_DELETE:
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION investiq_reject_change();"
        )
    # TimescaleDB is optional: use it for price bars when the extension is installed.
    has_timescale = bind.exec_driver_sql(
        "SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"
    ).scalar()
    if has_timescale:
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        op.execute("SELECT create_hypertable('price_bars', 'ts', migrate_data => true, if_not_exists => true)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in FULLY_APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    for table in NO_DELETE:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS investiq_reject_change()")
