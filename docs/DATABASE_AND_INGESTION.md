# Database and ingestion

External exporters should use the [ingestion-only credential contract](EXTERNAL_INGESTION.md). Migration `005_ingestion_api_keys.sql` adds tenant-scoped hash-only credentials with revocation and RLS. Ingestion-key batches reject tenant/integration violations atomically with 403; all-invalid batches return 422. The operator-compatible behavior described below remains available through the same domain service.

## Configure and initialize

`DATABASE_URL` is mandatory and read only from the process environment. A missing or blank value produces an actionable startup/CLI error; there is no implicit SQLite fallback. Production requires PostgreSQL. No environment file is automatically read or written by the database/import scripts. If you use an existing ignored `.env.local`, explicitly load its values into the process through your own environment tooling. Uvicorn can explicitly load it with `--env-file` when starting the API.

Set `DATABASE_URL` privately to the Supabase PostgreSQL connection URI, then run from the repository root:

```bash
.venv/bin/python scripts/init_db.py
# Equivalent for PostgreSQL:
.venv/bin/python scripts/migrate.py
```

For Supabase's transaction pooler, the backend uses SQLAlchemy `NullPool` and disables psycopg automatic prepared statements. Configure TLS in your database URI (`sslmode=require`). Credentials are never stored in source, printed by command error handlers or sent to the browser. PostgreSQL timestamp columns use `TIMESTAMP WITH TIME ZONE`; the shared UTC type rejects naive timestamps and normalizes reads/writes to UTC, independently of the database session timezone.

Migrations execute transactionally, with an advisory transaction lock, a version/digest ledger and tamper detection. Do not edit applied migrations. `001_initial.sql` remains unchanged. `002_ingestion_storage.sql` renames the old event/incident tables without deleting records, copies existing thresholds into configuration, creates rollups for existing snapshots, links snapshots to those rollups, and backfills tenant ownership on enrichment records. Legacy events receive a `legacy_backfill` marker because v1 never retained original source metadata. RLS is enabled with no public policies and PUBLIC privileges revoked on new tables and the migration ledger. The trusted backend database role deliberately owns/bypasses RLS; tenant-scoped queries and composite constraints remain essential.

Local demo/tests can explicitly choose a SQLite URL and `APP_ENV=demo` or `test`, then use `init_db.py` or `seed.py`. Existing v1 SQLite demo databases are detected and refused; choose a fresh ignored database file. Production schema upgrades are supported by PostgreSQL migrations, not by deleting data or using `create_all` as a migration mechanism. No migration runs automatically during an API request or deployment build.

## Tables and ownership

| Table | Purpose / uniqueness |
| --- | --- |
| tenants | Tenant registry; primary key `id` |
| integrations | Provider identity, category and owner; primary key `(tenant_id,id)` |
| integration_config | One configuration row per tenant/integration; latency target and expected telemetry gap; positive-value constraint |
| request_events | Unaggregated events and bounded validated source metadata; primary key `(tenant_id,event_id)` |
| metric_rollups | Immutable calculated metrics per `(tenant_id,integration_id,window_start,window_end)` |
| health_snapshots | Immutable policy decision/evidence; unique tenant/integration/five-minute bucket; composite FK to rollup |
| health_incidents | Incident lifecycle; at most one unresolved incident per tenant/integration |

`ingestion_api_keys` stores only key digests and tenant/lifecycle metadata. `access_tokens` and `enrichments` remain supporting tables. Enrichments now also carry tenant/integration IDs and a composite FK to their snapshot. Tenant-scoped records reference tenant-owned parents; a snapshot cannot attach another tenant's rollup, and an incident/enrichment cannot attach another tenant's snapshot.

`Integration.latency_target_ms` and `max_gap_minutes` remain compatible Python/API properties, but their only stored source is `integration_config`. The constructor creates the configuration row. Refresh stores a rollup and snapshot together in the same transaction; duplicate refreshes create neither again. A rollup contains its configured-window measurements plus explicitly named 24-hour context metrics. Raw events remain independent of those calculations and are never updated on retry or refresh.

## HTTP batches

Use an ingestion key for external exporters, or an existing workspace operator token for compatibility:

- `POST /api/ingest` with `{ "events": [record, ...] }` is the canonical external endpoint and accepts ingestion-only keys.
- `POST /api/v1/request-events` accepts the same envelope for workspace-operator/local-demo compatibility; ingestion-only keys cannot use this alias.
- `POST /api/v1/logs` with `{ "logs": [record, ...] }` remains compatible.

Each envelope accepts 1–1000 records. Generated names (`request_id`, `timestamp`, `http_status`) and legacy names (`event_id`, `occurred_at`, `status_code`) are supported through aliases; do not submit both names for one field. Required fields are request/event ID, integration ID, aware timestamp, status and finite nonnegative duration. Names, type, error code/message, timeout, category and synthetic scenario metadata are optional and bounded. Unknown fields are rejected. Empty CSV optional metadata is treated as absent. Timestamps without a timezone, future events, and API events older than seven days are rejected.

The bearer identity determines tenant ownership. An optional source `tenant_id` must match it. Integrations must already exist for that tenant; ingestion never provisions arbitrary tenants or integrations from untrusted input. Error category is normalized from HTTP status and timeout, as before. Raw source metadata is stored as validated fields in `raw_event`, with UTC timestamps and normalized numeric types, plus dedicated metadata columns. This is unaggregated request metadata, not an unvalidated arbitrary request body or a byte-for-byte original file archive. Export names map to stored `event_id`/`occurred_at`/`status_code` columns. Arbitrary payload fields are not accepted.

Workspace-operator compatibility batches return HTTP 200 with per-record outcomes, including when all records are rejected. Ingestion-key batches return 422 if entirely invalid and 403 before writes for any unauthorized tenant/integration:

```json
{
  "accepted": 2,
  "rejected": 1,
  "duplicates": 1,
  "rejections": [{"index": 2, "code": "invalid_record", "fields": ["latency_ms"]}],
  "inserted": 2
}
```

`inserted` is a deprecated alias of `accepted`. Counts sum to the submitted record count. Rejection indexes are zero-based; errors expose fixed codes and known field names, never input values, attacker-controlled keys, error messages or database exception text. Malformed envelopes (missing list, empty/oversized list, invalid JSON) return 422 before ingestion. Role/auth failures remain 401/403.

Valid records persist while malformed records are rejected. `INSERT ... ON CONFLICT DO NOTHING` on `(tenant_id,event_id)` enforces idempotency across retries, duplicates inside a batch and concurrent requests. The first stored valid event wins; later valid records with the same ID do not modify it, even if their content differs. The same event ID in a different tenant is independent. Expected record-level database constraint failures are isolated with savepoints. Database connectivity/transaction failures abort the entire batch and return 503, without reporting falsely accepted records. Tenant row locks serialize ingestion with refresh, keeping snapshot evidence internally consistent.

## File imports

Provision tenants/integrations first using the existing admin CLI or demo seeder. Then import a file with a trusted database connection:

```bash
.venv/bin/python scripts/ingest_file.py data/synthetic/sample/requests.jsonl \
  --tenant brightline --allow-historical
```

Supported inputs are JSON arrays, strict `events`/`logs` JSON envelopes, JSONL and header-based CSV. `.csv` uses the same field names as JSON; UTF-8 BOMs are supported. `--tenant` explicitly binds the import to one tenant; other tenants' records are counted as rejections. Filter a multi-tenant file or invoke imports with appropriate tenant-specific files. This trusted CLI does not bypass tenant matching or auto-provision integration IDs. It uses the same Pydantic validator, UTC conversion, database insert and counts as the API.

`--allow-historical` permits old offline replay only; it never permits future events and is not available through the API. `--batch-size` accepts 1–1000 and defaults to 1000. Each chunk commits independently. JSONL/CSV are streamed; JSON arrays are loaded as one document. Malformed JSONL lines, invalid field values and ragged CSV records are rejected without aborting their peers. Broken document-level JSON or CSV quoting/encoding can make record boundaries unknowable: those produce a clear file error rather than guessed recovery. Previously committed chunks remain stored and can be safely retried.

The CLI prints aggregate accepted/rejected/duplicate counts and up to 100 indexed rejection details, plus `rejections_omitted` for larger imports. It never prints source records or credentials. The synthetic demo seeder now uses this same ingestion service before replaying health evaluations. No external API is needed to ingest or calculate health.

## Verification and deployment

Run `cd backend && ../.venv/bin/pytest -q`. Tests cover mixed-batch acceptance, duplicate preservation, tenant isolation, malformed records, UTC round trips, raw/rollup separation, config persistence, file formats, retries, historical replay and missing configuration. The existing health/incident scenarios still run against the new tables.

GitHub Actions provisions an isolated empty PostgreSQL database and runs `scripts/check_postgres.py`, which installs v1, inserts representative legacy rows, applies all subsequent migrations and verifies backfills, RLS flags, concurrent ingestion and refresh. This script refuses a nonempty database and must never be used against a customer database. Current PostgreSQL migration, upgrade, preserved-data and concurrency results are recorded in [verification](VERIFICATION.md); SQLite tests alone do not establish them.

On Supabase/Vercel, configure server-side project variables, apply migrations from a trusted terminal, then deploy the single Services project. Trusted service build/server processes share project variables; no credential is exposed to browser bundles. The frontend's sanitized read contract remains unchanged. Raw error messages are retained only in tenant-scoped database storage; the normal detail API and AI enrichment continue using sanitized/aggregate data. Configure an appropriate retention/access policy before storing real customer error metadata.

`003_health_engine.sql` adds per-integration policy fields and uppercase, typed health result/counter columns. See [Health engine](HEALTH_ENGINE.md) for configuration and transition behavior.
