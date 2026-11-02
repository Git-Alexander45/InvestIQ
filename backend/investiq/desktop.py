"""Windows desktop launcher: what ``InvestIQ.exe`` and ``InvestIQ-Background.exe`` run.

``InvestIQ.exe`` (console window): on first start creates the owner's private folder
(``%LOCALAPPDATA%\\InvestIQ``) with a ``.env`` holding a random API token and a built-in SQLite
database, applies migrations (after a verified backup when data exists), loads the starter data,
registers the hourly "InvestIQ\\Daily Research" task, starts the local API and dashboard on
127.0.0.1 and opens the browser. Closing the window stops InvestIQ.

``InvestIQ-Background.exe`` (no window): what the scheduled task runs. It runs the research cycle
only when it is due (catching up missed days) and takes the daily backup when it is due.

The environment must be prepared before ``investiq.config`` is imported, because the settings
read ``INVESTIQ_ENV_FILE`` when the module loads; that is why imports here are deferred.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = "InvestIQ"
API_PORT = 8765
DASHBOARD_PORT = 3000
DASHBOARD_URL = f"http://127.0.0.1:{DASHBOARD_PORT}/"
TASK_NAME = r"InvestIQ\Daily Research"


def bundle_dir() -> Path:
    """Folder holding the bundled dashboard and Node.js (PyInstaller's _internal when frozen)."""
    if os.environ.get("INVESTIQ_BUNDLE_DIR"):
        return Path(os.environ["INVESTIQ_BUNDLE_DIR"])
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def app_home() -> Path:
    if os.environ.get("INVESTIQ_HOME"):
        return Path(os.environ["INVESTIQ_HOME"])
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / APP if base else Path.home() / ".investiq"


def _restrict(path: Path) -> None:
    if os.name == "nt":
        user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(M)", "*S-1-5-18:(F)",
                        "*S-1-5-32-544:(F)"], capture_output=True, check=False)
    else:
        path.chmod(0o600)


ENV_TEMPLATE = """\
# InvestIQ settings for this computer (created on first start; keep it private).
# Add your keys after the "=" signs, save, then close and reopen InvestIQ.
# Owner preferences (research time, AI budget, risk limits, email address) are in the dashboard.
INVESTIQ_ENV=production
INVESTIQ_DATABASE_URL=sqlite:///{db}
INVESTIQ_DATA_DIR={data}
INVESTIQ_BACKUP_DIR={backups}
INVESTIQ_OUTBOX_DIR={outbox}
INVESTIQ_API_HOST=127.0.0.1
INVESTIQ_API_PORT={api_port}
INVESTIQ_API_TOKEN={token}
INVESTIQ_FRONTEND_ORIGIN=http://127.0.0.1:{dash_port}

# Market data (needed for real research; see docs/DATA_SOURCES.md)
INVESTIQ_FMP_API_KEY=
INVESTIQ_TWELVEDATA_API_KEY=
# SEC EDGAR: "InvestIQ personal research you@example.com"
INVESTIQ_SEC_USER_AGENT=

# AI analysis (optional; spending is capped by the monthly budget in Settings)
ANTHROPIC_API_KEY=

# Email reports (optional; otherwise reports are saved in the outbox folder)
INVESTIQ_EMAIL_FROM=
INVESTIQ_RESEND_API_KEY=
INVESTIQ_SMTP_HOST=
INVESTIQ_SMTP_PORT=587
INVESTIQ_SMTP_USERNAME=
INVESTIQ_SMTP_PASSWORD=
"""


def ensure_home(home: Path) -> Path:
    """Create the private folder and .env on first start. An existing .env is never changed."""
    for sub in ("data", "backups", "outbox"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    env_file = home / ".env"
    if not env_file.exists():
        env_file.write_text(ENV_TEMPLATE.format(
            db=(home / "data" / "investiq.sqlite3").as_posix(), data=home / "data", backups=home / "backups",
            outbox=home / "outbox", api_port=API_PORT, dash_port=DASHBOARD_PORT, token=secrets.token_urlsafe(32),
        ), encoding="utf-8")
        _restrict(env_file)
    return env_file


def read_env(env_file: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - loopback URLs only
            return r.status < 500
    except Exception:  # noqa: BLE001 - any failure means "not up yet"
        return False


def _wait(url: str, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _http_ok(url):
            return True
        time.sleep(0.5)
    return False


def register_task(background_exe: Path) -> str:
    """Hourly check while the owner is logged on; each run does work only when the cycle is due."""
    if os.name != "nt":
        return "skipped (not Windows)"
    proc = subprocess.run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "HOURLY",
                           "/TR", f'"{background_exe}"'], capture_output=True, text=True, check=False)
    return "registered" if proc.returncode == 0 else f"not registered: {(proc.stderr or proc.stdout).strip()}"


def prepare(home: Path) -> dict[str, str]:
    env_file = ensure_home(home)
    os.environ["INVESTIQ_ENV_FILE"] = str(env_file)
    from investiq.config import get_settings, reset_settings_cache
    from investiq.logging_setup import configure_logging

    reset_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level, str(Path(settings.data_dir) / "logs" / "investiq.log"))
    return read_env(env_file)


def setup_database() -> None:
    from investiq.cli import cmd_bootstrap

    rc = cmd_bootstrap(argparse.Namespace(no_backup=False))
    if rc:
        raise RuntimeError(f"database setup failed (code {rc}); see the log in the data folder")


class Running:
    """The API (in a thread) and the dashboard (bundled Node.js) for one session."""

    def __init__(self, env: dict[str, str], log_dir: Path) -> None:
        import uvicorn

        from investiq.api.app import create_app

        self.server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=API_PORT,
                                                    log_level="warning", server_header=False, proxy_headers=False))
        self.api_thread = threading.Thread(target=self.server.run, name="investiq-api", daemon=True)
        self.env, self.log_dir, self.node = env, log_dir, None

    def start(self) -> None:
        self.api_thread.start()
        if not _wait(f"http://127.0.0.1:{API_PORT}/api/health", 60):
            raise RuntimeError("the InvestIQ API did not start")
        root = bundle_dir()
        node = root / "node" / ("node.exe" if os.name == "nt" else "node")
        server_js = root / "dashboard" / "server.js"
        if not node.exists() or not server_js.exists():
            raise RuntimeError(f"dashboard files are missing from {root}; reinstall InvestIQ")
        child_env = {**os.environ, "PORT": str(DASHBOARD_PORT), "HOSTNAME": "127.0.0.1", "NODE_ENV": "production",
                     "INVESTIQ_API_URL": f"http://127.0.0.1:{API_PORT}",
                     "INVESTIQ_API_TOKEN": self.env.get("INVESTIQ_API_TOKEN", "")}
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = (self.log_dir / "dashboard.log").open("ab")
        self.node = subprocess.Popen([str(node), str(server_js)], cwd=server_js.parent, env=child_env,  # noqa: S603
                                     stdout=log, stderr=subprocess.STDOUT)
        if not _wait(DASHBOARD_URL, 60):
            raise RuntimeError(f"the dashboard did not start; see {self.log_dir / 'dashboard.log'}")

    def stop(self) -> None:
        if self.node and self.node.poll() is None:
            self.node.terminate()
            try:
                self.node.wait(10)
            except subprocess.TimeoutExpired:
                self.node.kill()
        self.server.should_exit = True
        self.api_thread.join(10)


def smoke_check(token: str) -> list[str]:
    """Checks the installed app end to end: API, dashboard page, and dashboard -> API proxy."""
    problems = []
    if not _http_ok(f"http://127.0.0.1:{API_PORT}/api/health"):
        problems.append("API health check failed")
    if not _http_ok(DASHBOARD_URL):
        problems.append("dashboard page failed")
    try:
        with urllib.request.urlopen(f"{DASHBOARD_URL}api/iq/status", timeout=10) as r:  # noqa: S310
            if r.status != 200:
                problems.append(f"dashboard proxy returned {r.status}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"dashboard proxy failed: {exc}")
    if not token:
        problems.append("no API token in .env")
    return problems


def run_app(smoke_test: bool = False) -> int:
    home = app_home()
    print(f"{APP}: starting (data folder: {home})")
    if not smoke_test and _http_ok(DASHBOARD_URL) and _http_ok(f"http://127.0.0.1:{API_PORT}/api/health"):
        print(f"{APP} is already running; opening the dashboard.")
        webbrowser.open(DASHBOARD_URL)
        return 0
    env = prepare(home)
    print("Checking the database (a verified backup is taken before any upgrade)...")
    setup_database()
    if not smoke_test:
        exe_dir = Path(sys.executable).parent
        print(f"Daily research task: {register_task(exe_dir / 'InvestIQ-Background.exe')}")
    running = Running(env, home / "data" / "logs")
    try:
        running.start()
        if smoke_test:
            problems = smoke_check(env.get("INVESTIQ_API_TOKEN", ""))
            print("SMOKE TEST " + ("PASSED" if not problems else "FAILED: " + "; ".join(problems)))
            return 0 if not problems else 1
        webbrowser.open(DASHBOARD_URL)
        print(f"\n{APP} is running at {DASHBOARD_URL}")
        print(f"Your keys and settings file: {home / '.env'}")
        print("Keep this window open while you use InvestIQ. Close it (or press Ctrl+C) to stop.\n")
        while running.api_thread.is_alive() and (running.node is None or running.node.poll() is None):
            time.sleep(1)
        print(f"{APP} stopped unexpectedly; see the logs in {home / 'data' / 'logs'}.")
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        running.stop()


def run_background() -> int:
    """Scheduled task entry point: research cycle and backup only when due. Never opens a window."""
    prepare(app_home())
    from investiq.db.session import get_session
    from investiq.services.jobs import run_due

    setup_database()
    s = get_session()
    try:
        run_due(s)
    finally:
        s.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog=APP)
    p.add_argument("--background", action="store_true", help="run due research and backups, then exit")
    p.add_argument("--smoke-test", action="store_true", help="start, check every part, then exit")
    args = p.parse_args(argv)
    try:
        return run_background() if args.background else run_app(smoke_test=args.smoke_test)
    except Exception as exc:  # noqa: BLE001 - show a readable message instead of a traceback window
        import logging

        logging.getLogger(__name__).exception("InvestIQ failed to start")
        print(f"\n{APP} could not start: {exc}")
        if not args.background and not args.smoke_test and sys.stdin and sys.stdin.isatty():
            input("Press Enter to close this window.")
        return 1


def background_main() -> int:
    # The windowless build has no console: give print() and logging somewhere harmless to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    return main(["--background"])
