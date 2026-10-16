# Local end-to-end validation — 2026-10-16

This run used isolated synthetic SQLite and loopback PostgreSQL 16 databases. No hosted connection, environment file or live OpenAI request was used. README.md and SOLUTION_DESIGN.md were not changed by this task. Nothing was deployed or prepared for Vercel deployment.

## Reproduce the smoke test

From the repository root, with the existing virtual environment and installed dependencies:

```bash
.venv/bin/python scripts/smoke_test.py
```

The command creates temporary SQLite storage, generates two tenants with all ten scenarios, replays historical evaluation, launches a real FastAPI HTTP process, tests authenticated ingestion and health APIs, restarts the API to verify persistence, and cleans up. It disables OpenAI and overrides inherited DATABASE_URL, so an inherited hosted URL cannot be used. It never loads environment files or prints generated credentials. Port 8000 must be available; choose `--port 8012` otherwise.

For browser inspection, keep its API running:

```bash
.venv/bin/python scripts/smoke_test.py --serve
```

In a second terminal:

```bash
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open http://localhost:3000. The default API base is http://localhost:8000. Use `--scenario` with the existing demo launcher for a focused scenario instead of the full smoke acceptance flow:

```bash
.venv/bin/python scripts/run_demo.py --scenario authentication-outage
```

The launcher also supports `all`, `healthy`, `latency-degradation`, `complete-outage` and `recovery`. Stop the current local backend before changing launchers. The synthetic data is a historical replay; elapsed time intentionally makes evidence stale. A reload preserves recorded decisions; Evaluate now evaluates current evidence rather than manufacturing new traffic.

## Existing developer commands

Commands start at the repository root unless indicated. Backend scripts read process environment variables, not environment files. Configure/export settings privately; merely adding them to an environment file does not make these CLI commands load them.

| Operation | Actual repository command |
| --- | --- |
| Persistent local SQLite dataset | `APP_ENV=demo DATABASE_URL=sqlite:///./data/local-validation.db .venv/bin/python scripts/seed.py --duration 90 --tenants 2 --seed 42` |
| Backend using that dataset | `APP_ENV=demo DATABASE_URL=sqlite:///./data/local-validation.db .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000` |
| Frontend development | In `frontend/`: `npm run dev -- --hostname 127.0.0.1 --port 3000` |
| Frontend production preview | In `frontend/`: `npm run build`, then `npm run start -- --hostname 127.0.0.1 --port 3000` |
| PostgreSQL migrations | `.venv/bin/python scripts/migrate.py` with an explicitly configured development DATABASE_URL |
| Generate reproducible JSONL | `.venv/bin/python scripts/generate_synthetic_data.py --scenario all --duration 90 --tenants 2 --seed 42 --output data/synthetic/generated` |
| Load generated file | `.venv/bin/python scripts/ingest_file.py data/synthetic/generated/requests.jsonl --tenant brightline --allow-historical` |
| Evaluate current tenant | `POST /api/evaluate`, workspace operator bearer token required outside local demo |
| Provision tenant/workspace access | `.venv/bin/python scripts/admin.py brightline 'Brightline HR' --integration workday-payroll` (hidden workspace-token prompt) |
| Issue external ingestion key | `.venv/bin/python scripts/ingestion_keys.py create brightline --name 'Customer exporter'` |
| Backend tests | `.venv/bin/python -m pytest -q backend/tests` |
| Python lint | `.venv/bin/ruff check --select F,I backend/app backend/tests scripts` |
| Python formatting check | `.venv/bin/ruff format --check backend/app backend/tests scripts` |
| Frontend tests/types | In `frontend/`: `npm test` and `npm run typecheck` |
| Frontend formatting/build | In `frontend/`: `npx --no-install prettier --check src` and `npm run build` |

The generated file contains multiple tenants; the importer intentionally rejects records for tenants other than its explicit `--tenant`. Provision matching integration IDs first. For the complete multi-tenant demo, use seed.py or smoke_test.py, which group by tenant before calling the same ingestion service. Generation defaults to a fixed historical UTC anchor; `--start` accepts an explicit five-minute boundary. Historical imports are trusted CLI behavior, unavailable to external HTTP callers.

Python type checking and ESLint are not configured. TypeScript checking, Python import/undefined-name checks and frontend formatting were executed; formatting is not represented as ESLint coverage.

## Local PostgreSQL workflow

Docker Desktop must be running. The existing Compose setup requires PGPASSWORD in the shell. Explicitly disable Compose's implicit environment-file loading:

```bash
docker compose --env-file /dev/null up -d
```

Manually configure DATABASE_URL to the local `brightline` database on loopback port 5432 using the credentials you supplied to Compose. Then use scripts/migrate.py and, for this local demo only, scripts/seed.py before starting Uvicorn. Backend startup has no automatic schema migration.

For repeatable migration/backfill checks, create a separate empty local database (never customer data):

```bash
docker compose --env-file /dev/null exec postgres createdb -U brightline brightline_upgrade_check
```

Set DATABASE_URL manually to that empty local database and APP_ENV to test, then run:

```bash
.venv/bin/python scripts/check_postgres.py
```

For the PostgreSQL HTTP smoke test, create another empty database whose name starts with `brightline_smoke`:

```bash
docker compose --env-file /dev/null exec postgres createdb -U brightline brightline_smoke_validation
```

Point DATABASE_URL at that loopback database, then:

```bash
.venv/bin/python scripts/smoke_test.py --local-postgres --duration 180 --tenants 3 --port 8011
```

The smoke command rejects hosted hosts, ordinary database names, connection query overrides and nonempty databases. It does not delete an existing schema. PostgreSQL data remains in its explicitly created test database; the default SQLite mode cleans itself up. Choose a fresh database name for another PostgreSQL smoke run.

For a manually configured Supabase **development** database, export DATABASE_URL privately and apply migrations explicitly yourself. The local smoke command deliberately refuses hosted URLs; this validation did not use that alternative. Keep production and development connections distinct.

## Manual environment configuration

No variables are needed for default isolated smoke mode. For ordinary PostgreSQL operation configure DATABASE_URL, APP_ENV, CORS_ALLOWED_ORIGINS and NEXT_PUBLIC_API_BASE_URL. Local Compose additionally needs PGPASSWORD. OPENAI_API_KEY is optional and backend-only. CRON_SECRET is required when selecting production settings. No new variable or environment-file edit was introduced.

## Verified results

- Full SQLite HTTP smoke: 15,673 generated events, two tenants, 20 scenario series. Generation/ingestion/historical evaluation took 15.28 seconds on this machine. A later final rerun also passed after CLI safety improvements.
- Full PostgreSQL HTTP smoke: 48,001 generated events, three tenants, 30 scenario series. Generation/ingestion/historical evaluation took 84.22 seconds. Added targeted moderate-error and no-traffic integrations exercise all four current states.
- Brightline summary after smoke: HEALTHY 3, DEGRADED 1, UNHEALTHY 6, UNKNOWN 2. The second tenant additionally owns an unobserved private integration and reports UNKNOWN 3. Summary/list counts agree with stored snapshots.
- Healthy, elevated error rate, latency-only degradation, complete outage, intermittent failure, authentication failure, low traffic, recovery, brief spike and sustained bad windows all traversed generation → shared ingestion → database → metrics → snapshots → incidents → API. Sustained moderate latency warnings eventually escalate under the configured policy; successful HTTP responses do not suppress latency degradation.
- The brief spike opened no incident. Recovery opened and resolved an incident only after the configured consecutive clean windows. Moderate 3% errors initially produce DEGRADED. An empty/no-traffic integration is UNKNOWN.
- Ingestion keys authenticated real HTTP batches for separate tenants. Invalid/revoked keys returned 401; cross-tenant and foreign-integration batches returned 403 before writes; ingestion keys could not read monitoring. Repeated 100-record batches produced 100 duplicates without inflating health metrics. Mixed valid/malformed batches returned safe counts/errors; entirely invalid batches returned 422.
- Health/readiness/docs/OpenAPI and allowed/disallowed CORS were checked through HTTP. Same-window evaluations created no duplicate snapshots/incidents. API restart retained the same summary.
- PostgreSQL migrations 001–005 applied on a clean local database. A separate upgrade run preserved v1 demo requests, policy, snapshots, incidents and enrichment through migration 005. Repeated migration runs skipped applied versions. UTC, RLS and concurrent deduplication/evaluation checks passed.
- Compared all ten ORM tables against PostgreSQL: expected columns, named indexes and foreign-key shapes exist. The migration ledger is an additional eleventh table. Tenant/integration/time indexes and the unique open-incident index are present.
- Database outage: `/healthz` remained 200; `/readyz` and summary returned sanitized 503. Restart restored readiness and retained data. The first larger-data attempt was interrupted when its disposable container disappeared; a fresh retained container completed successfully. No application/schema defect was inferred from that interruption.

## Browser validation

Used the actual Next.js production build against FastAPI, first with temporary SQLite and then with local PostgreSQL. Checked counts/table metrics, all-state representation, tenant selection, combined status/type filters, search, empty results, an empty tenant, loading states, details, error/latency/volume histories, transitions, resolved incidents and deterministic reasons. The browser reported no normal-operation errors or warnings.

The DocuSign detail showed 0% errors alongside unhealthy latency, and recovery history showed one clean observation held unhealthy before the next clean observation resolved it. Keyless Generate assistance returned the exact deterministic explanation with suggested checks. A clearly labeled cached local AI mock verified the structured advisory summary, confidence and investigation rendering; this was not a live OpenAI response.

Pausing the isolated API caused the frontend's timeout warning while retaining historical metrics and freshness information. Resuming and retrying restored access. Reload/navigation retained database evidence. The final PostgreSQL-backed dashboard was visually inspected; screenshot saved to `/tmp/brightline-local-e2e.png` for this local session.

## AI, security and performance

OPENAI_API_KEY was absent from the process environment. Missing-key behavior and provider timeout/error, successful structured response and opposing-summary cases passed with local fakes. Core health/incident processing ran without AI throughout. No external provider call was made.

Real environment filenames are ignored and none are tracked. A bounded application-source scan found no OpenAI-key, AWS-access-key or private-key patterns; matched values were never printed. Built browser JavaScript contained none of the backend credential variable names. This is a focused scan, not a full Git-history secret audit. Ingestion secrets are random, hashed at rest and revoked through the trusted CLI; issuance is not exposed as an HTTP administration route. ORM/bound queries preserve tenant scope, and errors/CORS fail safely.

Representative local PostgreSQL read API timings across three calls each were 16–54 ms for summary, integration list, dashboard, recovery detail and metric history. One new current-window evaluation across 12 integrations took 403 ms. The integration list performed four SQL queries for 12 integrations and did not load raw request events. Detail requests cap logs at 50 and history at 288; current list/summary read snapshots. Aggregation uses bounded time ranges and Polars; this was a sanity check, not a load/complexity proof. Per-record insert/savepoint overhead and repeated lookback scans remain scaling limits at much larger traffic volumes.

## Changes and pilot gaps

Added scripts/smoke_test.py and five CLI safety tests, plus this report. The smoke runner is isolated by default, bounds target selection, uses real HTTP and restarts its API, suppresses database exception details and leaves existing/hosted databases untouched. No production domain or frontend mismatch required a code change during this run. Migration 005's driver-format fix from the preceding task was exercised successfully here.

Before a real pilot: define retention/redaction and backup/restore procedures; add ingestion rate/request-size controls and actionable ingestion/scheduler observability; configure private operator access and secure customer credential handoff; validate scheduler cadence, TLS, connection limits and role permissions in the chosen deployment environment. Late events do not rewrite immutable completed decisions; historical correction/replay needs an explicit operational policy. Real connectors and alert delivery remain future work. SSO, queues and adaptive models are outside this MVP.

Local validation is complete and the repository is ready for the next deployment-preparation prompt (Prompt 9). No Vercel work was started. Validation servers and the disposable PostgreSQL container are stopped after testing; Docker Desktop and its cached PostgreSQL image remain available.

Final automated verification: **215 backend tests passed** (including five new smoke-target safety cases), **6 frontend tests passed**, TypeScript check and Next.js production build passed, Ruff import/undefined-name checks and formatting passed, frontend Prettier check passed, Python compilation and Git whitespace checks passed. One upstream Starlette/httpx deprecation warning remains. The final SQLite smoke rerun generated 15,569 events and completed generation/ingestion/historical evaluation in 18.03 seconds; counts vary with the explicit current five-minute anchor, while a fixed seed plus fixed anchor remains reproducible. CI now invokes the secret-free HTTP smoke command; no remote CI run is claimed.
