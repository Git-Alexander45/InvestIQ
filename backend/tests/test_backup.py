import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from investiq.config import get_settings
from investiq.db.base import Base
from investiq.db.session import build_engine
from investiq.models import BackupRecord
from investiq.services import backup
from investiq.services.bootstrap import bootstrap
from tests.conftest import TEST_DB_URL


@pytest.fixture()
def file_db(tmp_path, monkeypatch):
    """Backups need a real database file (or server), not the in-memory test database."""
    monkeypatch.setenv("INVESTIQ_BACKUP_DIR", str(tmp_path / "backups"))
    from investiq.config import reset_settings_cache

    reset_settings_cache()
    if TEST_DB_URL.startswith("postgresql"):
        eng = build_engine(TEST_DB_URL)
        with eng.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            conn.exec_driver_sql("CREATE SCHEMA public")
        from investiq.db.migrate import upgrade

        upgrade(eng)
    else:
        eng = build_engine(f"sqlite:///{tmp_path / 'live.sqlite3'}")
        Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    bootstrap(s)
    s.commit()
    yield eng, s
    s.close()
    eng.dispose()
    reset_settings_cache()


def test_backup_verify_and_restore_test(file_db):
    eng, s = file_db
    rec = backup.create_backup(s, eng, reason="test")
    s.commit()
    assert Path(rec.path).exists() and len(rec.sha256) == 64 and rec.size_bytes > 0
    assert rec.row_counts["instruments"] > 100
    assert Path(rec.path + ".json").exists()
    backup.verify_backup(s, rec)
    assert rec.status == "verified", rec.verification
    assert sorted(p.name for p in Path(rec.path).parent.iterdir()) == sorted([Path(rec.path).name, Path(rec.path).name + ".json"])
    report = backup.restore_test(s, eng, rec)
    assert report["ok"], report
    assert rec.restore_tested_at is not None
    s.commit()
    # The live database is untouched by the restore test.
    assert backup.row_counts(eng)["instruments"] == rec.row_counts["instruments"]


def test_tampered_backup_fails_verification(file_db):
    eng, s = file_db
    rec = backup.create_backup(s, eng)
    with open(rec.path, "ab") as f:
        f.write(b"tamper")
    backup.verify_backup(s, rec)
    assert rec.status == "failed" and "checksum" in rec.verification["error"]


def test_backups_are_never_deleted_automatically(file_db):
    eng, s = file_db
    backup.create_backup(s, eng)
    backup.create_backup(s, eng)
    usage = backup.disk_usage()
    assert usage["count"] == 2 and "never deleted automatically" in usage["note"]
    assert s.query(BackupRecord).count() == 2


def test_export_writes_one_csv_per_table(file_db, tmp_path):
    eng, _ = file_db
    out = backup.export_data(eng, tmp_path / "exports", tables=["instruments", "portfolios"])
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"instruments.csv", "portfolios.csv", "README.txt"} <= names
        assert zf.read("instruments.csv").decode().startswith("id,")


def test_missing_pg_tools_give_a_clear_message(monkeypatch):
    monkeypatch.setenv("INVESTIQ_PG_BIN_DIR", "/nonexistent/bin")
    from sqlalchemy.engine import make_url

    from investiq.config import reset_settings_cache

    reset_settings_cache()
    with pytest.raises(backup.BackupError, match="INVESTIQ_PG_TOOLS_MODE=docker"):
        backup._pg_cmd(get_settings(), "pg_dump", make_url("postgresql+psycopg://u:p@localhost/db"), [])
    reset_settings_cache()


def test_docker_mode_never_puts_password_on_command_line(monkeypatch):
    monkeypatch.setenv("INVESTIQ_PG_TOOLS_MODE", "docker")
    from sqlalchemy.engine import make_url

    from investiq.config import reset_settings_cache

    reset_settings_cache()
    url = make_url("postgresql+psycopg://investiq:s3cret@localhost/investiq")
    cmd = backup._pg_cmd(get_settings(), "pg_dump", url, ["--format=custom", "investiq"])
    assert cmd[:3] == ["docker", "compose", "-f"] and "exec" in cmd and "s3cret" not in " ".join(cmd)
    assert backup._pg_env(url)["PGPASSWORD"] == "s3cret"
    reset_settings_cache()


def test_export_neutralises_spreadsheet_formulas():
    assert backup._csv_cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert backup._csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert backup._csv_cell("Fed holds rates") == "Fed holds rates"
    assert backup._csv_cell(-1.5) == -1.5
    assert backup._csv_cell({"a": 1}) == '{"a": 1}'
