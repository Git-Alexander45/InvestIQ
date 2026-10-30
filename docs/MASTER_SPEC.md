# InvestIQ — Master Specification

> This file preserves, verbatim, the complete master development prompt supplied by the owner on 2026-10-30.
> It is the authoritative statement of requirements. Do not edit the specification text below; record
> interpretations in `docs/DECISIONS.md` and status in `docs/PROGRESS.md`.

---

INVESTIQ — COMPLETE MASTER DEVELOPMENT PROMPT
You are responsible for designing, engineering, implementing, testing and delivering InvestIQ, a complete AI-powered investment research and portfolio intelligence platform.
Act as a senior software architect, full-stack developer, quantitative finance engineer, AI engineer, database architect, cybersecurity engineer and technical project manager.
Your mission is to build the complete application described below.
This is not a basic stock screener, a dashboard prototype or a tutorial project.
It is intended to become a serious long-term investment intelligence platform.
You have authorization to make reasonable technical decisions, create files, install appropriate dependencies, build modules, run tests and continue development independently.
Do not stop after creating a plan or documentation. Build the actual application.
Do not ask for approval after every development phase. Continue autonomously wherever possible.
However, never purchase subscriptions, spend money, deploy publicly, execute real financial transactions, expose private information or perform destructive operations without explicit authorization.
If a required API key or external service is unavailable, implement the integration safely, document the requirement and continue building the rest of the application.
==================================================

1. THE MISSION
==================================================

InvestIQ's primary objective is to help grow and compound the owner's investment portfolio through aggressive, diversified, evidence-based investing.
The software must continuously identify, investigate, evaluate and rank investment opportunities.
It must search for investments with strong potential for long-term growth while managing portfolio concentration and downside risk.
The objective is to maximize long-term total returns and risk-adjusted compounding.
InvestIQ must identify:

* Strong growth opportunities.
* Undervalued investments.
* High-quality companies.
* Emerging industries.
* Strong ETFs.
* Dividend growth opportunities.
* International investment opportunities.
* Attractive opportunities across different asset classes.

Never assume the best investment is necessarily a stock.
Never recommend something simply because it has recently performed well.
Never force a BUY recommendation.
WAIT is a valid outcome.
Never guarantee investment returns.
Operating system: Windows 10/11.
Application: Local-first Windows application.
Database: Local persistent database.
Primary display currency: CAD.
Secondary display currency: USD.
Brokerages:

* Wealthsimple.
* Questrade.

Research frequency: One comprehensive automated research cycle per day.
Default research time: 6:00 PM Eastern, configurable.
Daily email: Mandatory after successful completion of the research cycle.
Desktop notifications: Supported.
Initial operation: Research, analytics and paper trading only.
Real trading: Prohibited.
Initial AI API budget: $5 CAD per calendar month, with an enforceable hard spending limit.
All external service costs must be identified separately from AI token costs.
The application must remain useful if an AI provider or market-data provider becomes temporarily unavailable.
Build a modular, maintainable architecture.
Preferred stack:
FRONTEND:

* Next.js.
* React.
* TypeScript.
* Professional financial trading-terminal design.
* TradingView Lightweight Charts.

BACKEND:

* Python.
* FastAPI.
* Pydantic.
* Modular service architecture.

DATABASE:

* PostgreSQL.
* TimescaleDB where appropriate for historical time-series data.
* Persistent local storage.
* Database migrations.
* Automated backups.

BACKGROUND PROCESSING:

* Reliable scheduling and background jobs.
* Celery and Redis if justified.
* Windows Task Scheduler or another reliable Windows-compatible scheduling mechanism.
* Recovery after application restarts.

DEPLOYMENT:

* Docker Compose where useful.
* Windows-compatible installation scripts.
* Local operation without requiring cloud hosting.

Evaluate Tauri or another suitable Windows desktop shell after the core application works.
Do not prematurely add unnecessary technologies.
If you choose an alternative to the preferred stack, explain the decision in docs/DECISIONS.md.
Keep the frontend, backend, AI orchestration, financial engine and database separate.
InvestIQ must research multiple investment types.
INDIVIDUAL INVESTMENTS:

* Canadian stocks.
* American stocks.
* International stocks.
* Growth companies.
* Value companies.
* Dividend companies.
* Emerging companies.

ETFs:

* Broad-market ETFs.
* Growth ETFs.
* Technology ETFs.
* Sector ETFs.
* Dividend ETFs.
* International ETFs.
* Bond ETFs.
* Commodity ETFs.
* Gold and precious-metal ETFs.

OTHER ASSET CLASSES:

* Government bonds.
* Corporate bonds.
* Treasury bills.
* Cash equivalents.
* Gold.
* Silver.
* Selected commodities.
* Other legitimate investable assets.

Do not limit the software to North American markets.
Research opportunities across:

* Canada.
* United States.
* Europe.
* Asia.
* Emerging markets.

Exclude REITs from the default recommendation universe unless explicitly enabled by the owner.
The system must follow an aggressive but diversified long-term investment philosophy.
Prioritize:

* Strong revenue growth.
* Earnings growth.
* Free cash flow.
* Competitive advantages.
* Attractive valuations.
* Growing addressable markets.
* Industry expansion.
* Innovation.
* Strong management.
* Sustainable business models.
* Long-term total returns.

Investigate emerging industries, including:

* Artificial intelligence.
* Semiconductors.
* Robotics.
* Automation.
* Cybersecurity.
* Biotechnology.
* Healthcare technology.
* Energy.
* Nuclear technology.
* Infrastructure.
* Advanced manufacturing.
* Other emerging sectors.

These are research areas, not automatic investment preferences.
Evaluate both upside and downside.
Do not confuse a promising industry with a promising individual company.
Diversification is a core requirement.
The system must analyze:
ASSET CLASS:

* Equities.
* ETFs.
* Bonds.
* Commodities.
* Precious metals.
* Cash equivalents.

GEOGRAPHY:

* Canada.
* United States.
* Europe.
* Asia.
* Emerging markets.

SECTORS:

* Technology.
* Healthcare.
* Financials.
* Energy.
* Industrials.
* Consumer goods.
* Materials.
* Utilities.
* Communication services.
* Other relevant sectors.

Also measure:

* Currency exposure.
* Underlying ETF holdings.
* ETF overlap.
* Individual company concentration.
* Correlations.
* Volatility.
* Maximum drawdown.
* Factor exposure.

IMPORTANT:
Owning five ETFs does not automatically mean a portfolio is diversified.
For example, multiple funds can have substantial overlap in the same large technology companies.
The system must inspect underlying holdings whenever reliable information is available.
Create a portfolio-level diversification engine.
Every new investment must be evaluated for how it affects the existing portfolio.
A high-scoring investment may still be a poor portfolio addition if it creates excessive concentration.
Do not force allocations.
Cash can remain uninvested if attractive opportunities are unavailable.
Initial configurable risk guidelines:

* Individual stock positions: generally 5–8% maximum.
* Speculative positions: generally 1–3% maximum.
* Single-sector concentration: flag exposure above approximately 25–30%.

These are starting guidelines, not inflexible universal rules.
Create an investment ranking system.
Initial overall scoring:

* Growth potential: 25%.
* Financial strength: 20%.
* Valuation: 15%.
* Competitive advantage: 10%.
* Industry trends: 10%.
* Catalysts and news: 10%.
* Risk characteristics: 10%.

Higher risk scores must indicate better risk characteristics.
Grades:
A+: 95–100.
A: 90–94.
B: 80–89.
C: 70–79.
D: 60–69.
F: Below 60.
Use different scoring models for different asset classes.
An ETF should not be evaluated using exactly the same criteria as an individual growth company.
Display:

* Overall grade.
* Individual category scores.
* Supporting evidence.
* Positive factors.
* Negative factors.
* Confidence.
* Investment horizon.
* Major risks.
* Reasons to avoid the investment.

Grades must never be presented as probabilities of success or guaranteed returns.
Make scoring weights configurable and version every change.
Create separate leaderboards:

1. Best overall investment opportunities.
2. Best aggressive-growth stocks.
3. Best diversified growth ETFs.
4. Best undervalued investments.
5. Best emerging-industry opportunities.
6. Best dividend-growth investments.
7. Best international investments.
8. Best defensive investments.
9. Best commodity and precious-metal opportunities.
10. Best Canadian TFSA investments.

Each leaderboard must use an appropriate evaluation method.
Include a WATCH, BUY, HOLD, SELL and AVOID assessment.
These are research assessments only, not executed trades.
The system must explain when a candidate is attractive but not currently a good purchase.
Every primary recommendation must be verified as purchasable through BOTH:

* Wealthsimple.
* Questrade.

Check:

* Exact ticker.
* Exchange.
* Security type.
* Trading currency.
* Canadian investor accessibility.
* Brokerage support.
* Account restrictions.
* TFSA eligibility where relevant.

Use these statuses:
VERIFIED:
Reliable evidence confirms availability.
UNVERIFIED:
Availability cannot be reliably established.
UNAVAILABLE:
Reliable evidence indicates the investment cannot be purchased.
Only investments confirmed available on both brokerages qualify for the primary recommendation list.
Never assume availability because a security is listed on the TSX, NYSE or Nasdaq.
Do not fabricate brokerage API integrations or search results.
If direct availability verification is unavailable, clearly identify the limitation and provide a manual verification workflow.
Record:

* Verification date.
* Evidence source.
* Ticker.
* Exchange.
* Brokerage status.

Never request brokerage passwords.
Never execute real brokerage trades.
Create a dedicated Canadian TFSA module.
Produce:

* Best overall TFSA candidate.
* Best growth TFSA candidate.
* Best dividend TFSA candidate.

Evaluate:

* Qualified investment eligibility.
* Fees and MER.
* Underlying holdings.
* Diversification.
* Distribution sustainability.
* Currency exposure.
* US dividend withholding.
* Leverage.
* Concentration.
* Long-term total return.

Canadian-listed does not automatically mean Canadian underlying assets.
Do not assume foreign dividend withholding disappears inside a TFSA.
Never invent the owner's contribution room.
The system must investigate all relevant information that could influence investments.
Research:

* Financial news.
* Political developments.
* Elections.
* Government policy.
* Tariffs.
* Trade agreements.
* Central bank announcements.
* Inflation.
* Interest rates.
* Employment.
* Geopolitical conflicts.
* Wars.
* Regulatory changes.
* Company announcements.
* Earnings.
* Insider transactions.
* Institutional holdings.
* Technology developments.
* Supply chains.
* Energy markets.
* Commodity markets.
* Economic reports.
* Industry developments.

Use suitable sources, including official government releases, company investor-relations pages, economic institutions, licensed financial data providers, news feeds and permitted public sources.
Do not simply collect headlines.
Determine:

* What happened?
* When did it happen?
* Is it confirmed?
* Which companies could be affected?
* Which sectors could be affected?
* Which ETFs contain affected companies?
* Is the impact positive, negative, mixed or uncertain?
* Is the impact short-term or long-term?
* How confident is the assessment?
* What evidence supports it?

Detect related stories and duplicate reports.
Store source links, publication timestamps, collection timestamps and summaries.
Respect copyright and source licensing. Do not permanently reproduce entire copyrighted articles unless permitted.
Run one comprehensive AI research cycle per day.
Default time: 6:00 PM Eastern.
Workflow:

1. Collect new market information.
2. Collect relevant news.
3. Collect economic and political developments.
4. Check timestamps and data quality.
5. Deduplicate information.
6. Classify important developments.
7. Identify affected companies and ETFs.
8. Analyze underlying ETF holdings.
9. Run quantitative screening.
10. Identify the strongest candidates.
11. Send filtered candidates for deeper AI reasoning.
12. Challenge the strongest investment theses.
13. Evaluate diversification and portfolio fit.
14. Produce final rankings and recommendations.
15. Update saved watchlists.
16. Update paper trading.
17. Save all results.
18. Generate the daily report.
19. Send the daily email.
20. Record completion status and cost.

The system should not send all collected information to expensive AI models.
Use code and low-cost models to filter information before deep reasoning.
If the computer is asleep or turned off, the scheduled job should execute when the computer next becomes available, subject to Windows scheduling capabilities.
Prevent duplicate executions.
Implement retries and error recovery.
Never report successful completion when required analysis failed.
Build a provider-independent AI model router.
The system must allow different models to be used for different responsibilities.
LOW-COST AI:

* Article summarization.
* News classification.
* Entity extraction.
* Duplicate detection where necessary.
* Preliminary screening.
* Fact extraction.

PYTHON FINANCIAL ENGINE:

* Ratios.
* Valuations.
* Returns.
* Dividends.
* Portfolio statistics.
* ETF overlap.
* Correlations.
* Risk calculations.
* Paper trading.
* Backtesting.

PREMIUM REASONING AI:

* Deep investment analysis.
* Growth assessment.
* Valuation interpretation.
* Bullish and bearish thesis analysis.
* Portfolio fit.
* Risk evaluation.
* Final investment conclusions.

OPTIONAL INDEPENDENT REVIEWER:

* Challenge recommendations.
* Identify unsupported assumptions.
* Find overlooked risks.
* Evaluate alternative interpretations.

Do not run every AI agent for every investment.
Use efficient orchestration.
AI roles should be defined through version-controlled prompts and a shared investment constitution.
Every AI response should use structured, validated output.
Do not rely on an AI model to remember important information between requests. Retrieve relevant saved information from the database.
Do not fine-tune models initially. Use instructions, structured data, retrieval, quantitative algorithms and performance testing.
Model names and prices must be verified against current official provider documentation.
Never hardcode outdated model prices.
Initial AI API spending limit: $5 CAD per month.
The application must:

* Track every AI request.
* Record model names.
* Record input and output tokens.
* Estimate provider charges.
* Convert USD charges into CAD.
* Track costs per task.
* Display daily and monthly usage.
* Enforce the hard monthly limit.

When the limit is reached:

* Stop optional premium AI calls.
* Preserve existing results.
* Continue market-data collection if available.
* Continue deterministic Python calculations.
* Save incoming news.
* Clearly report that AI analysis is paused.

Never automatically increase the budget.
Do not claim $5 is guaranteed to be sufficient for unlimited research.
Measure actual usage and adjust the volume of research to the budget.
Market-data subscriptions, email delivery, hosting and other services are separate expenses.
Everything important must be permanently saved.
Save:

* Every daily research cycle.
* Every news item.
* Every source URL.
* Every investment analysis.
* Every recommendation.
* Every grade.
* Every prediction.
* Every reasoning report.
* Every portfolio snapshot.
* Every paper trade.
* Every dividend.
* Every benchmark result.
* Every watchlist item.
* Every personal note.
* Every user preference.
* Every strategy version.
* Every AI spending record.
* Every notification.
* Every email delivery status.

Historical records must be versioned.
Never overwrite an old analysis with a new analysis.
When a stock's grade changes, retain the original grade and the reason for the change.
Implement:

* Persistent local storage.
* Database migrations.
* Automated backups.
* Backup integrity checks.
* Restore testing.
* Audit logs.
* Data export.

Never reset the database during normal development.
Never delete historical information without explicit authorization.
The owner must be able to save any stock, ETF or investment.
A saved investment should include:

* Ticker.
* Exchange.
* Name.
* Date saved.
* Personal notes.
* Why the owner likes it.
* Investment thesis.
* Historical grades.
* Previous AI analyses.
* Related news.
* Price history.
* Alerts.

The owner should be able to save investments from anywhere in the application.
The AI must consider saved investments during future research.
Distinguish personal preferences from objective investment quality.
Never delete saved investments or personal notes without authorization.
Build a complete simulated investment system.
Initial virtual capital:
$100,000 CAD per paper portfolio.
Create four independent portfolios:
PORTFOLIO A — AI AGGRESSIVE GROWTH
Aggressive growth with diversification and risk controls.
PORTFOLIO B — GLOBAL GROWTH
Growth opportunities across multiple countries and regions.
PORTFOLIO C — GROWTH + PROTECTION
Growth assets combined with defensive investments.
PORTFOLIO D — AI EXPERIMENTAL
Tests new scoring systems, investment approaches and asset allocations.
Also create appropriate benchmark portfolios.
Simulate:

* Purchases.
* Sales.
* Holdings.
* Cash.
* Position sizing.
* Dividends.
* Dividend reinvestment.
* Fees.
* Slippage.
* Currency conversion.
* Splits and corporate actions where data is available.

Use realistic execution prices and trading assumptions.
Never use future information to make past simulated decisions.
Record the exact price, timestamp and information available when a decision is made.
Track:

* Total return.
* Annualized return.
* Maximum drawdown.
* Volatility.
* Sharpe ratio.
* Win rate.
* Benchmark performance.
* Dividend contribution.
* Trading costs.
* Performance by asset class.
* Performance by sector.
* Performance by strategy.

All paper trading calculations must be performed by code, not expensive AI calls.
The AI must evaluate its own previous recommendations.
Record:

* Original recommendation.
* Original investment thesis.
* Original grade.
* Original price.
* Expected horizon.
* Actual price performance.
* Dividends.
* Benchmark comparison.
* Whether the thesis remained valid.
* Whether the recommendation was successful.

Evaluate outcomes after:

* 7 days.
* 30 days.
* 90 days.
* 180 days.
* 365 days.

These are evaluation checkpoints, not guarantees that an investment should be sold at those times.
Maintain two separate systems:
FROZEN STRATEGY:
The original strategy remains unchanged as a control.
EXPERIMENTAL STRATEGY:
Tests alternative scoring weights and investment approaches.
Never automatically change the production strategy based on a few successful trades.
Require historical testing and out-of-sample validation.
Prevent:

* Look-ahead bias.
* Survivorship bias.
* Overfitting.
* Benchmark manipulation.
* Selective reporting.

Track whether the AI genuinely improves.
A full email report must be sent every time the daily research cycle successfully completes.
The email should contain:

1. Global market overview.
2. Major financial news.
3. Important political developments.
4. Economic developments.
5. Top investment opportunities.
6. Best growth stocks.
7. Best growth ETFs.
8. Best undervalued opportunities.
9. Best dividend opportunities.
10. International opportunities.
11. Diversification findings.
12. Canadian TFSA opportunities.
13. Important risks.
14. Saved watchlist updates.
15. Paper trading performance.
16. Changes from the previous report.
17. AI spending summary.
18. Sources and timestamps.

If research fails, send a separate failure notification.
Use a configurable email provider such as Resend or SMTP.
Do not hardcode credentials.
Document external email costs and setup requirements.
Support native Windows notifications for:

* Important news.
* Watchlist developments.
* Significant grade changes.
* New investment opportunities.
* Portfolio risk alerts.
* Daily research completion.
* Paper trading milestones.
* Failed background jobs.

Include an in-app notification centre.
Save notification history.
Notifications must not depend on expensive AI calls for simple price thresholds or deterministic events.
Create a sophisticated financial trading-terminal interface.
The interface should be polished, information-rich, responsive and easy to navigate.
Avoid generic admin dashboard styling.
Build these main sections:

1. Dashboard.
2. Global Market Overview.
3. Investment Intelligence.
4. Stock Screener.
5. ETF Screener.
6. Growth Opportunities.
7. Undervalued Investments.
8. Dividend Intelligence.
9. International Markets.
10. TFSA Intelligence.
11. Portfolio Analytics.
12. Asset Allocation.
13. Diversification Analysis.
14. News Intelligence.
15. AI Research Reports.
16. Paper Trading.
17. Strategy Performance.
18. Prediction History.
19. Watchlists.
20. Notifications.
21. API Cost Monitor.
22. Settings.

CHARTS:

* Candlesticks.
* Volume.
* Moving averages.
* RSI.
* MACD.
* Bollinger Bands.
* Portfolio performance.
* Sector heatmaps.
* Asset allocation.
* Benchmark comparisons.
* Historical predictions.

Support appropriate timeframes:

* 1 minute.
* 5 minutes.
* 15 minutes.
* 1 hour.
* Daily.
* Weekly.
* Monthly.

Only show timeframes supported by the selected data provider.
Every price must identify:

* Trading currency.
* CAD equivalent.
* USD equivalent.
* FX rate and timestamp.
* Data source.
* Live or delayed status.

Never fabricate live prices.
Research appropriate market-data providers before implementation.
Evaluate:

* Financial Modeling Prep.
* Twelve Data.
* Other suitable providers.
* Official exchange and government sources.
* Bank of Canada exchange-rate data.

Compare:

* Canadian coverage.
* US coverage.
* International coverage.
* Real-time data.
* Historical prices.
* Intraday data.
* Fundamentals.
* ETF holdings.
* News.
* Dividends.
* Corporate actions.
* API limits.
* Licensing.
* Cost.

Do not assume a free API offers real-time market data.
Do not assume personal-use access permits redistribution.
Build provider abstractions so data sources can be replaced.
Use official exchange or government sources where appropriate.
For currency conversion, distinguish:

* Trading currency.
* Underlying currency exposure.
* Hedged and unhedged funds.

Use Bank of Canada reference rates when appropriate, while clearly identifying that daily reference rates are not necessarily live trading rates.
Every important financial data point must have:

* Source.
* Timestamp.
* Currency.
* Data type.
* Live or delayed status.
* Quality status.

Identify missing or stale data.
Never silently substitute fabricated values.
If two providers disagree, identify the discrepancy.
Never allow an AI model to treat an estimate as a verified fact.
Implement secure local application architecture.
Requirements:

* API keys stored outside source code.
* Protected environment configuration.
* No secrets in Git.
* Input validation.
* Parameterized database queries.
* Safe error handling.
* Restricted local network exposure.
* Database access controls.
* Secure backups.
* Dependency checks.
* Audit logging.

Do not mount the entire Windows drive unnecessarily.
Do not expose the Docker socket.
Do not access unrelated personal files.
Do not request brokerage credentials.
No real trading.
Design the application so a future remote or locally hosted MCP server can expose InvestIQ information to Claude.
Potential tools:

* get_market_overview.
* search_investments.
* get_stock_analysis.
* get_etf_analysis.
* get_latest_news.
* get_portfolio_overview.
* get_diversification_report.
* get_daily_recommendations.
* get_paper_trading_results.
* get_watchlist.
* get_ai_performance.

MCP must initially be read-only.
Do not let Claude execute trades or modify portfolio holdings.
This connector is an additional feature, not a replacement for automated API-based research.
Allow the owner to configure:

* Daily research time.
* Email address and email provider.
* Notification preferences.
* AI spending limit.
* Preferred currency display.
* Watchlists.
* Asset-class preferences.
* Risk limits.
* Portfolio allocations.
* Research universe.
* Brokerage verification preferences.
* AI model configuration.

Never assume the owner's actual portfolio or account balances.
Provide an interface for entering holdings and average purchase prices manually.
You must deliver the complete application through these stages, without requiring the owner to manually supply a separate prompt for each stage.
STAGE 0 — FOUNDATION

* Inspect environment.
* Create Git repository.
* Create documentation.
* Establish architecture.
* Configure project structure.
* Establish development commands.

STAGE 1 — CORE APPLICATION

* Backend.
* Frontend.
* Database.
* Migrations.
* Settings.
* Logging.
* Health checks.

STAGE 2 — DATA INFRASTRUCTURE

* Market data.
* Fundamentals.
* ETF holdings.
* Currency conversion.
* News ingestion.
* Data validation.

STAGE 3 — QUANTITATIVE ENGINE

* Stock scoring.
* ETF scoring.
* Asset-class analysis.
* Diversification.
* Portfolio analytics.
* Brokerage verification.

STAGE 4 — AI INTELLIGENCE

* Model router.
* Investment constitution.
* Agent instructions.
* News research.
* Stock analysis.
* ETF analysis.
* Risk management.
* Chief analyst.
* Evidence and citations.

STAGE 5 — AUTOMATION

* Daily scheduling.
* Research pipeline.
* Recovery.
* Email reports.
* Windows notifications.

STAGE 6 — PAPER TRADING

* Four portfolios.
* Simulated orders.
* Dividends.
* Benchmarks.
* Performance analytics.

STAGE 7 — PERFORMANCE LEARNING

* Prediction tracking.
* Strategy versioning.
* Historical backtesting.
* Out-of-sample validation.
* Frozen and experimental strategies.

STAGE 8 — DASHBOARD

* All major screens.
* Interactive charts.
* Reports.
* Search.
* Filters.
* Settings.

STAGE 9 — HARDENING

* Automated testing.
* Security review.
* Performance testing.
* Backup and recovery.
* Windows compatibility.
* Installation scripts.
* Documentation.

Do not leave the application as a collection of disconnected prototypes.
All modules must integrate into one working product.
Create and maintain:
CLAUDE.md
docs/MASTER_SPEC.md
docs/ARCHITECTURE.md
docs/ROADMAP.md
docs/PROGRESS.md
docs/DECISIONS.md
docs/DATA_SOURCES.md
docs/SECURITY.md
docs/TESTING.md
docs/KNOWN_ISSUES.md
The complete specification in this prompt must be preserved in MASTER_SPEC.md.
Update PROGRESS.md after meaningful milestones.
Record technical decisions and reasons.
Keep a clear list of incomplete features and external dependencies.
When a new session begins, use the documentation to resume.
Never repeatedly reread the entire codebase if reliable project documentation and targeted inspection can establish the current state.
Every module must have automated tests.
Test:

* Financial calculations.
* Scoring.
* ETF overlap.
* Portfolio allocations.
* Currency conversion.
* Data validation.
* AI response validation.
* API spending controls.
* Database migrations.
* Backup restoration.
* Paper trading.
* Dividend calculations.
* Benchmark comparisons.
* Scheduling.
* Email delivery.
* Windows notifications.
* Security controls.

Use synthetic test data.
Do not use fabricated data in actual production reports.
A feature is not complete merely because a screen exists.
It must be connected to real backend functionality and tested.
Start by inspecting the current project directory and environment.
Read the existing CLAUDE.md.
Create the documentation and project structure.
Preserve this entire specification in docs/MASTER_SPEC.md.
Design the architecture and document important decisions.
Initialize Git if necessary.
Set up the development environment.
Then immediately begin implementing the application.
Do not stop after planning.
Continue through the complete roadmap autonomously wherever possible.
Do not ask the owner to approve every ordinary development decision.
When an external API key, account permission, paid subscription or unavailable service blocks a feature:

* Document the blocker.
* Build the integration interface.
* Use synthetic test fixtures only for development.
* Continue other implementation work.
* Clearly identify what remains unconfigured.

If you encounter a technical problem:

* Investigate it.
* Attempt a reasonable fix.
* Test the fix.
* Document unresolved issues.

Never pretend something is complete when it is not.
InvestIQ is successful only when it is a functioning, integrated Windows application that:

* Performs daily automated investment research.
* Collects reliable financial and global information.
* Evaluates stocks, ETFs and multiple asset classes.
* Identifies diversified growth opportunities.
* Evaluates the complete portfolio.
* Checks Wealthsimple and Questrade availability.
* Includes Canadian TFSA intelligence.
* Uses multiple AI models efficiently.
* Enforces its AI spending budget.
* Saves all important information permanently.
* Maintains personal watchlists and notes.
* Generates daily email reports.
* Sends Windows desktop notifications.
* Runs four paper trading portfolios.
* Measures performance against benchmarks.
* Tracks predictions.
* Tests investment strategy improvements.
* Displays a professional financial dashboard.
* Operates reliably on Windows.
* Protects historical data.
* Passes its automated tests.

The ultimate goal is not to create an attractive interface or produce many stock recommendations.
The ultimate goal is to deliver a reliable, evidence-based investment intelligence system that helps the owner make better diversified investment decisions and compound capital over the long term.
BEGIN DEVELOPMENT NOW.
