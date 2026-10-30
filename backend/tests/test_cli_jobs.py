from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from investiq import cli
from investiq.db.base import Base
from investiq.models import JobRun
from investiq.services import jobs
from investiq.services.bootstrap import bootstrap
from investiq.services.preferences import set_pref


def test_serve_refuses_non_loopback_and_missing_token(monkeypatch, capsys):
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("server must not start"))
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert "Refusing" in capsys.readouterr().out
    monkeypatch.delenv("INVESTIQ_API_TOKEN", raising=False)
    assert cli.main(["serve"]) == 2


def test_gen_token_is_long_and_random(capsys):
    cli.main(["gen-token"])
    a = capsys.readouterr().out.strip()
    cli.main(["gen-token"])
    b = capsys.readouterr().out.strip()
    assert len(a) >= 40 and a != b


def test_run_due_skips_when_not_due_and_records_backup_job(session, monkeypatch, tmp_path):
    bootstrap(session)
    set_pref(session, "research_schedule", {"enabled": False}, actor="test")
    session.commit()
    file_engine = create_engine(f"sqlite:///{tmp_path / 'x.sqlite3'}")
    Base.metadata.create_all(file_engine)
    monkeypatch.setattr(jobs, "get_engine", lambda: file_engine)
    out = jobs.run_due(session, datetime(2026, 10, 29, 23, 0, tzinfo=UTC))
    assert out["cycle"] == "not due"
    assert out["backup"]["status"] == "succeeded"
    assert jobs.backup_if_due(session, datetime(2026, 10, 29, 23, 30, tzinfo=UTC))["status"] == "not_due"
    assert session.query(JobRun).filter_by(job="backup").count() == 1


def test_scheduler_survives_errors(monkeypatch):
    calls = []

    def boom(session, now):
        calls.append(now)
        raise RuntimeError("provider outage")

    monkeypatch.setattr(jobs, "run_due", boom)
    sch = jobs.Scheduler(poll_seconds=3600)
    sch.tick()
    sch.tick()
    assert len(calls) == 2 and sch.last_result is None


def test_migrations_match_models(engine):
    """The Alembic migrations must produce exactly the schema the ORM models describe."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from investiq.db.migrate import upgrade

    if engine.dialect.name == "sqlite":
        eng = create_engine("sqlite://")
        upgrade(eng)
    else:
        eng = engine  # conftest already migrated the PostgreSQL test database
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], diff
