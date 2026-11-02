# Security

InvestIQ holds the owner's financial research, holdings and API keys on one Windows computer. The
design goal is that nothing is reachable from outside that computer, secrets never leave `.env`,
history cannot be rewritten, and nothing can trade or spend money on its own.

## Hard rules

* No real trading, ever. There is no brokerage integration that can place orders, and InvestIQ
  never asks for brokerage usernames or passwords. Paper trading uses virtual money only.
* No spending without the owner. The AI budget is a hard monthly limit in CAD that is never raised
  automatically; raising it requires `confirm_budget_increase`. InvestIQ never buys subscriptions.
* No destructive database operations without explicit owner authorization and a verified backup.
* No secrets in Git. `.env` and `.env.*` are git-ignored; only `.env.example` (with empty values) is
  committed.

## Network exposure

| Component | Listens on | Notes |
|---|---|---|
| PostgreSQL (Docker) | `127.0.0.1:5432` | Published on loopback only; named volume; no host folders mounted; Docker socket not mounted; `no-new-privileges`. |
| API (`investiq serve`) | `127.0.0.1:8765` | Refuses to bind to anything other than loopback unless `--allow-lan` is passed deliberately. Refuses to start without an API token. |
| Dashboard (`next start`) | `127.0.0.1:3000` | Scripts bind it to loopback. |
| MCP server | stdio only | No network listener. |

## API protections

* Every route except `GET /api/health` requires the local API token (`Authorization: Bearer` or
  `X-InvestIQ-Token`), compared in constant time.
* `TrustedHostMiddleware` accepts only `127.0.0.1`, `localhost` and `::1`, which blocks DNS
  rebinding attacks against the API.
* CORS allows only the dashboard origin.
* Errors return a generic message and an error id; details go to the local log only.
* Security headers on every response (`nosniff`, `X-Frame-Options: DENY`, `no-referrer`,
  `no-store`). OpenAPI docs are disabled in production.
* Inputs are validated by Pydantic models with bounds; uploads are size-limited (brokerage CSV
  1 MB); downloads are restricted to the export folder and reject path traversal.
* Database access is through SQLAlchemy with bound parameters. The only formatted SQL statements
  create and drop the temporary restore-test database, whose name is generated internally.

## Dashboard protections

* The browser never sees the API token: the Next.js server-side proxy (`/api/iq/*`) adds it.
* The proxy only forwards plain API path segments to the configured local API (no traversal, no
  other hosts).
* The proxy rejects requests whose `Host` is not the dashboard's own (DNS rebinding) and
  cross-site requests (`Origin` / `Sec-Fetch-Site`), so another website cannot use the browser to
  act on InvestIQ. Allowed hosts can be changed with `INVESTIQ_DASHBOARD_HOSTS`.
* Generated reports are shown in a sandboxed iframe with a restrictive Content-Security-Policy, so
  report content cannot run scripts.

## Secrets

* Stored only in `.env` (or environment variables). The Windows installer generates a random
  database password and API token and restricts `.env` to the owner's account with `icacls`.
* `investiq status` and the dashboard report only whether a key is configured, never its value.
* Backups use `PGPASSWORD` in the environment, never on the command line.
* The installer never prompts for or stores brokerage credentials.

## Data integrity and audit

* Append-only history enforced by the ORM and by PostgreSQL triggers (see ARCHITECTURE.md).
* Owner actions (settings changes, budget changes, strategy promotion, holdings entries, brokerage
  verifications, backups) are written to the audit log, viewable in the dashboard.
* Backups are checksummed, verified, restore-tested and never deleted automatically. Backup files
  and exports are created with owner-only permissions where the operating system allows.
* CSV exports prefix text beginning with `=`, `+`, `-` or `@` so spreadsheets never execute
  externally sourced text (such as news headlines) as formulas.

## AI and MCP

* The MCP server exposes exactly 11 read-only tools. Each call runs in a read-only database
  transaction (PostgreSQL `SET TRANSACTION READ ONLY`, SQLite `query_only`) that is always rolled
  back. There are no tools that trade, change holdings, change settings or spend AI budget.
* AI output is validated against strict JSON schemas; citations must refer to evidence supplied to
  the model; AI can only make an assessment more cautious.
* News and filings are untrusted input. They are passed to models as quoted evidence with
  instructions to treat them as data, and AI output never triggers actions directly.
* XML feeds are parsed with `defusedxml` (no external entities).

## Windows notifications

Toast text is passed to PowerShell base64-encoded in an environment variable and XML-escaped
inside the script, so notification text can never be interpreted as a command.

## Review log

| Date | Check | Result |
|---|---|---|
| 2026-10-30 | `pip-audit` (backend virtual environment) | No known vulnerabilities |
| 2026-10-30 | `npm audit` (dashboard) | 0 vulnerabilities |
| 2026-10-30 | `ruff` with flake8-bandit (`S`) rules | All checks passed |
| 2026-10-30 | Secrets scan of the repository and history (API key, private key and token patterns; committed `.env` files) | None found |
| 2026-10-30 | Manual review: SQL construction, subprocess use, deserialization, file paths, uploads, proxy | Added DNS-rebinding and cross-site checks to the dashboard proxy and formula neutralisation to CSV exports; no other issues found |

Re-run these checks before each release (commands in `docs/TESTING.md`).
