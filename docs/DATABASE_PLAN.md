# Database model plan (before implementation)
PostgreSQL is the deployed source of truth. SQLAlchemy models and a versioned SQL migration describe the same schema. SQLite is restricted to a credential-free local demo and unit tests.

- tenants: UUID/id, display name. A tenant row lock serializes refresh and ingestion per tenant.
- access_tokens: SHA-256 digest, tenant FK, role (operator or reader); no plaintext persistence.
- integrations: composite tenant/id key, category, owner, expected maximum request gap, latency target.
- request_logs: composite tenant/event key for idempotency; composite integration FK prevents cross-tenant references; UTC request time, HTTP status, timeout flag, latency, allowlisted error category. No request bodies or personal data.
- health_snapshots: UUID, tenant/integration FK, unique 5-minute evaluation bucket; metric values, policy version, thresholds, reasons, evaluation time. Immutable evidence.
- incidents: tenant/integration FK, opening snapshot, last snapshot, opened/resolved timestamps, recovery streak. A PostgreSQL partial unique index permits one open incident per integration.
- enrichments: snapshot FK, generated time, source, explanation, evidence digest. Independent from health evaluation.

Index logs by tenant, integration, request time; snapshots by tenant, integration, bucket. Queries always scope to authenticated tenant. PostgreSQL RLS blocks anonymous Supabase API access; database credentials stay server-side. No browser database access.
