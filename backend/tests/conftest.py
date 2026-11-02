from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("INVESTIQ_ENV", "test")
os.environ.setdefault("INVESTIQ_ENV_FILE", "/nonexistent/.env")
os.environ.setdefault("INVESTIQ_ALLOW_SYNTHETIC_DATA", "true")
os.environ.setdefault("INVESTIQ_SCHEDULER_ENABLED", "false")
# Tests never write logs, backups or exports into the repository.
os.environ.setdefault("INVESTIQ_DATA_DIR", tempfile.mkdtemp(prefix="investiq-test-"))

import investiq.models  # noqa: E402,F401
from investiq.config import reset_settings_cache  # noqa: E402
from investiq.db.session import build_engine, set_engine  # noqa: E402

TEST_DB_URL = os.environ.get("INVESTIQ_TEST_DATABASE_URL", "sqlite://")


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIQ_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("INVESTIQ_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("INVESTIQ_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("INVESTIQ_DATABASE_URL", TEST_DB_URL)
    reset_settings_cache()
    eng = build_engine(TEST_DB_URL)
    if TEST_DB_URL.startswith("postgresql"):
        _reset_postgres(eng)
    from investiq.db.migrate import upgrade

    upgrade(eng)  # migrations (with history-protection triggers) on both databases
    set_engine(eng)
    yield eng
    eng.dispose()
    reset_settings_cache()


def _reset_postgres(eng) -> None:
    # Test database only: drop and recreate the public schema for isolation.
    assert "test" in str(eng.url.database), "refusing to reset a non-test database"
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")


@pytest.fixture()
def session(engine) -> Iterator[Session]:
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
