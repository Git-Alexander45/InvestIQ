# Roadmap

Stages follow the master specification (MASTER_SPEC.md, "Development roadmap"). Status reflects
what is implemented **and tested**; see PROGRESS.md for details and KNOWN_ISSUES.md for what still
depends on external services.

| Stage | Scope | Status |
|---|---|---|
| 0 Foundation | Repository, documentation, architecture, structure, commands | Done |
| 1 Core application | FastAPI backend, Next.js frontend, PostgreSQL, Alembic migrations, settings, logging, health checks | Done |
| 2 Data infrastructure | Market data, fundamentals, ETF holdings, FX, news ingestion, validation | Done (live provider calls pending keys) |
| 3 Quantitative engine | Stock and ETF scoring, asset-class models, diversification, portfolio analytics, brokerage verification | Done |
| 4 AI intelligence | Model router, constitution, agent prompts, news/stock/ETF analysis, risk manager, chief analyst, evidence and citations, hard budget | Done (live AI calls pending key) |
| 5 Automation | Daily scheduling with catch-up, 19-step pipeline, recovery, email reports, Windows notifications | Done |
| 6 Paper trading | Portfolios A–D, simulated orders, dividends, benchmarks, performance analytics | Done |
| 7 Performance learning | Prediction tracking, strategy versions, walk-forward backtests, out-of-sample validation, frozen and experimental strategies | Done |
| 8 Dashboard | 22 sections, interactive charts, reports, search, filters, settings; read-only MCP server | Done |
| 9 Hardening | Automated tests, security review, performance testing, backup and recovery, Windows scripts, documentation | Done (first Windows install to be confirmed by the owner) |

## Next steps after the first install

1. Owner: install on Windows, add a market data key, run the first cycle, and report anything that
   fails (the scripts and live adapters have not yet run on the owner's machine).
2. Watch the first live cycles for provider parsing issues and feed URL failures; fix adapters.
3. Verify brokerage availability for the investments of interest so BUY assessments become possible.
4. Add the AI key and review the first AI analyses and their costs on the Costs page.
5. After several months of predictions, review the Strategy page and consider an experimental
   strategy version; promote only if it beats the frozen baseline out of sample.

## Later ideas (not committed)

* Desktop wrapper (Tauri) with a tray icon.
* More providers (for example a Canadian mutual fund source) behind the same adapter interface.
* Additional corporate action types in paper trading.
