# Known Issues, Limitations and External Dependencies

Read this at the start of every session. Remove an entry only when it has been resolved and tested.

## Needs the owner (external accounts and keys)

| Item | Effect until configured | How to resolve |
|---|---|---|
| No market data key (`INVESTIQ_FMP_API_KEY` or `INVESTIQ_TWELVEDATA_API_KEY`) | Research cycles run but are marked degraded/failed for missing prices; no prices are shown or invented. | Choose a provider plan (DATA_SOURCES.md) and add the key to `.env`. |
| No `ANTHROPIC_API_KEY` | AI steps (news assessment, deep analysis, reviewer, chief analyst) are skipped and the cycle is marked degraded; quantitative research still runs. | Add the key; the monthly budget in Settings applies. |
| No email provider | Reports go to `outbox\` as `.eml` files instead of email. | Configure Resend or SMTP in `.env` and the recipient in Settings. |
| Brokerage availability | No instrument can be BUY until it is verified at both Wealthsimple and Questrade, so paper portfolios A–D stay in cash at first. This is intended. | Verify investments on the Brokerage page (manual or CSV). |
| SEC EDGAR User-Agent | SEC fundamentals unavailable without `INVESTIQ_SEC_USER_AGENT`. | Set it to "InvestIQ personal research you@example.com". |

## Not yet verified against live services

The build environment could not reach the data providers or AI provider (network policy and no
keys). Everything below is implemented and tested against recorded response shapes, mocks and
synthetic data, but **has not been exercised live**:

* FMP, Twelve Data, SEC EDGAR, Bank of Canada adapters. Field names follow the providers' current
  documentation; the first live run should be watched for parsing errors (they are recorded as
  data issues, not silently ignored). FMP coverage of TSX symbols (`.TO` suffix) and ETF holdings
  depends on the plan.
* Official RSS/Atom feed URLs in `backend/investiq/seed/news_sources.yaml`. Any that fail are listed
  in the cycle's degraded reasons; update the URL in the seed file and re-run bootstrap.
* Anthropic API calls (structured outputs, effort settings, fallback pricing). Model prices in
  `config/model_pricing.yaml` were taken from published pricing on 2026-10-06 and must be
  re-checked periodically.
* Resend and SMTP delivery (tested with mocks; outbox delivery tested for real).
* Windows toast notifications (payload construction tested; the PowerShell toast itself only runs
  on Windows).

## Windows-specific items verified only partially

* The PowerShell scripts were parsed and their helper functions exercised with PowerShell 7 on
  Linux. Docker, Task Scheduler and `icacls` steps can only run on Windows and should be checked
  on the first install.
* Backups in Docker mode (`docker compose exec pg_dump`) are unit-tested for the command line but
  were run for real only in local mode (PostgreSQL client tools on PATH).

## Functional limitations

* The TFSA designated stock exchange list is encoded from the Department of Finance page and needs
  periodic review.
* Corporate actions other than cash dividends and splits (spin-offs, mergers, return of capital)
  are not simulated in paper trading; affected positions should be reviewed manually.
* Mutual funds are supported in the data model and scoring, but providers rarely cover Canadian
  mutual funds; most will show missing data.
* Intraday charts require Twelve Data; with daily-only providers the chart offers daily, weekly and
  monthly intervals only.
* Backtests use the stored price history; meaningful out-of-sample results need several years of
  history from a real provider.
* A desktop application wrapper (Tauri/Electron) is deferred (DECISIONS.md D16); the dashboard runs
  in the browser on 127.0.0.1.
* Backups are never deleted automatically, so disk usage grows; the Settings page shows the total.
