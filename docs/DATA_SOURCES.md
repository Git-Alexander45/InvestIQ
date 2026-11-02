# Data Sources

InvestIQ never invents prices or facts. Each stored value records its provider and `as_of` time.
When a source is not configured or fails, the research cycle is marked degraded with the reason,
and the dashboard shows the data date and source next to every price.

| Data | Provider | Configuration | Status |
|---|---|---|---|
| Daily prices (OHLCV), quotes | Financial Modeling Prep (`fmp`) | `INVESTIQ_FMP_API_KEY` | Adapter built and tested against recorded response shapes; live calls not yet verified (no key in the build environment). |
| Daily and intraday prices | Twelve Data (`twelvedata`) | `INVESTIQ_TWELVEDATA_API_KEY` | Adapter built and tested against recorded shapes; live calls not yet verified. Intraday charts are offered only when this provider is configured. |
| Fundamentals | FMP; SEC EDGAR company facts (US filers) | FMP key; `INVESTIQ_SEC_USER_AGENT` ("Name email") | Adapters built; SEC facts are stored point-in-time by filing date. |
| ETF holdings, sector and country weights | FMP | FMP key (holdings may need a paid plan) | Adapter built; used for look-through overlap. |
| Dividends and splits | FMP | FMP key | Adapter built; used by paper trading and prediction returns. |
| Company news | FMP | FMP key | Adapter built. Only headline, link, time and a short excerpt are stored. |
| Official economic and policy news | Public RSS/Atom feeds (`backend/investiq/seed/news_sources.yaml`) | none | Federal Reserve, Bank of Canada, ECB, US BLS, US SEC, US EIA, Statistics Canada. Feed URLs were not reachable from the build environment and must be confirmed on first run (see KNOWN_ISSUES). |
| USD/CAD and other FX | Bank of Canada Valet API | none | Adapter built; daily reference rates. A conservative fallback rate (preference) is used for the AI budget only, never for valuations. |
| AI analysis | Anthropic API | `ANTHROPIC_API_KEY` | Router, budget, structured outputs and citation checks tested with a fake provider; live calls not yet verified. Prices in `config/model_pricing.yaml`. |
| Email delivery | Resend or SMTP; outbox folder otherwise | `INVESTIQ_RESEND_API_KEY` or `INVESTIQ_SMTP_*`, `INVESTIQ_EMAIL_FROM` | Both senders tested with mocks; outbox works without configuration. |
| Brokerage availability | Owner verification (dashboard form or CSV import) | none | Never inferred. Wealthsimple and Questrade offer no public availability API, and InvestIQ never asks for brokerage credentials. |
| TFSA designated exchanges | Department of Finance Canada list | none | Encoded in `tfsa/rules.py` with its source URL; review periodically. |
| Synthetic data | `synthetic` | `INVESTIQ_ALLOW_SYNTHETIC_DATA=true` in development | Deterministic fixtures for development and tests only. Refused in production; the dashboard shows a banner while it is active. |

## Choosing providers

Providers are chosen in Settings → Market data (`price_provider`, `fundamentals_provider`,
`etf_holdings_provider`, `fx_provider`). The recommended low-cost setup is:

* FMP for prices, fundamentals, ETF holdings, dividends and company news (check which endpoints
  your plan covers, especially Canadian listings and ETF holdings);
* Bank of Canada for FX;
* SEC EDGAR as a free fundamentals cross-check for US companies;
* Twelve Data if you want intraday charts.

InvestIQ does not purchase subscriptions. Choosing and paying for a plan is the owner's decision;
record external costs on the Costs page so they appear next to AI spending.

## Data quality rules

* Bars with impossible values (negative or zero prices, high below low, close outside the range)
  are dropped and recorded as data issues; single-day moves beyond a threshold are flagged.
* Prices older than `stale_after_days` (default 4) are marked stale and cannot support a BUY.
* When two providers disagree by more than `discrepancy_tolerance_pct` (default 1%), the
  discrepancy is recorded and shown.
* Stored bars are never overwritten; corrections are new versions.

## Licences and terms

Use each provider within its terms (personal, non-redistribution use). News items keep only a
headline, link and short excerpt. SEC EDGAR requires a descriptive User-Agent and fair access
(InvestIQ throttles requests).
