# Progress

## Last verified milestone (2026-10-30)

**Stages 0–9 complete and tested in the build environment.** All modules are integrated into one
product: the daily cycle feeds scores, assessments, reports, paper portfolios, predictions,
notifications, the dashboard and the MCP server. Verification: 130 backend tests pass on SQLite and
on PostgreSQL 16, dashboard unit tests, typecheck and production build pass, dependency audits are
clean (see TESTING.md).

What has **not** been verified yet (see KNOWN_ISSUES.md): live data providers, live AI calls and
live email (no keys and no network access to them during the build), and the Windows scripts on a
real Windows machine with Docker Desktop.

## Status by stage

### Stage 0 — Foundation ✔
CLAUDE.md, the verbatim master specification, documentation set, repository layout, commands.

### Stage 1 — Core application ✔
FastAPI backend bound to 127.0.0.1 with token auth, trusted hosts, CORS and safe errors;
SQLAlchemy models and two Alembic migrations (schema; PostgreSQL history-protection triggers and
optional TimescaleDB); versioned owner preferences; rotating file logs; health and status checks;
`investiq` command line (migrate, bootstrap, serve, run-cycle, backup, export, status, gen-token,
backtest, mcp); in-process scheduler; verified, restore-tested backups that are never deleted
automatically.

### Stage 2 — Data infrastructure ✔ (live calls pending keys)
Adapters for FMP, Twelve Data, SEC EDGAR, Bank of Canada and RSS/Atom; registry that degrades
gracefully when a key is missing; ingestion with bar validation, outlier and staleness flags,
cross-provider discrepancy checks; point-in-time repository; 128-instrument starter universe
across asset classes, regions and listings; deterministic synthetic provider for development.

### Stage 3 — Quantitative engine ✔
Returns, risk and technical indicators; FX conversion; derived fundamentals; asset-class scoring
models with the spec's equity weights; grades and assessments (BUY requires both brokerages
verified); leaderboards; ETF look-through overlap; diversification report and what-if; TFSA rules;
brokerage verification (manual and CSV) with expiry.

### Stage 4 — AI intelligence ✔ (live calls pending key)
Provider-independent router with low-cost, premium and reviewer tiers; hard CAD budget with
reservations, premium reserve and full request accounting; pricing table; constitution and agent
prompts (news researcher, stock and ETF analysts, reviewer, risk manager, chief analyst); evidence
packs and citation checks; strict structured outputs; AI can only make assessments more cautious.

### Stage 5 — Automation ✔
19-step daily cycle with per-step status and degraded reasons; due-check in the owner's time zone
with catch-up after sleep, stale-run takeover and attempt limit; HTML/text reports; email via
Resend, SMTP or outbox; Windows toast notifications; notification centre with preferences and
de-duplication; Windows Task Scheduler registration.

### Stage 6 — Paper trading ✔
Portfolios A–D with their policies plus benchmark portfolios; orders decided after the close and
filled at the next open with slippage, commissions and FX fees; dividends with withholding by
account type and DRIP; splits; daily snapshots; performance metrics and comparison with benchmarks.

### Stage 7 — Performance learning ✔
Predictions with checkpoints at 7/30/90/180/365 days including dividends and benchmark excess;
frozen baseline, experimental and production strategy versions; walk-forward backtests with an
out-of-sample split and no lookahead; promotion only with a passing backtest and explicit confirmation.

### Stage 8 — Dashboard ✔
Next.js dashboard with 22 sections (overview, markets, intelligence, stock and ETF screeners,
growth, undervalued, dividends, international, TFSA, portfolio, allocation, diversification, news,
reports, paper trading, strategy, predictions, watchlists, notifications, costs, settings,
brokerage) plus investment detail pages with interactive Lightweight Charts (intervals, ranges,
indicators); search; filters; schema-driven settings forms; server-side token proxy.
Read-only MCP server with the 11 specified tools.

### Stage 9 — Hardening ✔ (first Windows install to be confirmed)
Docker Compose for the database (loopback only, no socket, named volume); Windows PowerShell
scripts: install, start, stop, run-cycle, register-task, backup; security review (audits, secrets
scan, proxy DNS-rebinding and cross-site protection, CSV formula neutralisation, prompt-injection
guidance); performance measurements; complete documentation.

## Changelog

| Date | Milestone |
|---|---|
| 2026-10-30 | Stage 9: Windows scripts, Docker Compose, security fixes, performance tests, documentation |
| 2026-10-30 | Stage 8: dashboard (22 sections) and read-only MCP server |
| 2026-10-30 | Stage 1 completion: API, CLI, scheduler, backups, health |
| 2026-10-30 | Stages 5–7: research cycle, reports, paper trading, learning, notifications |
| 2026-10-30 | Stage 4: AI router, budget, prompts, evidence checks, agents |
| 2026-10-30 | Stages 1–3: schema, migrations, providers, scoring, diversification |
| 2026-10-30 | Stage 0: project instructions and master specification |
