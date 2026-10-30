# Installing InvestIQ on Windows

InvestIQ runs entirely on your computer. Installation takes about 15 minutes, most of it
downloading. Nothing is purchased and nothing is exposed to the network.

## 1. Prerequisites

Install these once (all free):

| Software | Version | Where |
|---|---|---|
| Windows 10 or 11 | 64-bit | |
| Docker Desktop | current | https://www.docker.com/products/docker-desktop/ (runs the database) |
| Python | 3.12 or newer | https://www.python.org/downloads/windows/ — tick "Add python.exe to PATH" |
| Node.js | 20 LTS or newer | https://nodejs.org/ |
| Git | current | https://git-scm.com/download/win (to download and update InvestIQ) |

Start Docker Desktop once and let it finish starting before you continue.

## 2. Download

```powershell
cd $HOME
git clone https://github.com/Git-Alexander45/InvestIQ.git
cd InvestIQ
```

## 3. Install

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -RegisterTask
```

The installer:

1. checks the prerequisites;
2. creates `.env` from `.env.example` with a random database password and a random local API token,
   readable only by your Windows account (an existing `.env` is never overwritten);
3. starts the database container (PostgreSQL 16 + TimescaleDB, reachable from this computer only);
4. creates `backend\.venv` and installs the backend;
5. migrates the database (after a verified backup when data already exists) and loads the starter
   universe, portfolios A–D, benchmarks and the baseline strategy;
6. installs and builds the dashboard;
7. with `-RegisterTask`, registers the daily research task (see step 6).

Running it again is safe; it updates the installation and keeps your data and settings.

## 4. Start and open the dashboard

```powershell
scripts\windows\start.ps1 -Open
```

The dashboard is at http://127.0.0.1:3000. Stop everything with `scripts\windows\stop.ps1`
(add `-Database` to also stop the database container; your data is kept).

## 5. Configure (optional but needed for real research)

Edit `.env` in a text editor, then restart with `stop.ps1` and `start.ps1`.

| Setting | What it enables |
|---|---|
| `INVESTIQ_FMP_API_KEY` | Prices, fundamentals, ETF holdings, dividends, company news. **Without a price provider, research runs are recorded as degraded and no prices are shown.** |
| `INVESTIQ_TWELVEDATA_API_KEY` | Alternative price source and intraday charts. |
| `INVESTIQ_SEC_USER_AGENT` | Free US fundamentals from SEC EDGAR (format: `InvestIQ personal research you@example.com`). |
| `ANTHROPIC_API_KEY` | AI analysis. Spending is capped by the monthly budget in Settings (default 5 CAD). Without it, quantitative research still runs. |
| `INVESTIQ_RESEND_API_KEY` or `INVESTIQ_SMTP_*`, `INVESTIQ_EMAIL_FROM` | Daily email reports. Without them, reports are saved as `.eml` files in `outbox\`. |

Everything else (research time, budget, risk limits, email recipient, notification types,
universe, paper trading costs) is set in the dashboard under **Settings**. See
`docs/DATA_SOURCES.md` for provider details.

## 6. Daily research

The task **InvestIQ Daily Research** (Task Scheduler → InvestIQ) checks every hour and 5 minutes
after logon whether the day's research is due, using the research time from Settings (default
18:00 Toronto time, after the market close). If the computer was off or asleep, the missed day is
caught up when it is next on. It runs as you, only while you are logged on, and stores no
password.

* Register or update: `scripts\windows\register-task.ps1` (add `-WithServer` to also start the
  dashboard at logon)
* Remove: `scripts\windows\register-task.ps1 -Unregister`
* Run now: `scripts\windows\run-cycle.ps1` (does nothing if today is already done; `-Force` to rerun)
* Log: `data\logs\scheduled-YYYY-MM.log`

## 7. Verify brokerage availability

A BUY assessment requires that the investment is **verified** as available at both Wealthsimple
and Questrade. InvestIQ cannot check this itself and never asks for your brokerage login. On the
**Brokerage** page, mark investments as verified after checking them in each app, or import a CSV
(template on the same page). Verifications expire after 180 days by default.

## 8. Backups

A verified backup is taken automatically when the last one is more than 20 hours old, and before
every migration. To take one now and prove it restores:

```powershell
scripts\windows\backup.ps1            # add -Export for CSV files of every table
```

Backups are in `backups\` (with a `.json` manifest and SHA-256 checksum) and are **never deleted
automatically**. Copy them to another drive or a cloud folder you trust. To restore after a
disaster, see "Restoring a backup" below.

## 9. Updating InvestIQ

```powershell
scripts\windows\stop.ps1
git pull
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
scripts\windows\start.ps1
```

The installer backs up and verifies the database before applying any new migration.

## 10. Using InvestIQ from Claude (MCP, read-only)

Add this to your Claude Desktop configuration (`%APPDATA%\Claude\claude_desktop_config.json`),
adjusting the path:

```json
{
  "mcpServers": {
    "investiq": {
      "command": "C:\\Users\\YOU\\InvestIQ\\backend\\.venv\\Scripts\\investiq.exe",
      "args": ["mcp"]
    }
  }
}
```

The 11 tools are read-only: Claude can read research, news, portfolios and watchlists but cannot
trade, change holdings, change settings or spend the AI budget.

## Restoring a backup

Restoring replaces the live database, so it is a deliberate manual step:

1. Stop InvestIQ: `scripts\windows\stop.ps1`.
2. Take a fresh backup of the current state first if the database still works:
   `scripts\windows\backup.ps1`.
3. Restore the chosen file (replace the file name; user and database names are in `.env`):
   ```powershell
   docker cp backups\investiq-YYYYMMDDTHHMMSSffffffZ.dump investiq-db:/tmp/restore.dump
   docker compose exec -T db pg_restore -U investiq -d investiq --clean --if-exists --no-owner /tmp/restore.dump
   docker compose exec -T db rm /tmp/restore.dump
   ```
4. Start InvestIQ and check that your history is back (Overview, Reports, and the Backups panel on
   the Settings page).

## Troubleshooting

| Problem | Fix |
|---|---|
| "Docker is installed but not running" | Start Docker Desktop and wait until it says it is running. |
| Dashboard shows "INVESTIQ_API_TOKEN is not set" | Start it with `start.ps1`, which loads `.env`. |
| Dashboard shows "InvestIQ API is not reachable" | Check `data\logs\api.err.log`; run `backend\.venv\Scripts\investiq.exe status`. |
| Research runs are "degraded" | The reasons are listed on the Overview page and in the day's report; usually a missing key or an unreachable feed. |
| Port 5432 already in use | Set `INVESTIQ_DB_PORT` in `.env` (and the port in `INVESTIQ_DATABASE_URL`). |
| Scripts are blocked by execution policy | Run them with `powershell -ExecutionPolicy Bypass -File ...`, or `Unblock-File scripts\windows\*.ps1`. |
