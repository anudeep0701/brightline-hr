# Brightline HR Integration Health

Brightline Ops often learns an integration is broken from a customer ticket. This product turns request logs into a morning view of what needs attention, why, and whether it is recovering. Health is deterministic; optional OpenAI assistance explains observed evidence and suggests checks. The operator decides what to do.

The [hosted assessment](https://brightline-hr.vercel.app) opens in a constrained Brightline demo workspace using synthetic/demo telemetry. The reviewer does not need to supply a workspace credential. Production deployments retain tenant-scoped workspace authentication. Never upload real employee/customer data to the shared demo.

## Reviewer map

Start with this README and the two-page [SOLUTION_DESIGN.pdf](SOLUTION_DESIGN.pdf). Its editable source is [SOLUTION_DESIGN.md](SOLUTION_DESIGN.md). The guide's reviewer reads about 15 files; these 13 implementation/configuration files are the suggested drill-down, not a limit on the source needed to run the app.

| Requirement / decision | Key file |
| --- | --- |
| Run the supplied 60 logs end to end | `scripts/replay_official_data.py` |
| Normalize, validate and deduplicate telemetry | `backend/app/ingestion/service.py` |
| Include errors/timeouts and P95 latency | `backend/app/metrics/calculation.py` |
| Configurable thresholds, volume, window and cadence | `backend/app/health/config.py` |
| Explainable states, hysteresis and recovery | `backend/app/health/policy.py` |
| Incident opening/resolution | `backend/app/incidents/lifecycle.py` |
| Secure automatic fixed-tenant demo session | `backend/app/api/demo.py` |
| Scoped, read-only AI with fallback and guardrails | `backend/app/ai/operations_assistant.py` |
| Morning priorities, freshness and fleet overview | `frontend/src/components/operations-view.tsx` |
| Evidence, trends, recovery and AI drill-down | `frontend/src/app/integrations/[id]/page.tsx` |
| Official-input acceptance and timeout regression | `backend/tests/test_official_data.py` |
| Health policy business tests | `backend/tests/test_health_engine.py` |
| One Vercel project, separate Next.js/FastAPI services | `vercel.json` |

## Run locally

Requires Python 3.11+ and Node.js 22+ with npm; internet is needed to install packages. macOS/Linux commands below start at the extracted `brightline-hr/` root. Git, PostgreSQL and an OpenAI key are not needed for the local SQLite demo.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
export APP_ENV=demo
export DATABASE_URL=sqlite:///./data/demo-v4.db
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/seed.py
npm run dev
```

Open http://localhost:3000. Backend: http://localhost:8000; probes: `/healthz`, `/readyz`; API docs: `/docs`. Ctrl+C stops both services. The explicitly selected local SQLite demo is credential-free. Normal PostgreSQL workspaces require Workspace access; the hosted assessment uses a separate automatic one-hour HttpOnly demo session.

You may manually copy `.env.example` to root `.env` if it does not exist, then populate your own values; keep the example blank. The Node launcher loads root configuration, while Python administration CLIs read exported process variables only. Do not create frontend environment files. [Local setup and Windows notes](docs/LOCAL_DEVELOPMENT.md).

## Run the official supplied dataset

The unchanged 60-record input is included as a required fixture at `data/provided/integration_logs.json`. Optional starter helpers were replaced: their error denominator drops timeouts. This replay uses the same ingestion, metrics, policy and incident services as production:

```sh
.venv/bin/python scripts/replay_official_data.py
# For a fresh UI replay, stop the normal app and use two terminals:
.venv/bin/python scripts/replay_official_data.py --rebase-to-now --serve
# Other terminal:
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm --prefix frontend run dev
```

Exact replay reports historical results at 2026-08-04 10:00 UTC: Slack/Workday Healthy; ADP/DocuSign/Greenhouse Unhealthy. Greenhouse has 50% failures including five timeouts, not just one HTTP error. The sparse sample profile uses a 60-minute window, five-request floor and 10%/30% warning/critical rates; production defaults remain unchanged. UTC is assumed for timezone-free input. Explicit rebase shifts timestamps uniformly for presentation; no outcomes or stored rows are rewritten. [Mapping and rationale](docs/OFFICIAL_DATA_REPLAY.md).

## Decisions, AI and use

Default policy: 15-minute windows, five-minute intended evaluation cadence, 20 requests, 1%/5% error/timeout warnings/critical thresholds, and P95 at 1.5×/3× the configured target or eligible healthy baseline. The worst signal wins. Two adjacent bad windows confirm critical failure, three degraded windows escalate, and two clean windows below stricter recovery margins resolve. UNKNOWN means insufficient/stale evidence; no errors alone does not mean healthy. [Exact rules](docs/HEALTH_ENGINE.md).

Overview prioritizes issues; Integrations filters the fleet; Incidents shows active/resolved history. AI assistant answers workspace questions; detail pages support integration/incident questions. Answers cite bounded facts and disclose more evidence on request. AI cannot change health, incidents, thresholds or credentials, execute remediation, or query another tenant. Telemetry is untrusted data; raw messages, employee data and credentials are excluded from model context. Missing/failed AI returns deterministic assistance. [AI controls](docs/AI_OPERATIONS.md).

Data Sources supports previewed/confirmed CSV, JSON and NDJSON/JSONL uploads (2 MiB/1,000 records), and documents `POST /api/ingest` with separate tenant-scoped ingestion-only keys. Both share the domain ingestion path. [File/API onboarding](docs/DATA_ONBOARDING.md) · [API contract](docs/API_CONTRACT.md).

Synthetic scenarios extend the official input with outages, latency, sparse traffic, spikes and recovery. Run `.venv/bin/python scripts/generate_synthetic_data.py --scenario all --duration 90 --tenants 3 --seed 42` to regenerate offline. Bulk generated logs and standalone images are omitted from the submission; tests still verify a fixed dataset digest. [Generator](data/synthetic/README.md).

## Test

```sh
.venv/bin/python -m pytest -q backend/tests
.venv/bin/python -m ruff check backend scripts --select F,I
.venv/bin/python -m ruff format --check backend scripts
npm --prefix frontend test
npm test
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
.venv/bin/python scripts/smoke_test.py --port 8012
```

Tests are isolated and need no credentials. PostgreSQL migration/concurrency and clean-copy checks are described in [verification](docs/VERIFICATION.md); SQLite alone does not establish those behaviors.

## Deployment and configuration

One root Vercel Services project builds Next.js/TypeScript/Tailwind and Python/FastAPI/Pydantic separately; `/api/*` and probes route to FastAPI, other paths to Next.js. Polars computes metrics; hosted storage is Supabase PostgreSQL. Apply `scripts/migrate.py` manually after exporting the target database URI. No migration runs during requests/builds. [Supabase-first deployment](docs/CREDENTIALS_AND_DEPLOYMENT.md).

Required hosted variables: `DATABASE_URL`, `APP_ENV=production`, `CRON_SECRET`. Optional AI: `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-6-luna`). Public assessment additionally needs `DEMO_MODE=true`, `DEMO_TENANT_SLUG=brightline`, `DEMO_SESSION_SECRET`; file imports opt in with `DEMO_ALLOW_FILE_IMPORT=true`. Leave `NEXT_PUBLIC_API_BASE_URL`/`CORS_ALLOWED_ORIGINS` unset for same-origin production; they are optional local overrides. `PGPASSWORD` is only for optional local Docker Compose. Secrets are server-side; all example placeholders are blank.

Hobby has no configured cron: Evaluate now evaluates existing traffic. Demo-only Refresh demo data refills bounded synthetic feeds through normal ingestion. Production would use the protected cron endpoint with approximately five-minute scheduling. Polling every 60 seconds only reloads evidence.

## Trade-offs and gaps

Rules are explainable but need real-traffic calibration; confirmation adds delay. One PostgreSQL store avoids streaming complexity but requires load/retention work at scale. SSO, notifications, provider pull connectors and autonomous remediation are intentionally absent. AI budgets are best-effort per worker. Sample outcomes are not customer ROI; MTTD and ticket lead-time need independent production timestamps. [Compliance and submission steps](docs/FINAL_SUBMISSION_COMPLIANCE.md).
