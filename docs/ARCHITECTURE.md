# InvestIQ Architecture

InvestIQ is a single-owner, local-first application. Everything runs on the owner's Windows
computer: a PostgreSQL database in Docker, a Python backend, and a Next.js dashboard. Nothing is
reachable from the network; the only outbound traffic is to data providers, the AI provider and
the owner's email provider.

```
 Browser (127.0.0.1:3000)
   │  same-origin requests, no token
   ▼
 Next.js dashboard  ──(server-side proxy /api/iq/*, adds API token)──►  FastAPI (127.0.0.1:8765)
                                                                         │
     Windows Task Scheduler ── run-cycle.ps1 ── investiq CLI ───────────┤
     Claude (MCP client) ───── investiq mcp (stdio, read-only) ─────────┤
                                                                         ▼
                                              PostgreSQL 16 + TimescaleDB (Docker, 127.0.0.1:5432)
                                                                         ▲
     Data providers (FMP, Twelve Data, SEC EDGAR, Bank of Canada, RSS) ──┘  via investiq.data
     Anthropic API ─────────────────────────────────────────────────────── via investiq.ai.router
```

## Layers (backend/investiq)

| Layer | Package | Responsibility |
|---|---|---|
| Configuration | `config.py`, `services/preferences.py` | Infrastructure settings and secrets from `.env`; owner preferences as versioned database records. |
| Database | `db/`, `models/`, `backend/migrations/` | SQLAlchemy 2 models, Alembic migrations, append-only history protection. |
| Data | `data/` | Provider adapters (`providers/`), registry, ingestion, validation (outliers, staleness, cross-provider discrepancies), point-in-time repository. |
| Financial engine | `finance/`, `scoring/`, `diversification/`, `tfsa/` | Deterministic Python: returns, risk, indicators, FX, fundamentals, ETF look-through overlap, scores, grades, assessments, leaderboards, diversification and TFSA rules. |
| AI orchestration | `ai/` | Model router with a hard CAD budget, pricing table, evidence packs and citation checks, structured output validation, agent roles (news, analyst, reviewer, risk, chief analyst). Prompts live in `ai/prompts/`. |
| Research pipeline | `research/` | The daily 19-step cycle, locking and catch-up, report generation. |
| Paper trading | `paper/` | Order planning, next-open fills with slippage and FX fees, dividends with withholding, splits, benchmarks, snapshots and performance. |
| Learning | `learning/` | Prediction checkpoints (7/30/90/180/365 days), strategy versions (frozen baseline, experimental, production), walk-forward backtests with out-of-sample validation. |
| Notifications | `notify/` | Email (Resend, SMTP or outbox `.eml` files) and Windows toast notifications, with a notification centre and de-duplication. |
| Services | `services/` | Backup and restore tests, scheduler and job runs, health, alerts, audit log, owner portfolio views, bootstrap. |
| Interfaces | `api/`, `cli.py`, `mcp_server.py` | Local REST API, command line, read-only MCP server. |

The frontend (`frontend/`) is a Next.js App Router application. Pages call the backend only
through `/api/iq/[...path]`, a server-side route that validates the path (`lib/proxyPath.ts`) and
adds the API token, so the token never reaches the browser. Charts use TradingView Lightweight
Charts 5.

## Daily research cycle

`research/cycle.py` runs these steps in order. Each step is recorded with its status, timing and
notes; optional steps degrade the cycle instead of failing it.

1. collect_market_data (required) · 2. collect_company_news · 3. collect_economic_political_news ·
4. check_data_quality (required) · 5. deduplicate_news · 6. classify_developments ·
7. identify_affected_securities · 8. analyse_etf_holdings · 9. quantitative_screening ·
10. shortlist_candidates · 11. ai_deep_analysis · 12. challenge_theses · 13. portfolio_fit ·
14. rank_and_recommend · 15. update_watchlists · 16. update_paper_trading · 17. save_results ·
18. generate_report · 19. send_email

Statuses: `succeeded`, `succeeded_degraded` (with reasons such as "no AI key" or "RSS unreachable"),
`failed`. A day counts as done when it succeeded or succeeded degraded.

**Scheduling and recovery.** The cycle is due when the owner's research time (default 18:00
America/Toronto, set in the dashboard) has passed and that day is not done. `run-cycle --if-due` is
idempotent: the Windows task calls it hourly and at logon, and the API server runs the same
due-check every minute. A missed day is caught up when the computer is next on. Concurrency is
controlled by a unique (cycle_date, kind, attempt) row; a run whose heartbeat is older than 45
minutes is treated as stale; a day is attempted at most 3 times.

## Scoring and assessments

Each instrument is scored by the model for its asset class (equity, equity ETF, fixed income,
commodity, cash equivalent). Category weights are in `scoring/strategy_config.py`; the equity
weights are those of the master specification. A category without data scores a neutral 50 and
lowers coverage and confidence, so thin data cannot produce a high grade.

Assessments: BUY needs an overall score of at least 80, adequate valuation, risk, coverage and
confidence, **and** availability VERIFIED at both Wealthsimple and Questrade. Otherwise strong
candidates are WATCH. Holdings can be HOLD or SELL. AI can only make an assessment more cautious,
never less.

## Data integrity

* Historical tables are append-only. An ORM `before_flush` guard rejects updates and deletes
  (except columns listed in `__mutable_columns__`, such as a cycle's status) and PostgreSQL
  triggers from migration 0002 enforce the same rules in the database.
* Point in time: every fact carries `as_of`; backtests and paper fills only see data available at
  the decision time; fills happen at the next bar's open; delisted instruments stay in history.
* Prices are never invented. Missing data is reported as missing.

## Storage and backups

PostgreSQL 16 with TimescaleDB runs in Docker on a named volume. Backups use `pg_dump` (custom
format) inside the container, are checksummed (SHA-256) with a JSON manifest, verified, and
optionally restored into a temporary database to prove they work. Backups are never deleted
automatically. Migrations run only after a verified backup.

## Why this shape

See `docs/DECISIONS.md` for the reasons behind these choices (no message broker, in-process
scheduler plus Windows task, append-only history, server-side proxy, and others).
