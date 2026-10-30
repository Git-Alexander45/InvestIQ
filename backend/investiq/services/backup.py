"""Database backups, verification, restore tests and data export.

* PostgreSQL: ``pg_dump --format=custom`` (locally or inside the compose database service).
* SQLite (development/tests): the online backup API.

Every backup is checksummed (SHA-256), described by row counts, and recorded in ``backups``.
A restore test loads the backup into a separate temporary database and compares row counts;
the live database is never touched. Old backups are never deleted automatically (deleting
history needs the owner's explicit decision), so the disk usage is reported instead.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from investiq.config import Settings, get_settings
from investiq.db.base import Base
from investiq.models import BackupRecord
from investiq.services.audit import audit


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _restrict(path: Path) -> None:
    """Owner-only permissions where the OS supports them (Windows inherits the user-profile ACL)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def row_counts(engine: Engine) -> dict[str, int]:
    out = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            out[table.name] = int(conn.execute(select(func.count()).select_from(table)).scalar_one())
    return out


# ------------------------------------------------------------------------------------------------
# PostgreSQL tool invocation
# ------------------------------------------------------------------------------------------------


def _pg_env(url) -> dict[str, str]:
    env = {**os.environ}
    if url.password:
        env["PGPASSWORD"] = url.password  # passed via environment, never on the command line
    return env


def _pg_cmd(settings: Settings, tool: str, url, args: list[str]) -> list[str]:
    conn = ["-U", url.username or "postgres"]
    if settings.pg_tools_mode == "docker":
        return ["docker", "compose", "-f", str(settings.docker_compose_file), "exec", "-T", settings.docker_db_service,
                tool, *conn, *args]
    exe = str(Path(settings.pg_bin_dir) / tool) if settings.pg_bin_dir else tool
    if shutil.which(exe) is None and not Path(exe).exists():
        raise BackupError(f"{tool} not found. Install the PostgreSQL client tools, set INVESTIQ_PG_BIN_DIR, "
                          "or set INVESTIQ_PG_TOOLS_MODE=docker when PostgreSQL runs in Docker Compose.")
    return [exe, "-h", url.host or "127.0.0.1", "-p", str(url.port or 5432), *conn, *args]


def _run(cmd: list[str], env: dict[str, str], *, stdin=None, stdout=None, timeout: int = 3600) -> None:
    proc = subprocess.run(cmd, env=env, stdin=stdin, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[:500] if proc.stderr else ""
        raise BackupError(f"{Path(cmd[0]).name} failed ({proc.returncode}): {err}")


def _pg_dump(settings: Settings, engine: Engine, dest: Path) -> None:
    url = engine.url
    with dest.open("wb") as out:
        _run(_pg_cmd(settings, "pg_dump", url, ["--format=custom", "--no-owner", "--no-privileges", url.database]),
             _pg_env(url), stdout=out)


# ------------------------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------------------------


def create_backup(session: Session, engine: Engine, *, reason: str = "scheduled", settings: Settings | None = None
                  ) -> BackupRecord:
    settings = settings or get_settings()
    out_dir = Path(settings.backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")  # unique: a backup never overwrites another
    counts = row_counts(engine)
    if engine.dialect.name == "postgresql":
        dest, method = out_dir / f"investiq-{stamp}.dump", "pg_dump"
        if dest.exists():
            raise BackupError(f"{dest} already exists")
        _pg_dump(settings, engine, dest)
    elif engine.dialect.name == "sqlite":
        src_path = engine.url.database
        if not src_path or src_path == ":memory:":
            raise BackupError("in-memory SQLite databases cannot be backed up")
        dest, method = out_dir / f"investiq-{stamp}.sqlite3", "sqlite_backup"
        src, dst = sqlite3.connect(src_path), sqlite3.connect(dest)
        try:
            src.backup(dst)
            # A self-contained file: opening a WAL-mode copy would leave -wal/-shm files beside it.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
            src.close()
    else:
        raise BackupError(f"unsupported database dialect {engine.dialect.name}")
    _restrict(dest)
    manifest = {"created_at": stamp, "method": method, "reason": reason, "row_counts": counts,
                "sha256": _sha256(dest), "size_bytes": dest.stat().st_size}
    (dest.with_suffix(dest.suffix + ".json")).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    rec = BackupRecord(path=str(dest), method=method, size_bytes=manifest["size_bytes"], sha256=manifest["sha256"],
                       row_counts=counts, status="created", verification={"reason": reason})
    session.add(rec)
    session.flush()
    audit(session, "backup.created", entity_type="backup", entity_id=rec.id, path=str(dest), size=rec.size_bytes)
    return rec


def verify_backup(session: Session, rec: BackupRecord, settings: Settings | None = None) -> BackupRecord:
    """Checksum plus a structural read of the archive. Does not modify any database."""
    settings = settings or get_settings()
    path = Path(rec.path)
    result: dict[str, Any] = {**(rec.verification or {}), "checked_at": datetime.now(UTC).isoformat()}
    try:
        if not path.exists():
            raise BackupError("backup file is missing")
        if _sha256(path) != rec.sha256:
            raise BackupError("checksum mismatch: the file changed or is corrupt")
        if rec.method == "sqlite_backup":
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise BackupError(f"sqlite integrity_check: {ok}")
        elif rec.method == "pg_dump" and settings.pg_tools_mode == "local":
            url = make_url(settings.database_url)
            exe = str(Path(settings.pg_bin_dir) / "pg_restore") if settings.pg_bin_dir else "pg_restore"
            if shutil.which(exe) or Path(exe).exists():
                _run([exe, "--list", str(path)], _pg_env(url))
        result.update(checksum="ok", structure="ok")
        rec.status = "verified"
        rec.verified_at = datetime.now(UTC)
    except (BackupError, sqlite3.Error, OSError) as exc:
        result.update(error=str(exc))
        rec.status = "failed"
    rec.verification = result
    session.flush()
    return rec


def restore_test(session: Session, engine: Engine, rec: BackupRecord, settings: Settings | None = None
                 ) -> dict[str, Any]:
    """Restore into a NEW temporary database, compare row counts with the manifest, then drop
    only that temporary database. The live database is never written to."""
    settings = settings or get_settings()
    report: dict[str, Any] = {"backup_id": rec.id, "started_at": datetime.now(UTC).isoformat()}
    if rec.method == "sqlite_backup":
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "restore.sqlite3"
            shutil.copyfile(rec.path, copy)
            eng = create_engine(f"sqlite:///{copy}")
            try:
                restored = row_counts(eng)
            finally:
                eng.dispose()
    elif rec.method == "pg_dump":
        restored = _pg_restore_test(settings, engine, Path(rec.path))
    else:
        raise BackupError(f"unknown backup method {rec.method}")
    mismatches = {t: {"expected": n, "restored": restored.get(t)} for t, n in rec.row_counts.items()
                  if restored.get(t) != n}
    report.update(tables=len(restored), mismatches=mismatches, ok=not mismatches)
    rec.verification = {**(rec.verification or {}), "restore_test": report}
    if not mismatches:
        rec.restore_tested_at = datetime.now(UTC)
    else:
        rec.status = "failed"
    session.flush()
    audit(session, "backup.restore_tested", entity_type="backup", entity_id=rec.id, ok=not mismatches)
    return report


def _pg_restore_test(settings: Settings, engine: Engine, path: Path) -> dict[str, int]:
    url = engine.url
    temp_db = f"investiq_restore_test_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{temp_db}"'))  # name is generated above, never user input
        try:
            args = ["--no-owner", "--no-privileges", "--exit-on-error", "-d", temp_db]
            if settings.pg_tools_mode == "docker":
                with path.open("rb") as f:
                    _run(_pg_cmd(settings, "pg_restore", url, args), _pg_env(url), stdin=f)
            else:
                _run(_pg_cmd(settings, "pg_restore", url, [*args, str(path)]), _pg_env(url))
            restored_engine = create_engine(url.set(database=temp_db))
            try:
                return row_counts(restored_engine)
            finally:
                restored_engine.dispose()
        finally:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_db}" WITH (FORCE)'))
    finally:
        admin.dispose()


def disk_usage(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    d = Path(settings.backup_dir)
    files = sorted(p for p in d.glob("investiq-*") if p.suffix in (".dump", ".sqlite3")) if d.exists() else []
    return {"directory": str(d), "count": len(files), "total_bytes": sum(p.stat().st_size for p in files),
            "oldest": files[0].name if files else None, "newest": files[-1].name if files else None,
            "note": "Old backups are never deleted automatically. Remove files manually if space is needed."}


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(v: Any) -> Any:
    """Text from outside sources (news headlines, notes) must not run as a spreadsheet formula."""
    if isinstance(v, dict | list):
        v = json.dumps(v, default=str)
    if isinstance(v, str) and v.startswith(FORMULA_PREFIXES):
        return "'" + v
    return v


def export_data(engine: Engine, dest_dir: Path, tables: list[str] | None = None) -> Path:
    """Write every table (or a subset) as CSV into one zip file the owner can open in a spreadsheet."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"investiq-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    wanted = [t for t in Base.metadata.sorted_tables if tables is None or t.name in tables]
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf, engine.connect() as conn:
        for table in wanted:
            buf = io.StringIO()
            w = csv.writer(buf)
            cols = [c.name for c in table.columns]
            w.writerow(cols)
            for row in conn.execute(select(table)).yield_per(5000):
                w.writerow([_csv_cell(v) for v in row])
            zf.writestr(f"{table.name}.csv", buf.getvalue())
        zf.writestr("README.txt", "InvestIQ data export. One CSV per table; JSON columns are JSON-encoded. "
                                  "Timestamps are UTC. Text starting with = + - @ is prefixed with ' so "
                                  "spreadsheets never run it as a formula.\n")
    _restrict(out)
    return out
