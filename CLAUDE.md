# InvestIQ — Permanent Project Instructions

InvestIQ is a professional, Windows-based, local-first AI investment research and portfolio
intelligence platform. Its mission is to identify aggressive, diversified, long-term investment
opportunities and help compound the owner's portfolio. Reliability, accuracy, security and data
integrity matter more than development speed.

## Start of every session

1. Read this file, `docs/PROGRESS.md` (last verified milestone) and `docs/KNOWN_ISSUES.md`.
2. Read the docs relevant to the task: `docs/MASTER_SPEC.md` (the complete, verbatim
   specification), `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/DATA_SOURCES.md`,
   `docs/SECURITY.md`, `docs/TESTING.md`, `docs/ROADMAP.md`.
3. Continue from the last verified milestone. Use targeted inspection; do not re-read the whole codebase.

Never rely only on conversation history for requirements: the docs are the source of truth.

## Development standards

- Modular code that follows `docs/ARCHITECTURE.md`; frontend, backend API, AI orchestration,
  financial engine and database stay separate.
- Commit working milestones. Test significant features. Keep the application working.
- Never claim functionality works without testing it. Never replace working functionality with
  placeholders. Never rewrite completed modules without a reason recorded in `docs/DECISIONS.md`.
- A feature is complete only when: implementation exists, tests pass, errors are handled,
  docs are updated, and existing functionality remains intact.
- Update `docs/PROGRESS.md` after meaningful milestones and `docs/KNOWN_ISSUES.md` when
  something is incomplete or blocked.

## Investment rules the code must preserve

- Aggressive long-term growth with diversification across asset classes, sectors, countries.
- Never focus only on stocks or technology. Never force a BUY. WATCH ("wait") is valid.
- Never guarantee returns. Grades are not probabilities.
- Primary recommendations require VERIFIED availability at BOTH Wealthsimple and Questrade.
  Never assume availability from an exchange listing.
- Never execute real trades. Never request brokerage credentials.
- Use Python for deterministic financial calculations; AI only for interpretation, with evidence.
- Never fabricate financial data or sources. Synthetic data is for development/tests only.
- AI budget: $5 CAD/month hard limit by default; never raised automatically.

## Data integrity

- Historical records are append-only (ORM guard + PostgreSQL triggers). Insert new versions;
  never overwrite analyses, grades, recommendations, predictions, trades, notes or strategies.
- Never run destructive database operations without explicit owner authorization and a verified backup.
- Schema changes only through Alembic migrations in `backend/migrations/versions/`.

## Security

- Secrets only in `.env` (git-ignored) / environment variables. Never commit secrets.
- API binds to 127.0.0.1 and requires the local API token; the browser never sees the token.
- Do not access unrelated personal files. Do not expose the database or Docker socket.

## Commands

```bash
# Backend (from backend/)
uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev,mcp]"
investiq migrate                         # verified backup, then Alembic migrations (INVESTIQ_DATABASE_URL)
investiq bootstrap                       # seed universe, strategies, portfolios
investiq serve                           # API on 127.0.0.1:8765 (+ in-process scheduler)
investiq run-cycle --if-due              # daily research cycle (idempotent)
python -m pytest                         # tests (SQLite); set INVESTIQ_TEST_DATABASE_URL for PostgreSQL
ruff check investiq tests

# Frontend (from frontend/); the proxy needs INVESTIQ_API_TOKEN in its environment
npm install && npm run dev               # http://127.0.0.1:3000
npm test && npm run typecheck && npm run build

# Database for development: docker compose up -d db   (needs .env; see .env.example)

# Windows (scripts/windows/): install.ps1, start.ps1, stop.ps1, run-cycle.ps1,
# register-task.ps1 (daily task), backup.ps1. See docs/INSTALL.md.
```
