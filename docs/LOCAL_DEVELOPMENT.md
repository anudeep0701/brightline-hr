# One-command local development

Run `npm run dev` from the repository root. The root package has no npm dependencies: its Node launcher starts the existing FastAPI and Next.js services separately. It uses `.venv` directly, so activating the virtual environment is optional. Node.js 22+ and Python 3.11+ are required.

## One-time dependency setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

On Windows, the virtual-environment Python command is `.venv\Scripts\python.exe`; the launcher selects that path automatically.

## Configuration

The local launcher loads repository-root `.env` and optional `.env.local` at runtime. Nonempty terminal variables take precedence over `.env.local`, which takes precedence over `.env`; blank values are ignored. Only documented application variables are loaded, and values are never logged. It does not create/edit environment files, apply migrations, provision tenants, seed data or start PostgreSQL. Keep every placeholder in `.env.example` blank; that file contains descriptions and defaults only. After one-time setup, run `npm run dev` without exporting the same configuration again. Restart the command after changing configuration.

- **DATABASE_URL** is required. Set your development PostgreSQL/Supabase URI in root `.env` or `.env.local`, or export it in the terminal.
- **APP_ENV** defaults to `demo`. This local launcher allows `demo` or `test`; it refuses production/Vercel execution. In test mode the API requires workspace authentication.
- **CORS_ALLOWED_ORIGINS** defaults to `http://localhost:3000`. If overridden, include that exact origin. Open the dashboard using `localhost` rather than `127.0.0.1` so the origin matches.
- **NEXT_PUBLIC_API_BASE_URL** defaults to `http://localhost:8000`. An override must point to the launcher's backend at localhost or 127.0.0.1 on port 8000. This is a public URL, never a credential.
- **OPENAI_API_KEY** is optional and goes only to the backend child. Core monitoring works without it.
- **OPENAI_MODEL** is an optional backend-only override, defaulting to `gpt-6-luna`. Export `OPENAI_MODEL=gpt-6-luna` before launch to select it explicitly. Restart the backend after changing process configuration.
- **PGPASSWORD** is needed only for the existing local Docker Compose database. The launcher does not start that database.
- **CRON_SECRET** is not required by local demo settings; production/scheduler configuration remains separate.

Keep local configuration at the repository root. The launcher refuses separate `frontend/` environment files because Next.js could independently load backend secrets from them. Backend credentials loaded at the root are removed from the frontend child's environment. This local launcher behavior does not change production deployment or standalone Python CLI tools: those still use process variables, and do not automatically load root environment files. PostgreSQL still requires a workspace access token; loading database configuration does not bypass authentication.

## Connect a PostgreSQL demo workspace

A 401 `Bearer token required` means the backend is reachable but the browser is not authenticated. In a second terminal at the repository root, run:

```bash
npm run demo:access
```

This local-only command uses the same root configuration/precedence as `npm run dev`, then invokes the existing trusted administrator CLI to generate and register an operator workspace token for `brightline`. It prints the token once after persistence succeeds; the database stores only its hash. Copy that token into **Workspace access → Workspace bearer token → Connect** on the dashboard. Do not paste an ingestion or OpenAI key. Browser refresh clears the token, so save it privately for reconnection. Re-running this command creates an additional credential; it does not retrieve old plaintext, seed data or apply migrations. An existing tenant's integrations/data are preserved.

Only the local SQLite demo permits credential-free access. PostgreSQL authentication is retained even with APP_ENV=demo. No application restart is necessary after registering a token.

## Existing SQLite demo

SQLite is already supported for local demo/test use. The exact relative URL from the repository root is `sqlite:///./data/demo-v4.db`; its database file is ignored by Git. Both seeding and the root launcher use the repository root as the backend working directory, so the path resolves consistently.

For macOS/Linux:

```bash
export APP_ENV=demo
export DATABASE_URL=sqlite:///./data/demo-v4.db
.venv/bin/python scripts/seed.py
npm run dev
```

Seeding is one-time, non-destructive setup; existing tenants are preserved. If you have a legacy incompatible SQLite database, select a fresh local filename. The launcher never silently deletes/replaces a database. For a fresh synthetic scenario at the current time, use a fresh ignored database filename and seed it explicitly. SQLite does not change the production PostgreSQL requirement.

PowerShell equivalent:

```powershell
$env:APP_ENV = 'demo'
$env:DATABASE_URL = 'sqlite:///./data/demo-v4.db'
.venv\Scripts\python.exe scripts/seed.py
npm run dev
```

## PostgreSQL setup

Start your existing development PostgreSQL separately. For the repository's local Docker Compose database, first configure PGPASSWORD privately, then disable Compose's automatic environment-file loading:

```bash
docker compose --env-file /dev/null up -d
```

Export DATABASE_URL for that local database and apply migrations explicitly:

```bash
.venv/bin/python scripts/migrate.py
```

Seed only a synthetic development database, or use `scripts/admin.py` to provision a real development tenant and workspace access. Then run `npm run dev`. The launcher makes no database changes during startup and never applies migrations to a hosted database automatically.

## URLs and shutdown

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Backend | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |
| Liveness | http://localhost:8000/healthz |
| Storage/schema readiness | http://localhost:8000/readyz |

Ctrl+C in the root command stops both services. On macOS/Linux, the launcher signals both process groups, lets them shut down and removes any remaining descendants after a five-second grace period. Windows uses taskkill's process-tree termination because POSIX group signals are unavailable. If either service exits unexpectedly, the launcher stops the other and returns failure. Missing configuration/dependencies or occupied ports fail before either service launches. Readiness still requires a reachable, initialized database.

FastAPI reload watches `backend/app`; Next.js retains its normal development hot reload. Production uses one root Vercel Services configuration with independent frontend/backend builds and same-origin API routing. Local development keeps its existing two ports.

## Verification

`npm test` at the repository root checks configuration fail-fast behavior, local URL/CORS boundaries and removal of backend secrets from the frontend environment. Existing backend/frontend suites remain separate. Actual startup, browser-to-API requests and Ctrl+C cleanup are additionally verified locally against an isolated seeded SQLite database; the launcher does not require OpenAI.

Verified on macOS: root `npm run dev` launched Uvicorn with reload on port 8000 and Next.js dev on port 3000 against an isolated 5,079-event SQLite dataset. Browser requests loaded all ten integrations without console errors; healthz, readyz, docs/OpenAPI and configured CORS returned successful responses. Sending Ctrl+C to the root terminal exited successfully, released both listening ports, and exited the backend reloader and worker. All 215 backend tests, six frontend tests, four root-launcher tests and TypeScript checks passed. No environment file, hosted database or production deployment configuration was changed. Windows path/process-tree support is implemented but was not runtime-tested on this macOS host.

PostgreSQL requires a tenant-scoped workspace token for dashboard/AI/operator access even with `APP_ENV=demo`. Only the explicitly selected SQLite demo permits credential-free synthetic tenant access. Provision the workspace token using the existing trusted `scripts/admin.py` CLI, then connect it through the dashboard's workspace access control.
