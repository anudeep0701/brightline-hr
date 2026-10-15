# Brightline Integration Health

A production-shaped FDE case study: tenant-scoped operational health across payroll, e-signature, ATS, directory and notification systems. Deterministic decisions, auditable evidence and optional OpenAI incident assistance.

The repository root is the monorepo (`brightline-hr` locally); no extra nested checkout is required.

## Run locally without credentials
Requires Python 3.11+ and Node.js 22+. Commands below start from this repository root. No `.env` file is required or created.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
DATABASE_URL=sqlite:///./data/demo.db python scripts/seed.py
cd backend
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open [the dashboard](http://localhost:3000) and [API documentation](http://localhost:8000/docs). Default local `APP_ENV=demo` uses a synthetic tenant and SQLite at `data/demo.db`; production requires PostgreSQL. The SQLite default path assumes Uvicorn runs from `backend/`, while the seed command explicitly uses the repository-root path. Demo seeding is non-destructive and only runs once. To regenerate fresh scenarios later, stop the backend, explicitly remove **only** `data/demo.db`, then rerun the seed command. Data does not advance automatically: stale telemetry is a deliberate observable state.

Use `docker compose up -d` for local PostgreSQL. Set `DATABASE_URL` to `postgresql://brightline:local-demo-only@localhost:5432/brightline`, then run `python scripts/migrate.py` and optionally `python scripts/seed.py` with `APP_ENV=demo`. Pass the same database URL to the backend process. SQLite is only an evaluator convenience; PostgreSQL is the deployed database.

## What to inspect
- Gusto: failure-rate outage; fast responses cannot offset errors.
- DocuSign: degraded latency despite successful responses.
- Greenhouse, Okta and Slack: healthy.
- Workday: stale telemetry; Checkr: insufficient samples.
- ADP: historical incident and sustained recovery.
- Integration detail: exact reasons, versioned thresholds, 24-hour history, incident timeline and recent sanitized logs.
- Explain: deterministic fallback without a key; optional aggregate-grounded OpenAI output when configured.

## Health policy
Every five minutes, evaluate the last 15-minute window. ≥1% error rate or ≥1.5× latency target is degraded; ≥5% or ≥3× is unhealthy. Worst signal wins. Fewer than 20 samples or stale telemetry is unknown, except catastrophic low-volume bursts (≥5 failures and ≥50% error rate). Incidents resolve after two adjacent healthy evaluation buckets. The browser refreshes every 60 seconds. Read [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md) for tradeoffs, edge cases and scale limits.

## Verify
```bash
cd backend
../.venv/bin/pytest -q
cd ../frontend
npm run typecheck
npm run build
npm audit
```

CI additionally provisions isolated PostgreSQL and checks migrations, RLS enablement and concurrent refresh behavior through `scripts/check_postgres.py`. To run that check locally, provide a dedicated PostgreSQL test database via `DATABASE_URL` and `APP_ENV=test`; it creates and removes only its own randomized test tenant. Never point CI at customer data.

## Layout
```text
frontend/src/app/           dashboard and integration detail routes
frontend/src/components/   shared shell, status and history components
frontend/src/lib/          typed API client and formatting
frontend/src/types/        API response types
backend/app/api/           HTTP routes and tenant authorization
backend/app/schemas/       Pydantic ingestion/output schemas
backend/app/models/        SQLAlchemy persistence models
backend/app/db/            engine/session access
backend/app/ingestion/     idempotent validated batch ingestion
backend/app/metrics/       Polars event-time analytics
backend/app/health/        pure versioned policy and refresh service
backend/app/incidents/     recovery lifecycle
backend/app/ai/            optional cached explanations and fallback
backend/migrations/        versioned PostgreSQL schema
backend/tests/             deterministic and API regression tests
data/                      ignored synthetic request data / local database
scripts/                   generation, seed, migration, admin and PG checks
docs/                      model plan, API contract, checklist and deployment
```

## Credentials and deployment
Only [.env.example](.env.example) is tracked, with blank placeholders. Keep it blank and configure actual values through your local environment or Vercel settings. [Credentials and deployment](docs/CREDENTIALS_AND_DEPLOYMENT.md) gives step-by-step OpenAI key creation, Supabase connection setup, workspace token provisioning, cron configuration and Git-based Vercel deployment.

Deploy as two Vercel projects using `frontend/` and `backend/` roots, sharing this Git repository and Supabase PostgreSQL. The five-minute cron needs a suitable Vercel plan. No credentials were provisioned and no hosted deployment was performed by this implementation.

This MVP includes hashed tenant tokens, role checks, validated metadata, immutable evidence, transactional refresh and automated tests. It does not yet include SSO, real provider exporters, notification delivery, retention automation or enterprise operational hardening. These boundaries and the rollout plan are explicit in the solution design.

Production builds explicitly use Next.js Webpack (`next build --webpack`) for compatibility with restricted local build environments. The Next.js development server still uses its default bundler.
