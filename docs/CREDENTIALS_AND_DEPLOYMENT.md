# Supabase first, then one Vercel application

The deployment uses one Vercel project and domain. The root `vercel.json` defines independently built Next.js and FastAPI services. [Vercel Services](https://vercel.com/docs/services) is currently in beta; this is a supported configuration, with hosted preview validation required before pilot use.

Only blank `.env.example` belongs in Git. Real credentials go in process environment or Vercel project variables. Standalone Python administration commands do not load environment files. The existing local `npm run dev` launcher still loads root configuration for the user and filters backend credentials out of its frontend child.

## 1. Prepare Supabase before deploying

Use a dedicated Supabase project/database for this pilot. Keep preview and customer data separate.

1. In Supabase, open **Connect**. Obtain the PostgreSQL URI and URL-encode its password. Use the transaction pooler for the serverless runtime, with `sslmode=require` (or verified TLS with the appropriate CA configuration). The existing SQLAlchemy engine uses `NullPool` and `prepare_threshold=None`. See [Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres).
2. Privately export `DATABASE_URL` into your trusted administration terminal. Do not paste it into chat, source files or command output. For migrations, use a direct/session connection if required by network or administrative permissions. Use the transaction URI as Vercel's runtime value afterward.
3. From the repository root, apply the pending migrations:

   ```sh
   .venv/bin/python scripts/migrate.py
   ```

   The runner applies numbered migrations transactionally and checks stored digests. It preserves existing demo data on compatible PostgreSQL schemas. A changed applied migration fails rather than silently rewriting history. Check backups and the target database before administering an existing customer database.
4. Run the same command again to verify migration state. A successful run with no “Applied” lines means all existing migration digests match.
5. Register the tenant/integration and issue a workspace token:

   ```sh
   .venv/bin/python scripts/admin.py brightline 'Brightline HR' \
     --integration workday-payroll --generate-token
   ```

   Save the entire once-displayed token privately. After the application is available, enter it under **Workspace access → Workspace bearer token → Connect** without `Bearer`. It stays in browser memory; refresh clears it. The database stores its SHA-256 digest. An existing tenant is preserved; each invocation issues another token. Repeat with a new integration ID to register additional systems, or `--role reader` for read-only access. CLI-created integration metadata can be refined through trusted administration.
6. Issue the separate ingestion-only credential:

   ```sh
   .venv/bin/python scripts/ingestion_keys.py create brightline \
     --name 'Customer exporter'
   ```

   Save its entire once-displayed value in the exporter secret store. Only a domain-separated SHA-256 digest is persisted. It cannot read the workspace or request AI assistance. See [external ingestion](EXTERNAL_INGESTION.md) for revocation and request examples.

No Supabase service-role, publishable or anonymous API key is needed: FastAPI connects directly to PostgreSQL. No database migration runs during builds or requests. Only explicitly enabled demo sessions may generate bounded synthetic telemetry as described below.

If `DATABASE_URL` is not exported, administration commands fail clearly. A secret present only in a prohibited/unread environment file is not available to a review session; the hosted database must then be configured manually before deployment.

## 2. Configure the single Vercel project

Push the repository to your Git provider and import it **once** into Vercel. Configure:

- **Root Directory:** `.` (repository root), not `frontend` or `backend`.
- **Framework preset:** allow Services configuration; do not force a single Next.js or FastAPI project preset. If the import screen requires a project-level choice, use Other with its command/output overrides cleared.
- **Project-level Install / Build / Output overrides:** unset. Service settings in the root `vercel.json` own these.
- **Node.js:** 22+; backend Python is selected by `backend/.python-version` (3.12).

| Service | Root | Framework | Install | Build / entrypoint |
| --- | --- | --- | --- | --- |
| frontend | `frontend/` | Next.js | `npm ci` | `npm run build` |
| backend | `backend/` | FastAPI | Automatic; `requirements.txt` | `index:app`; framework-managed Python build |

Do not add a backend install override in Vercel or `vercel.json`: custom Python installation disables Vercel's dependency optimization. `backend/requirements.txt` pins the runtime dependencies; `backend/requirements-dev.txt` adds local servers, tests, lint and synthetic generation. Install the latter for local development. The previous combined lock was replaced by these two pinned files. Pytest settings moved to `backend/pytest.ini` so an empty project manifest cannot take precedence over requirements discovery. The Python version remains pinned in `.python-version`.

The backend function excludes tests, caches, local environments and SQLite files through service-scoped `functions.excludeFiles`. Frontend assets, repository documentation and synthetic datasets are outside the backend service root. Runtime application source and migrations remain available. Polars is retained for request-time metric aggregation; NumPy, Faker, pytest and Pygments are local tooling only. OpenTelemetry's API package remains because the pinned FastAPI version requires it.

The Linux runtime still exceeds 225 MiB before packaging, mainly because of Polars. Automatic installation lets Vercel package an optimized function and install selected public dependencies at cold start. A local build with the official Python builder produced a 114.13 MiB function from a 232.30 MiB pre-optimization bundle. This adds a cold-start dependency download and initialization cost; verify first-request latency in the hosted deployment. Do not restore a custom install command to work around it. See [Vercel's Python bundling documentation](https://vercel.com/docs/functions/runtimes/python#controlling-what-gets-bundled).

There is no nested backend `vercel.json`, legacy `builds` array, external backend URL rewrite, custom ASGI wrapper or Next.js API proxy. The Python domain remains in `backend/app`.

Set these project environment variables for each intended deployment environment:

| Variable | Configuration |
| --- | --- |
| `DATABASE_URL` | Supabase PostgreSQL runtime pooler URI with TLS; required |
| `APP_ENV` | `production`; required on Vercel, including previews |
| `CRON_SECRET` | Independent random secret of at least 32 characters; required |
| `OPENAI_API_KEY` | Optional server-side project key; monitoring works without it |
| `OPENAI_MODEL` | Optional override; default `gpt-6-luna` |
| `NEXT_PUBLIC_API_BASE_URL` | Leave unset for this deployment; production uses the current browser origin |
| `CORS_ALLOWED_ORIGINS` | Leave unset; same-origin production grants no cross-origin browser access |
| `PGPASSWORD` | Not required; only used by optional local Docker Compose |
| `DEMO_MODE` | Default `false`; set `true` only for the public synthetic assessment |
| `DEMO_TENANT_SLUG` | Existing demo tenant ID (`brightline`), required when demo mode is enabled |
| `DEMO_ALLOW_FILE_IMPORT` | Default `false`; opt in with `true` for previewed, tenant-scoped synthetic assessment imports |
| `DEMO_SESSION_SECRET` | Independent random signing secret of at least 32 characters; backend-only, required in demo mode |

Services share project variables. This is not a per-service secret boundary: trusted Next.js server/build code can also see project secrets. The frontend references no backend credentials, and only `NEXT_PUBLIC_` values are bundled for the browser. Never rename a secret with that prefix. Use separate projects if separate service trust/administration becomes a requirement.

For optional AI, use an existing authorized OpenAI project key or create one through [OpenAI Platform](https://platform.openai.com/api-keys), then set it as the server-only project variable. Verify model access separately. Briefs use structured fact/check selection, no tools, an eight-second timeout and deterministic fallback. See [AI operations](AI_OPERATIONS.md).

## 3. Public routing and authentication

The [service routing table](https://vercel.com/docs/services/routing) preserves original paths, query strings, bodies, methods and Authorization headers:

| Public path | Owner |
| --- | --- |
| `/api`, `/api/*` | FastAPI, including compatibility routes, ingestion, uploads, AI and evaluation |
| `/healthz`, `/readyz` | FastAPI probes |
| `/docs`, `/docs/*`, `/redoc`, `/openapi.json` | FastAPI documentation/schema |
| `/`, `/integrations/*`, `/data-sources`, `/_next/*`, other application paths | Next.js |

A missing backend route returns the backend's 404; it does not fall through to Next.js. `/api` prefixes are not stripped, so backend route definitions and OpenAPI URLs remain unchanged.

Workspace reader/operator authorization, tenant scoping, ingestion-only keys and cron authorization remain independent. CORS is not authentication. External exporters can POST to `https://<app-domain>/api/ingest` with their ingestion key. If Vercel Deployment Protection is enabled, configure approved exporter access as well as application authorization; do not make a protected preview the production ingestion target.

Local `npm run dev` still starts ports 3000 and 8000 and configures exact localhost CORS. An explicit local API override remains supported. Do not carry a localhost API override into the Vercel production build.

### Hosted assessment access

For the existing case-study Vercel project, open **Settings → Environment Variables** and add `DEMO_MODE=true`, `DEMO_TENANT_SLUG=brightline` and `DEMO_SESSION_SECRET` for **Production**. Generate the signing value in a password manager (at least 32 random characters); use a different value from `CRON_SECRET`. Keep `APP_ENV=production` and existing database/AI/cron variables. Do not add a public API URL or any `NEXT_PUBLIC_` secret. Redeploy after saving the variables. Never enable this mode against customer telemetry: the configured workspace's evidence and AI assistance become publicly accessible.

The `brightline` tenant and its synthetic integrations/events must already exist in the dedicated assessment database. The session endpoint never creates tenants or integrations. If only a minimal integration has been provisioned, **Refresh demo data** registers missing fixed assessment scenario integrations in this tenant before generating their events. Existing metadata/policies remain unchanged; the same 12-integration ceiling applies. If synthetic telemetry or evaluation is overdue, it generates at most 96 events per integration (12 integrations maximum) relative to the current UTC bucket, then calls normal ingestion and evaluation. A tenant lock and stable per-bucket request IDs bound concurrent/repeated entry. Deliberately stale scenarios, live telemetry and file imports are preserved. Missing tenant/signing configuration fails startup; a nonexistent tenant returns a safe unavailable response. Tenant selection is server configuration, not a request parameter.

On entry, the frontend reads `GET /api/demo/session`, then calls `POST /api/demo/session` only when enabled. The server sets a signed `__Host-brightline_demo` cookie with **HttpOnly, Secure, SameSite=Lax**, `Path=/` and a one-hour lifetime. Responses contain only workspace metadata and expiry, never a workspace bearer token or signing value. Signing uses domain-separated HMAC-SHA256 with no session table or third-party authentication service. Every request rechecks the configured tenant and expiry. Changing the secret invalidates all sessions; disabling demo mode stops cookie access. Individual session revocation is intentionally not implemented.

The page renews sessions every 20 minutes while visible; an expired request gets one renewal/retry, without redirects. Refreshing the page opens the same configured workspace automatically. These cookies require HTTPS in hosted use; local browser validation uses localhost's secure-cookie support. Cross-site writes are rejected through origin checks and a required custom request header. Production grants no cross-origin demo access.

Demo access permits health/integration/metric/incident reads, Data Sources inspection, grounded AI briefs/questions and tenant-scoped **Evaluate now**. A server-side capability allowlist rejects log writes, policy changes and credential/admin operations. Imports are denied by default; `DEMO_ALLOW_FILE_IMPORT=true` permits only the existing preview/confirm workflow in the configured tenant, with the same 2 MiB/1,000-record file limits and a 3,000-record demo import cap. Uploaded tenant IDs cannot change scope. Server-generated batch IDs mark imports; an owner can run `.venv/bin/python scripts/demo_cleanup.py --confirm` to remove only those tagged imports in the configured demo tenant. No public cleanup or credential administration endpoint exists. History is preserved; subsequent evaluation reflects cleanup in a new bucket. Upload only synthetic assessment data because the shared workspace is publicly visible. It does not grant `/api/ingest` or cron access. Existing ingestion keys and workspace bearers retain their independent authorization. The local launcher strips the signing secret from the frontend process; the frontend never references it. In Vercel Services, project variables remain shared with trusted build/server processes, but are not browser configuration.

When `DEMO_MODE` is false, the session endpoint cannot issue a cookie, existing demo cookies confer no access, and the hosted UI retains **Workspace access**. Real customer deployments should leave all demo settings unset. Existing credential-free local SQLite demo behavior remains a separate local-only workflow.

## 4. Scheduled evaluation

The case-study deployment uses Vercel Hobby, so health evaluation can be triggered on demand and any configured Vercel cron is limited to a Hobby-compatible cadence. The intended production operating cadence is approximately five minutes and would use a production-capable scheduler.

The committed root config has **no cron entry**, including no daily cron. A daily job would not provide the intended operational freshness and would unnecessarily advance a static demo without new telemetry. An authenticated workspace operator uses **Evaluate now**, which calls `POST /api/evaluate`, evaluates only that tenant through the existing service, and reloads the dashboard. The button is disabled for readers and while work is running; failures are shown in the dashboard. It never uses or receives `CRON_SECRET`.

**Keep `CRON_SECRET` configured in Vercel**, even on Hobby: existing production settings still require at least 32 characters. `GET /api/cron/refresh` remains protected and available for future production scheduling. No/incorrect secret returns 401; locking, idempotency, tenant evaluation and incident confirmation/recovery are unchanged. Scheduler choice does not change the health policy.

For intended production on a suitable paid scheduling tier, add this top-level entry to the root `vercel.json`:

```json
"crons": [{ "path": "/api/cron/refresh", "schedule": "*/5 * * * *" }]
```

Alternatively, an approved production scheduler can invoke the same HTTPS endpoint with server-held bearer authorization. Do not put that secret in browser code. Confirm [Vercel plan limits](https://vercel.com/docs/cron-jobs/usage-and-pricing) and actual invocations before operational adoption. Cron executes in production, not previews. Current cross-tenant scheduling is bounded to 100 tenants.

Manual evaluations remain subject to configured buckets: repeated clicks in one bucket do not advance streaks, and skipped buckets break continuity. Static/old demo traffic will become UNKNOWN; on-demand evaluation does not manufacture recent telemetry or preserve old healthy states. In the explicit public demo, **Refresh demo data** generates fresh synthetic events through normal ingestion and evaluates them; it is separate from **Evaluate now**. Demo session entry also repairs stale baseline feeds, but never overwrites historical decisions or rewrites timestamps. Daily scheduling is optional but intentionally not configured.

## 5. Release verification

After an approved deployment, check:

1. `/healthz`, `/readyz`, `/docs` and `/openapi.json` resolve on the same domain as the dashboard.
2. `/api/workspace` returns 401 without a token; a valid workspace token loads only its tenant.
3. A recent production-style `/api/ingest` batch accepts valid events; replay reports duplicates; a foreign tenant/integration is rejected.
4. An operator can call `/api/evaluate`; repeated same-bucket evaluation does not advance incidents.
5. The dashboard and detail pages load same-origin evidence, including file-import validation and confirmation.
6. AI brief/investigation requests show deterministic fallback without an OpenAI key. Verify live provider access separately if AI is enabled.
7. Unauthenticated cron calls return 401. For the Hobby demo, authenticated operator evaluation succeeds without any scheduler. For enterprise operation, verify recurring scheduled calls succeed and keep evidence fresh.

Git pushes deploy both services together; previews and application rollbacks are atomic across the two builds. Database migrations remain manual and are not rolled back with application code. Services beta, shared project configuration and coupled release cadence are the trade-offs for one domain and one deployment. No hosted deployment has been verified by local tests alone.
