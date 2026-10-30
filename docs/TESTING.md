# Testing

All tests use synthetic data. Production reports never use fabricated data: the synthetic provider
is refused when `INVESTIQ_ENV=production`.

## Commands

```bash
# Backend (from backend/, with the virtual environment active)
python -m pytest                                    # SQLite in memory (fast)
INVESTIQ_TEST_DATABASE_URL=postgresql+psycopg://investiq:PASSWORD@localhost:5432/investiq_test \
  python -m pytest                                  # PostgreSQL: also runs triggers, migrations, pg_dump/pg_restore
ruff check investiq tests                           # lint, including flake8-bandit security rules
pip-audit --skip-editable                           # dependency vulnerabilities

# Dashboard (from frontend/)
npm test                                            # proxy and formatting unit tests (node --test)
npm run typecheck
npm run build
npm audit
node tests/screens.cjs                              # optional: screenshots of every page (needs running servers)
```

On Windows PowerShell, set the PostgreSQL URL with
`$env:INVESTIQ_TEST_DATABASE_URL = "postgresql+psycopg://..."` before `python -m pytest`.
The PostgreSQL test database is dropped and recreated by the tests: never point it at the real
InvestIQ database.

## What is covered

130 backend tests and 6 dashboard tests. Each area the specification lists has tests:

| Spec area | Tests |
|---|---|
| Financial calculations | `test_finance.py`: total return, CAGR, drawdown, volatility, Sharpe, beta, correlation, win rate, SMA/EMA/RSI/MACD/Bollinger, resampling, derived fundamentals |
| Scoring | `test_scoring.py`: grade bands, baseline weights match the spec, evidence, missing data cannot produce a high grade, model selection, ETF criteria, leveraged products avoided, assessments, leaderboards |
| ETF overlap | `test_overlap_diversification.py`: pairwise overlap, look-through hidden concentration, effective number and HHI |
| Portfolio allocations | `test_overlap_diversification.py`, `test_paper.py`: position limits, sector caps, what-if rejects concentrating additions |
| Currency conversion | `test_finance.py` (conversion, crosses, latest rate), `test_paper.py` (FX fee and recorded rate) |
| Data validation | `test_data_pipeline.py`: invalid bars, outliers, staleness, discrepancies, never-overwrite, point-in-time fundamentals, append-only guard |
| Data providers | `test_data_providers.py`: FMP, Twelve Data, SEC, Bank of Canada, RSS/Atom (XXE-safe), HTTP retries |
| AI response validation | `test_ai.py`: strict schemas, invalid output, refusals, provider errors, citation checks |
| API spending controls | `test_ai.py`: hard limit, pause when spent, premium reserve, never raised automatically, fallback pricing, daily usage |
| Database migrations | `test_cli_jobs.py::test_migrations_match_models` (migrations equal the models), PostgreSQL trigger tests |
| Backup restoration | `test_backup.py`: backup, checksum, tamper detection, restore test into a temporary database, never auto-deleted, export, Docker mode keeps the password off the command line |
| Paper trading | `test_paper.py`: next-open fills with slippage, no lookahead, FX fees, unverified candidates not bought, sector caps, sells, realized P&L, splits |
| Dividend calculations | `test_paper.py`: US withholding in TFSA vs RRSP, DRIP; `test_learning.py`: dividends in prediction returns |
| Benchmark comparisons | `test_paper.py`: benchmark buy-and-hold, excess return on common dates only; `test_learning.py` |
| Scheduling | `test_cycle.py`: due logic in Toronto time across DST, catch-up after sleep, same day never twice, stale and concurrent runs, attempt limit; `test_cli_jobs.py`: scheduler survives errors, backup job |
| Email delivery | `test_notify.py`: outbox `.eml`, missing recipient, retries, SMTP STARTTLS, Resend |
| Windows notifications | `test_notify.py`: toast payload encoded (no command injection), Windows-only, failures reported, notification centre |
| Security controls | `test_api.py`: token required, untrusted host rejected, security headers, safe errors, no secrets in status, budget increase needs confirmation, synthetic refused in production, export path traversal; `test_cli_jobs.py`: loopback-only serve; `test_mcp.py`: exactly the 11 read-only tools, writes rejected; dashboard `tests/proxy.test.mjs`: path validation, DNS rebinding and cross-site rejection |
| Full pipeline | `test_cycle.py::test_full_cycle_on_synthetic_data`, `test_api.py` research endpoints after a cycle, `test_mcp.py` tools after a cycle |

## Results (2026-10-30)

| Suite | Result |
|---|---|
| Backend on SQLite | 130 passed |
| Backend on PostgreSQL 16 | 130 passed |
| Dashboard unit tests | 6 passed |
| Dashboard typecheck and production build | passed (25 routes) |
| PowerShell scripts | parsed without errors; helper functions, `run-cycle.ps1` and `backup.ps1` exercised with PowerShell 7.6 on Linux using a stand-in CLI |
| `pip-audit`, `npm audit`, `ruff` | clean |

## Performance

Measured in the Linux build container (4 vCPU) with the full 128-instrument starter universe on
synthetic data, no AI key.

| Operation | SQLite | PostgreSQL 16 |
|---|---|---|
| Daily cycle, first day (backfills history for 128 instruments) | 83 s | 92 s |
| Daily cycle, following day | 62 s | 65 s |
| Backup + verification + restore test into a temporary database | 1.6 s | 4.8 s |
| Database size after two cycles | 55 MB | 58 MB (pg_dump file 11 MB) |

Both cycles finished `succeeded_degraded` as expected (no AI key, no news provider, RSS hosts
blocked in the build environment). With real providers the cycle time is dominated by provider
rate limits rather than computation.

API response times on the demo database (median of 5 local requests, warm):

| Endpoint | Time |
|---|---|
| `GET /api/dashboard` (overview) | 0.17 s |
| `GET /api/leaderboards` | 0.11 s |
| `GET /api/screener?kind=all` | 0.10 s |
| `GET /api/instruments/{id}/bars?range=MAX` with SMA50/200, RSI, MACD, Bollinger (1,568 bars) | 0.09 s |
| `GET /api/diversification` | 0.08 s |
| `GET /api/market/overview` | 0.07 s |
| `GET /api/paper` | 0.03 s |
| search, news, TFSA, prediction summary, instrument detail | under 0.02 s |

These are comfortably inside the needs of a single-user dashboard. The research cycle is a daily
background job, so its duration matters only for catch-up after long absences.
