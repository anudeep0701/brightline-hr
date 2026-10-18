# Verification record

## Python deployment bundle reduction — 2026-10-18

- Split pinned runtime requirements from local test, synthetic-generation, lint and server tooling. Removed the stale combined lock/range manifest; moved unchanged pytest configuration to `backend/pytest.ini` to avoid a competing dependency-free project manifest. CI and local setup use `requirements-dev.txt`.
- Removed the backend custom install command. Service-scoped function exclusions omit tests, caches, local environments and SQLite artifacts. Domain source, migrations, API contracts, service routing and frontend build settings are unchanged.
- On Linux x86-64 / Python 3.12, a clean production-only installation passed `pip check`, startup, database access, Polars health evaluation, workspace authentication, tenant isolation, external ingestion/deduplication, CSV preview/import, AI fallback, operator refresh and cron authorization. No pytest, Faker, NumPy, Pygments, Ruff or Uvicorn was installed in that runtime.
- The official `@vercel/python` 25.1.3 builder ran locally in a disposable Linux container, using the existing exported app and production requirements. It measured **232.30 MiB before optimization** and **114.13 MiB for the optimized function**. This is a local packaging result, not a hosted size guarantee. Vercel may install selected public dependencies at cold start; that cost remains to be measured on the host.
- Largest installed runtime packages before optimization: Polars native runtime **171.85 MiB**, psycopg binary **18.99 MiB**, SQLAlchemy **17.29 MiB**, OpenAI **6.14 MiB**, Pydantic core **4.96 MiB** and Polars Python package **4.09 MiB**. Polars is used by live metric aggregation; OpenTelemetry API is a FastAPI dependency. Neither was removed.
- **312 backend**, **35 frontend** and **14 launcher/deployment tests passed**. Ruff F/I, frontend lint, TypeScript, isolated production Next.js build, Vercel configuration schema and whitespace checks passed. One upstream Starlette/httpx deprecation warning remains.
- Real HTTP smoke passed with **16,870 synthetic events**, covering all four health states, incidents/recovery, ingestion, uploads, auth and fallback. A separate same-origin gateway check against the production frontend build passed frontend/backend routing, probes/docs, workspace authorization, tenant boundaries, external ingestion/idempotency, evaluation, AI fallback and cron authorization.
- Tracked-path and credential-pattern audits found no secrets or local credential databases; only intentional invalid-URI fixtures matched. No real environment file, hosted database or OpenAI API was accessed. Git push and hosted deployment results are reported separately.

## Vercel Hobby refresh adaptation — 2026-10-18

The committed Hobby deployment contains no scheduled cron, including no daily job. Workspace operators use the existing **Evaluate now** action and `POST /api/evaluate`. The backend cron endpoint, secret checks, locks, idempotency, tenant evaluation and health thresholds are unchanged. Production settings still require `CRON_SECRET`; it remains server-only. Intended enterprise evaluation cadence remains approximately five minutes with a capable scheduler.

- Backend: **312 passed**, including a new regression proving manual refresh requires an operator, cannot cross tenants, is idempotent within a bucket, and does not grant workspace tokens cron access. The real cron secret still permits the existing global scheduler path.
- Frontend: **35 passed**. Existing button state, progress/error handling and dashboard reload were verified in source; no new UI or domain logic was introduced.
- Launcher/deployment: **13 passed**, including no Hobby cron and preserved routing for both operator and scheduler endpoints.
- Ruff F/I, frontend lint, TypeScript and isolated production Next.js build passed. Production entrypoint/startup and unauthenticated cron rejection passed with no environment files loaded.
- Real HTTP smoke passed with **16,726 synthetic events** in temporary SQLite. It covered probes/docs/CORS, workspace and ingestion authentication, tenant isolation, retries, malformed records, all four health states, incident recovery, AI fallback, file imports and restart.
- Additional same-origin HTTP validation against the new production build passed frontend routing, probes/docs, workspace authorization, tenant boundaries, live ingestion/deduplication, health evaluation, AI fallback and protected cron invocation. This was a disposable local gateway using the committed route table, not a hosted Vercel deployment. Review servers were stopped afterward.
- Tracked-path and credential-pattern checks found no real environment files, local credential databases, virtual environments, dependency trees or live credentials. Only intentional invalid-URI fixtures matched. Frontend source and production browser bundles contain no `CRON_SECRET` reference. No environment file or hosted database was accessed.
- GitHub's existing commit had passing CI but no Vercel statuses/deployment records were visible. No Vercel CLI, local project link or authenticated Vercel browser session was available. Git push/deployment outcomes are reported separately; a passing local build does not establish a hosted deployment.

## One-project deployment adaptation — 2026-10-16

The current deployment target is one root Vercel Services project. The previous independent-project deployment instructions are superseded. Services is a first-party beta feature; no hosted build/deployment has been run.

- Root `vercel.json` defines independent Next.js/FastAPI builds and ordered service rewrites. `/api/*`, probes and API documentation retain their original backend paths; other requests reach Next.js. The cron definition moved from the removed nested backend config to the root.
- Production browser requests default to the current origin. The existing local launcher still supplies port 8000. API authorization and file-confirmation headers are unchanged. The Live API sample resolves to the current public app origin after mounting.
- Production defaults to no CORS grants; safe localhost CORS remains the local default. Explicit cross-origin production grants still require exact HTTPS origins.
- **299 backend tests, 35 frontend tests and 12 launcher/deployment-contract tests passed.** Ruff F/I, frontend Prettier lint, TypeScript, and the isolated production Next.js build passed. The build used no API URL override and no environment files.
- Existing real-HTTP smoke passed with 15,805 seeded events, authenticated ingestion, tenant isolation, all four health states, recovery, uploads, provenance, AI fallback and process restart. Production entrypoint import/startup also passed with no OpenAI credential or CORS configuration.
- A disposable same-origin ingress driven by the root rewrite table passed real HTTP checks for Next.js pages/assets, probes/docs, workspace authentication, cross-tenant rejection, external ingestion and duplicate retries, health reads/evaluation, all three AI endpoints with fallback, and cron authorization. The browser loaded authenticated overview/onboarding and a Live API sample using its current origin with no console errors. This verifies the local routing contract, not Vercel cloud execution. All temporary services were stopped afterward.
- The root config passed the downloaded official Vercel schema with a modern JSON Schema validator. The published schema advertises draft-04 while containing newer constructs; draft-7 validation was used to retain those constructs. Validation tooling was installed only in temporary storage, not project dependencies.
- README, solution design, local-development and deployment documentation now describe one project. All eight example placeholders remain blank; no new variable was introduced.
- Supabase was not configured in this session: `DATABASE_URL` was absent from process environment, and the user explicitly prohibited inspecting `.env`. The deployment guide puts migration verification and credential provisioning before Vercel import. No hosted database was modified.

## Final engineering review — 2026-10-16

Ready to commit and prepare a case-study deployment, subject to hosted configuration and post-deployment checks. No hosted deployment or Supabase migration was performed. No real environment file was read or modified. Existing local services were left untouched.

| Check | Actual result |
| --- | --- |
| Backend tests | `.venv/bin/python -m pytest -q backend/tests` — 292 passed; one upstream Starlette/httpx deprecation warning |
| Frontend tests | `npm --prefix frontend test` — 31 passed, including the new low-volume UNKNOWN regression |
| Launcher tests | `npm test` — 10 passed |
| Lint / types | Ruff `--select F,I`, frontend Prettier lint and TypeScript all passed |
| Production frontend build | `npm run build` passed in an isolated copy, with no environment files copied and the installed dependencies shared; all three product routes built |
| Backend startup | Deployment entrypoint import, real Uvicorn startup and clear missing-DATABASE_URL failure verified |
| Real HTTP pipeline | `scripts/smoke_test.py --port 8012` passed with temporary SQLite, 15,605 seeded events and OpenAI disabled |
| PostgreSQL | `scripts/check_postgres.py` passed on disposable PostgreSQL 16: legacy upgrade through 006, repeat migration, UTC, RLS, concurrent deduplication and evaluation |
| Browser | Isolated production frontend reached the temporary API; overview, unhealthy detail, deterministic fallback and data onboarding inspected; no console warnings/errors |
| Configuration / documentation | Eight blank example variables verified; README CLI options and local links checked; solution design compared with current policy, lifecycle and AI services |
| Secret hygiene | Real environment paths ignored and absent from tracked files/history filenames. Source pattern scan found only intentional invalid-credential test fixtures; no live credential was found. This was not an exhaustive secret-scanning service audit. |
| Dependencies / whitespace | `pip check` and `git diff --check` passed |

The backend suite covers reproducible generation, all four deterministic states, latency-only failure, minimum volume, stale telemetry, hysteresis, recovery, idempotency, partial validation, tenant isolation and absent/failed/malformed AI responses. The HTTP smoke also covers credential revocation, file preview/confirmation, provenance and API restart. AI provider calls remain mocked or disabled; live model access has not been validated.

Review fixes: corrected the dashboard's insufficient-request reason-code match; added its regression test; clarified README confirmation semantics; added frontend lint to CI; corrected stale model, environment-loading and credential commands in the deployment guide. No health-policy or backend API behavior changed.

No unfinished application TODO/FIXME stubs were found. Nonblocking cleanup remains: the legacy generator entrypoint, test-covered legacy AI helper and historical priority helper are retained; `autoprefixer` is an unused direct development dependency under the current Tailwind PostCSS configuration. The Python lock also includes demo/test dependencies in the deployment installation. None prevented the local build; the first hosted build must verify its actual bundle and execution limits.

Deployment prerequisites: configure a Git remote (none is currently configured), commit all required new files, provision Supabase and workspace/ingestion credentials, and configure the root Vercel Services project. The five-minute cron requires a compatible plan (Pro/Enterprise); Hobby cannot deploy that schedule. Confirm hosted readiness, CORS, browser authentication and cron execution. See [deployment steps](CREDENTIALS_AND_DEPLOYMENT.md).

Pilot gaps remain: real traffic calibration, provider exporters, SSO/membership RBAC, managed credential lifecycle, rate controls, retention/redaction, backup/restore, alert delivery, operational observability and load testing. Operational durations and health percentages are calculated; customer ROI and ticket-based MTTD are not established.

## Earlier implementation checks

The entries below are historical checkpoints, not current test totals or current verification limitations.

Implemented and verified locally on 2026-10-15:

- Pytest: 36 passed. One upstream Starlette/httpx deprecation warning; no failing tests.
- Frontend TypeScript check: passed.
- Next.js production build using Webpack: passed for dashboard and dynamic integration detail route.
- npm audit: zero reported vulnerabilities in the installed dependency tree.
- Ruff import/undefined-name checks: passed; Python and frontend sources formatted.
- Browser verification: desktop and narrow layouts, integration search, Gusto detail evidence, and keyless explanation fallback.
- Synthetic seeding: 8 integrations, 30,204 request records and 25 historical evaluation buckets.
- Secret hygiene: six blank placeholders in `.env.example`; no real environment files created; real env paths, database files and credentials excluded from Git.

Not verified in this environment:

- PostgreSQL execution, migration application and concurrent refresh: local Docker daemon is unavailable. A dedicated PostgreSQL GitHub Actions job runs `scripts/check_postgres.py` after migrations; no CI run has been claimed.
- Live OpenAI behavior: no key was supplied. The SDK path is tested with mocks; no paid API requests were made.
- Supabase/Vercel deployment: no cloud credentials or Git remote were supplied. Deployment configuration and instructions are provided.

The default Turbopack production build hit a restricted process/port error during final checks. The documented `next build --webpack` production build passed. Preview servers started for browser verification were stopped afterward.


Database/ingestion follow-up:

- All seven requested table models are present; v2 PostgreSQL migration preserves legacy records and creates configuration/rollup links.
- Partial record acceptance and database conflict handling are shared by API, JSON/JSONL/CSV import and demo seed.
- Local backend regression suite: **79 passed** (one upstream Starlette/httpx deprecation warning). Covers UTC, file retry, config persistence, schema initialization, required environment configuration and tenant ownership constraints. Ruff checks and Python compilation passed.
- PostgreSQL migration/backfill and concurrency checks are updated in CI; Docker remained unavailable locally. No supplied database credentials were read from `.env.local`, and no hosted database migration was performed.


Health-engine follow-up:

- Policy defaults now persist in integration_config; metrics, non-overlapping baselines, uppercase observed/stabilized states, evidence sufficiency, reason codes/text and state counters are implemented. Final backend suite: **112 passed** (one upstream Starlette/httpx deprecation warning); Ruff and Python compilation passed.
- Synthetic scenarios are replayed against confirmation/recovery hysteresis. Additional tests cover configured cadences, gaps, configuration changes, recovery margins, re-opening and an AI client that must not be called.
- Frontend typecheck and production build passed after adapting uppercase API states and rendering stored threshold values.
- PostgreSQL migration 003 is supplied for policy/result columns and historical status conversion. Local PostgreSQL execution remains unavailable while Docker is stopped; no hosted schema changes or live AI calls were made.


Optional AI-enrichment follow-up:

- Backend suite: **130 passed** (one upstream Starlette/httpx deprecation warning). Tests cover structured success, missing credentials, connection/timeout/provider failures, refusal and incomplete output, schema and category grounding, exact reason_text fallback, evidence privacy, tenant/time-scoped comparison and incident context, cache reuse and legacy regeneration. All provider calls are mocked; no supplied credentials were read or used.
- Frontend TypeScript check and production build passed with structured investigation checks, issue hypothesis, advisory confidence and what-changed rendering. This UI extension was build-checked; the earlier browser verification above predates it.
- Ruff import/undefined-name checks, Python compilation and Git whitespace checks passed.
- Additive PostgreSQL migration 004 and CI upgrade assertions preserve legacy enrichment explanations. PostgreSQL execution remains unverified locally because Docker is unavailable. No hosted migration or live OpenAI call was made.
- No environment files were created or modified for this feature; `.env.example` placeholders remain blank. The backend alone reads OPENAI_API_KEY from its process environment.


Public FastAPI surface follow-up:

- Backend suite: **162 passed**, including 32 new public-API contract and boundary cases (one upstream Starlette/httpx deprecation warning). Covers probes, missing schema columns, storage failures, safe error envelopes, reader/operator permissions, tenant filter isolation, query validation, latest-state filtering, half-open time boundaries, activity-overlapping incidents, bounded pagination, idempotent ingest/evaluate, keyless and mocked successful enrichment, CORS preflight and OpenAPI schemas.
- Isolated file-backed SQLite smoke test generated one tenant, ten integration series and 5,510 events. All public GET routes, compatibility dashboard, all ten keyless explanations and repeated current evaluation passed. Observed summary: three HEALTHY, six UNHEALTHY, one UNKNOWN. Temporary database was removed after verification; existing local data was untouched.
- Ruff checks, Python compilation and Git whitespace checks passed. No frontend source changed for this API task; existing dashboard routes retain their contracts.
- API work introduced no database migrations, environment variables or external infrastructure. No environment files were created/edited and no live OpenAI request or hosted PostgreSQL migration was made. PostgreSQL runtime verification remains delegated to the supplied isolated CI job.


Operations dashboard follow-up:

- Backend suite: **165 passed**, including authorized workspace/tenant metadata, SQLite-only demo selection, prevention of PostgreSQL demo tenant selection, previous snapshots and cached enrichment reads that cannot invoke AI (one upstream Starlette/httpx deprecation warning).
- Frontend: **6 presentation-helper tests passed**, TypeScript check passed, production build passed. GitHub Actions now includes the frontend tests. Ruff, Python compilation and whitespace checks passed.
- Browser QA covered initial loading, four recorded status counts, empty status results, combined healthy/payroll filters, demo tenant switching and tenant-preserving navigation, recovery metrics/state transitions/resolved incidents, keyless assistance, current-window evaluation, invalid-token errors and restored access. Stopping the backend and reloading retained prior evidence with an explicit failure/freshness warning. Desktop 1440px and mobile 390px DOM layout checks showed no body overflow; the normal preview was visually inspected after tightening the mobile header. Temporary viewport overrides were reset.
- Preview data came from the new temporary keyless launcher: three synthetic tenants, thirty integration series and 25,160 events. The owned frontend/backend servers were stopped and the temporary database removed after QA. Screenshot proof is available at `/tmp/brightline-dashboard.jpg` on this host.
- No real environment file, existing local database or hosted database was modified. No live OpenAI call was made. PostgreSQL/Supabase/Vercel runtime verification remains outside this local UI check; the supplied CI PostgreSQL job covers migration/concurrency behavior when run.


Business-behavior testing follow-up:

- Added eleven API-level acceptance cases using fixed UTC time, an explicit advancing clock and NumPy seed 42. They exercise the real ingest → metrics → health → incident path, not a mocked health result.
- New checks cover healthy/moderate/sparse traffic, severe latency without errors, consecutive bad windows, repeated-evaluation idempotency, isolated spikes with raw-event preservation, borderline recovery resets, two-window resolution, malformed/duplicate batches, provider outage recovery, opposing AI summaries with unchanged decisions, and same-ID tenant isolation.
- An autouse guard prevents accidental OpenAI client construction unless a test installs an explicit offline fake. No production/application business code changed for this testing task.
- Final verification: **176 backend tests passed**, **6 frontend behavior tests passed**, Ruff checks and whitespace checks passed. One upstream Starlette/httpx deprecation warning remains. PostgreSQL CI/hosted execution was not run locally; no real environment file or external API was used.

External ingestion follow-up:

- Added ingestion-only tenant keys, hash-only storage, issuance/list/revocation CLI and migration 005. Canonical authenticated ingestion enforces scope before writes and returns safe partial-validation results; generated/file/API ingestion shares one domain service.
- **210 backend tests passed**, including 34 external-ingestion cases; **6 frontend tests passed** and TypeScript checks passed. One upstream Starlette/httpx deprecation warning remains.
- PostgreSQL migration/RLS and credential lifecycle checks are updated for isolated CI, but were not executed locally or against hosted storage. No external API calls, key provisioning or real environment-file changes were performed. No new environment variable is required.

Local end-to-end follow-up (2026-10-16):

- See [local validation report](LOCAL_VALIDATION.md) for exact commands, phase evidence and pilot gaps. No hosted database, real environment file or live AI provider was accessed.
- **215 backend tests**, **6 frontend tests**, TypeScript, production build, Python lint/formatting, frontend formatting, Python compilation and whitespace checks passed.
- Actual PostgreSQL 16 clean migration and legacy-data upgrade/concurrency checks passed locally, including migration 005. The 48,001-event, three-tenant HTTP smoke run passed; actual browser checks covered SQLite and PostgreSQL-backed API responses, keyless assistance, a labeled cached AI mock, empty/loading/error states and recovery.
- Added a safe local smoke CLI and five hosted-target/secret-echo guard tests. CI invokes the HTTP smoke workflow; no remote CI run or deployment is claimed.

One-command developer launch follow-up:

- Root `npm run dev` supervises the existing FastAPI and Next.js dev commands without adding dependencies or changing deployment roots. It checks required configuration/dependencies/ports before spawning and removes backend credentials from the frontend environment. Environment-file contents are never loaded.
- Actual macOS startup/browser/API/CORS checks and terminal Ctrl+C shutdown passed against an isolated SQLite dataset. Both ports and Uvicorn reloader/worker processes were released. Windows process-tree support is implemented, not claimed as runtime-tested.
- **215 backend**, **6 frontend** and **4 launcher tests** passed; TypeScript and formatting/whitespace checks passed. See [local development](LOCAL_DEVELOPMENT.md) for setup, exact SQLite syntax and environment requirements. `.env.example` remains blank with explanatory comments.

Grounded AI operations follow-up:

- Added fact-constrained incident briefs, six fixed-topic copilot questions, compact persisted audit metadata, recovery evidence/summary and explicit live freshness alongside immutable recorded decisions. No new table, migration, environment variable or infrastructure was added; no real environment file or hosted database was accessed.
- **246 backend tests**, **10 frontend tests**, **4 launcher tests**, TypeScript, production build, Ruff/import checks, formatting, compilation and whitespace checks passed. All earlier tests remain intact. One upstream Starlette/httpx deprecation warning remains.
- Actual browser checks covered unhealthy brief generation, audit metadata, focused error-driver fallback, resolved opening/recovery/condition details and selected-resolution recovery fallback with no console errors. The extended real-HTTP SQLite smoke passed with 15,237 generated events, including brief and recovery routes, while OpenAI was disabled.
- Positive/malformed/malicious/provider-failure responses are tested through local provider fakes. No live OpenAI request was made. Regular demo `--enable-ai` explicitly permits use of an already-exported backend key through the normal API, rather than a separate AI demo implementation. See [AI operations](AI_OPERATIONS.md) for design, evaluator steps and audit limits.
