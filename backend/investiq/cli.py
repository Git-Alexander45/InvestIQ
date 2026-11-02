"""InvestIQ command line: ``investiq <command>``. Run ``investiq --help`` for the list."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from investiq.config import get_settings
from investiq.logging_setup import configure_logging

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _session():
    from investiq.db.session import get_session

    return get_session()


def cmd_migrate(args: argparse.Namespace) -> int:
    from investiq.db.migrate import current_revision, head_revision, upgrade
    from investiq.db.session import get_engine

    engine = get_engine()
    current, head = current_revision(engine), head_revision()
    if current == head:
        print(f"Database is up to date (revision {head}).")
        return 0
    if current is not None and not args.no_backup:
        # Existing data: take and verify a backup before changing the schema.
        from investiq.services import backup

        s = _session()
        try:
            rec = backup.create_backup(s, engine, reason=f"pre-migration {current}->{head}")
            backup.verify_backup(s, rec)
            s.commit()
            if rec.status != "verified":
                print(f"Pre-migration backup failed verification: {rec.verification}. Migration NOT applied.")
                return 2
            print(f"Pre-migration backup verified: {rec.path}")
        finally:
            s.close()
    upgrade(engine)
    print(f"Migrated {current or 'empty database'} -> {head}.")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    rc = cmd_migrate(args)
    if rc:
        return rc
    from investiq.services.bootstrap import bootstrap

    s = _session()
    try:
        _print(bootstrap(s))
        s.commit()
    finally:
        s.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    host = args.host or settings.api_host
    if host not in LOOPBACK and not args.allow_lan:
        print(f"Refusing to listen on {host}: InvestIQ is private and binds to 127.0.0.1 only. "
              "Pass --allow-lan only if you understand the exposure (see docs/SECURITY.md).")
        return 2
    if not settings.secret("api_token"):
        print("INVESTIQ_API_TOKEN is not set. Run 'investiq gen-token' and put the value in .env.")
        return 2
    uvicorn.run("investiq.api.app:create_app", factory=True, host=host, port=args.port or settings.api_port,
                log_level=settings.log_level.lower(), proxy_headers=False, server_header=False)
    return 0


def cmd_run_cycle(args: argparse.Namespace) -> int:
    from investiq.research import locking
    from investiq.research.cycle import run_cycle
    from investiq.services.jobs import run_due

    s = _session()
    try:
        if args.if_due:
            _print(run_due(s))
            return 0
        cycle_date = date.fromisoformat(args.date) if args.date else None
        try:
            c = run_cycle(s, triggered_by="cli", cycle_date=cycle_date, force=args.force)
        except locking.CycleNotDue as exc:
            print(f"Not run: {exc}. Use --force to run again deliberately.")
            return 1
        _print({"cycle_id": c.id, "date": c.cycle_date, "status": c.status, "degraded": c.degraded_reasons,
                "error": c.error, "ai_cost_cad": c.ai_cost_cad})
        return 0 if c.status != "failed" else 3
    finally:
        s.close()


def cmd_backup(args: argparse.Namespace) -> int:
    from investiq.db.session import get_engine
    from investiq.services import backup

    s = _session()
    try:
        rec = backup.create_backup(s, get_engine(), reason="manual")
        backup.verify_backup(s, rec)
        out: dict[str, Any] = {"id": rec.id, "path": rec.path, "status": rec.status, "sha256": rec.sha256}
        if args.restore_test and rec.status == "verified":
            out["restore_test"] = backup.restore_test(s, get_engine(), rec)
        s.commit()
        _print(out)
        return 0 if rec.status == "verified" else 4
    finally:
        s.close()


def cmd_export(args: argparse.Namespace) -> int:
    from investiq.db.session import get_engine
    from investiq.services.backup import export_data

    dest = Path(args.out) if args.out else get_settings().data_dir / "exports"
    path = export_data(get_engine(), dest, args.tables.split(",") if args.tables else None)
    print(path)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from investiq.services.health import health

    s = _session()
    try:
        _print(health(s))
    finally:
        s.close()
    return 0


def cmd_gen_token(args: argparse.Namespace) -> int:
    print(secrets.token_urlsafe(32))
    return 0


def cmd_use_synthetic(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.is_production or not settings.allow_synthetic_data:
        print("Synthetic data is only allowed in development with INVESTIQ_ALLOW_SYNTHETIC_DATA=true.")
        return 2
    from investiq.services.preferences import set_pref

    s = _session()
    try:
        set_pref(s, "market_data", {"price_provider": "synthetic", "fundamentals_provider": "synthetic",
                                    "etf_holdings_provider": "synthetic", "fx_provider": "synthetic"}, actor="owner",
                 reason="development: synthetic data (every report is labelled SYNTHETIC)")
        s.commit()
        print("Market data set to SYNTHETIC. Reports will be clearly labelled as test data.")
    finally:
        s.close()
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from investiq.learning import backtest, strategies

    s = _session()
    try:
        strat = strategies.latest_experimental(s) if args.strategy == "experimental" else strategies.production(s)
        run = backtest.run(s, strat, strategies.frozen(s), date.fromisoformat(args.start), date.fromisoformat(args.end),
                           date.fromisoformat(args.split), rebalance_days=args.rebalance_days, top_n=args.top_n)
        s.commit()
        _print({"run_id": run.id, "passed_validation": run.passed_validation, "notes": run.validation_notes,
                "in_sample": run.in_sample, "out_of_sample": run.out_of_sample})
    finally:
        s.close()
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from investiq.mcp_server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investiq", description="InvestIQ local research platform")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("migrate", help="apply database migrations (backs up existing data first)")
    m.add_argument("--no-backup", action="store_true", help="skip the pre-migration backup (not recommended)")
    m.set_defaults(func=cmd_migrate)

    b = sub.add_parser("bootstrap", help="migrate and load the starter universe, portfolios and strategies")
    b.add_argument("--no-backup", action="store_true")
    b.set_defaults(func=cmd_bootstrap)

    sv = sub.add_parser("serve", help="run the local API server (and scheduler)")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    sv.add_argument("--allow-lan", action="store_true")
    sv.set_defaults(func=cmd_serve)

    rc = sub.add_parser("run-cycle", help="run the daily research cycle")
    rc.add_argument("--if-due", action="store_true", help="only run if today's (or a missed) cycle is due")
    rc.add_argument("--force", action="store_true", help="run again even if the day already completed")
    rc.add_argument("--date", help="research day (YYYY-MM-DD); defaults to the latest scheduled day")
    rc.set_defaults(func=cmd_run_cycle)

    bk = sub.add_parser("backup", help="create and verify a database backup")
    bk.add_argument("--restore-test", action="store_true", help="also restore into a temporary database")
    bk.set_defaults(func=cmd_backup)

    ex = sub.add_parser("export", help="export data as CSV files in a zip")
    ex.add_argument("--out")
    ex.add_argument("--tables", help="comma-separated table names (default: all)")
    ex.set_defaults(func=cmd_export)

    sub.add_parser("status", help="show health and configuration status").set_defaults(func=cmd_status)
    sub.add_parser("gen-token", help="print a new random local API token").set_defaults(func=cmd_gen_token)
    sub.add_parser("use-synthetic-data", help="development only: switch market data to synthetic"
                   ).set_defaults(func=cmd_use_synthetic)

    bt = sub.add_parser("backtest", help="walk-forward backtest against the frozen baseline")
    bt.add_argument("--strategy", choices=["experimental", "production"], default="experimental")
    bt.add_argument("--start", required=True)
    bt.add_argument("--end", required=True)
    bt.add_argument("--split", required=True, help="start of the out-of-sample period")
    bt.add_argument("--rebalance-days", type=int, default=30)
    bt.add_argument("--top-n", type=int, default=10)
    bt.set_defaults(func=cmd_backtest)

    sub.add_parser("mcp", help="run the read-only MCP server over stdio").set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, str(Path(settings.data_dir) / "logs" / "investiq.log"))
    args = build_parser().parse_args(argv)
    started = datetime.now(UTC)
    rc = args.func(args)
    if args.command in ("run-cycle", "backup"):
        print(f"finished in {(datetime.now(UTC) - started).total_seconds():.1f}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
