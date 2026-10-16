# Database model plan

The initial plan was recorded before business logic. The current storage contract is PostgreSQL/Supabase, with explicit SQLite only for demo/tests.

- `tenants`: tenant registry.
- `integrations`: composite tenant/integration identity and provider metadata.
- `integration_config`: one tenant/integration configuration row; positive latency and freshness targets.
- `request_events`: independent unaggregated telemetry; composite tenant/event ID makes ingestion idempotent. Validated bounded source metadata is retained separately from analytics.
- `metric_rollups`: immutable calculated event-time metrics; unique tenant/integration/window.
- `health_snapshots`: decision, policy, thresholds, reasons and composite link to the tenant-owned rollup; unique evaluation bucket.
- `health_incidents`: tenant-owned opening/last snapshots and recovery lifecycle; partial uniqueness for open incidents.
- Supporting `ingestion_api_keys` store domain-separated hashes, tenant scope and revocation metadata; migration 005 enables RLS and revokes browser-role access. Keys grant only ingestion. `access_tokens` store workspace hashes; `enrichments` carry tenant/integration ownership and snapshot evidence digest.

UTC-aware types normalize all timestamps. Composite foreign keys enforce ownership. Tenant row locks coordinate ingestion/refresh. RLS blocks public Supabase data access; the trusted backend also scopes all queries by authenticated tenant.

`001_initial.sql` is immutable. `002_ingestion_storage.sql` preserves and backfills v1 records into the current schema. See [Database and ingestion](DATABASE_AND_INGESTION.md) for initialization, per-record validation, file imports and deployment.
