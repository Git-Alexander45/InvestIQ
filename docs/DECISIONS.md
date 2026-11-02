# Technical Decisions

Each entry records what was decided and why. Do not reverse a decision without adding a new entry
that explains the reason.

## D1. Monolithic Python backend, no message broker
The spec allows Redis/Celery. A single owner running one daily cycle does not need a broker, and
Redis adds a service to install, secure and back up on Windows. Jobs run in the API process
(`services/jobs.py`) and through the Windows task (`run-cycle --if-due`). Database rows provide
locking. Revisit if parallel research across machines is ever needed.

## D2. Two schedulers that share one lock
Windows Task Scheduler is the primary trigger because it survives reboots and runs when the
dashboard is closed. The API's in-process scheduler is a convenience when the server is running.
Both call the same idempotent due-check, and the unique (cycle_date, kind, attempt) row makes a
double start impossible.

## D3. Append-only history in two layers
The ORM guard catches mistakes early with a clear error; PostgreSQL triggers make the rule hold
even for raw SQL. Corrections are new rows (new versions), so the past is never rewritten.
Only status-tracking columns that describe an in-progress record are mutable.

## D4. Owner preferences live in the database, secrets in `.env`
Preferences change from the dashboard and need history (who changed the budget and when), so each
change is a new versioned record. Secrets never go in the database or the browser.

## D5. Server-side proxy for the dashboard
The browser talks to Next.js only. The Next.js server adds the API token, so the token never
reaches JavaScript running in the page, and the API can require it on every route except health.

## D6. asset_class versus security_type
`asset_class` is the underlying exposure (equity, fixed_income, commodity, cash_equivalent,
multi_asset); `security_type` is the vehicle (stock, etf, mutual_fund, ...). A gold ETF is a
commodity exposure held through an ETF. Diversification uses exposure; scoring picks the model by
both.

## D7. Neutral 50 for missing categories
Treating missing data as zero would punish instruments with incomplete coverage unfairly; treating
it as average without penalty would let thin data reach a high grade. Missing categories score 50
and reduce coverage and confidence, and BUY requires minimum coverage and confidence.

## D8. Weights outside the equity model are initial judgement
The spec gives equity weights only. The ETF, fixed income, commodity and cash models use weights
chosen by InvestIQ (in `scoring/strategy_config.py`). They are part of the frozen baseline and may
only change through an experimental strategy version that beats the baseline out of sample.

## D9. Predictions are recorded when the assessment changes
Recording every instrument every day would flood the evaluation with near-duplicate predictions.
A prediction is recorded the first time an instrument is assessed under a strategy, whenever its
assessment changes, and again when the same assessment still stands 90 days later. Each prediction
is checked at 7/30/90/180/365 days, including dividends and against a benchmark, and every
prediction is evaluated so results cannot be cherry-picked.

## D10. AI budget is a hard reservation in CAD
Before each AI call the router reserves the worst-case cost (input estimate plus maximum output)
converted to CAD with the Bank of Canada rate (or a conservative fallback). If the reservation
does not fit, the call is refused and recorded. The actual cost is settled afterwards. The limit
is never raised automatically; raising it through the API needs an explicit confirmation flag.
Models without a price in `config/model_pricing.yaml` are refused. A premium reserve can stop
expensive calls first. Server-side fallback models are priced so fallback usage is never
under-counted.

## D11. AI can only make assessments more cautious
Quantitative scores decide eligibility. AI interprets evidence and can lower an assessment (for
example BUY to WATCH) with cited reasons, but cannot raise one. Citations are checked against the
evidence pack given to the model.

## D12. Brokerage availability is never inferred
An exchange listing does not prove an instrument can be bought at Wealthsimple or Questrade.
Availability is VERIFIED only by the owner (manually or by CSV import), expires after a
configurable number of days, and BUY requires both brokerages verified.

## D13. Backups are never deleted automatically
Disk usage is reported in the dashboard, but deleting history needs explicit owner action.
Filenames include microseconds so two backups in the same second never overwrite each other.
Restore tests use a temporary database and drop it afterwards; the live database is untouched.

## D14. pg_dump inside the Docker container on Windows
Installing PostgreSQL client tools on Windows is an extra step that often goes wrong.
`INVESTIQ_PG_TOOLS_MODE=docker` runs `pg_dump`/`pg_restore` with `docker compose exec` and streams
the file through stdin/stdout. The password is passed through the environment, never the command
line. `local` mode remains for a native PostgreSQL install.

## D15. Synthetic data only in development
The synthetic provider is deterministic and covers every feature, so the whole pipeline is tested
without keys. It is refused when `INVESTIQ_ENV=production` or unless
`INVESTIQ_ALLOW_SYNTHETIC_DATA=true`, and the dashboard shows a banner whenever synthetic data is
in use.

## D16. Desktop app: installer plus browser dashboard (no Tauri/Electron)
Superseded on 2026-11-02 at the owner's request for "an exe to download and open". The Windows
app is a PyInstaller build of the backend with a bundled Node.js running the Next.js standalone
dashboard, packaged by Inno Setup as a per-user `InvestIQ-Setup.exe` (no administrator rights).
The dashboard still opens in the browser on 127.0.0.1; a native window wrapper (Tauri/Electron)
remains deferred because it adds a toolchain without changing what the owner can do.

## D17. Email through Resend, SMTP or outbox
Without credentials, reports are written as `.eml` files to the outbox folder so nothing is lost
and the owner can open them in any mail client. Resend and SMTP (STARTTLS) are supported when
configured.

## D18. Next.js 16 and Lightweight Charts 5
Current stable versions at the time of building. Lightweight Charts 5 uses the
`addSeries(SeriesDefinition, options, paneIndex)` API, which allows RSI and MACD panes under the
price chart without another library.

## D19. Provider call cap is a preference
Free tiers limit calls per day. `max_provider_calls_per_cycle` (default 600) protects quotas; the
first runs backfill history gradually. Synthetic data has no cap.

## D20. Built-in SQLite database in the Windows app
Chosen by the owner on 2026-11-02 (recommended option) so the installer needs nothing else
installed: no Docker, no PostgreSQL service. One owner's data volume fits SQLite easily, all tests
run on it, and migration 0003 adds the same history-protection triggers PostgreSQL has. The
Docker/PostgreSQL setup (scripts/windows, docker-compose.yml) stays supported for anyone who
prefers it; the code is the same.
