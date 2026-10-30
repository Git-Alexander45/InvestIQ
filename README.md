# InvestIQ

Local-first AI investment research and portfolio intelligence platform for Windows.
Research, analytics and paper trading only: InvestIQ never places real trades and never asks for
brokerage credentials.

* Daily automated research across stocks, ETFs, bonds, commodities and cash equivalents, with
  evidence-based scores, grades and BUY / WATCH / HOLD / SELL / AVOID assessments.
* Diversification and ETF look-through analysis of your holdings, TFSA intelligence, and
  Wealthsimple / Questrade availability tracking.
* AI analysis under a hard monthly budget (default 5 CAD), four paper portfolios against
  benchmarks, prediction tracking and strategy backtests.
* Professional dashboard on http://127.0.0.1:3000 and a read-only MCP server for Claude.

## Quick start (Windows)

Prerequisites: Docker Desktop, Python 3.12+, Node.js 20+, Git.

```powershell
git clone https://github.com/Git-Alexander45/InvestIQ.git
cd InvestIQ
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -RegisterTask
scripts\windows\start.ps1 -Open
```

Then add a market data key (and optionally an AI key) to `.env`. Full instructions:
[`docs/INSTALL.md`](docs/INSTALL.md).

## Documentation

| Document | Contents |
|---|---|
| [MASTER_SPEC](docs/MASTER_SPEC.md) | The complete specification |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | How the parts fit together |
| [INSTALL](docs/INSTALL.md) | Installation, configuration, backups, updates |
| [DATA_SOURCES](docs/DATA_SOURCES.md) | Providers, keys and data quality rules |
| [SECURITY](docs/SECURITY.md) | Security model and review log |
| [TESTING](docs/TESTING.md) | Test commands, coverage and performance |
| [PROGRESS](docs/PROGRESS.md) / [ROADMAP](docs/ROADMAP.md) | Status |
| [DECISIONS](docs/DECISIONS.md) | Technical decisions and reasons |
| [KNOWN_ISSUES](docs/KNOWN_ISSUES.md) | Limitations and what still needs configuration |

InvestIQ provides research opinions, not financial advice, and never guarantees returns.
