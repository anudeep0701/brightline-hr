# API contract outline (before implementation)
Prefix /api/v1. All operator routes derive tenant from a hashed bearer token, never from user-supplied tenant headers. Credential-free demo routes are available only when APP_ENV=demo. Production fails closed without database, origins and cron secret.

- GET /healthz: liveness, no secrets.
- GET /api/v1/dashboard: integration list, latest snapshots, active incidents, evaluation time and stale indicator.
- GET /api/v1/integrations/{id}: integration, snapshot history (24h, max 288), recent sanitized logs (50), incidents (20).
- POST /api/v1/logs: validated batch (1–1000), idempotent tenant/event ids; operator token required. All-or-nothing validation, reject unknown integrations and future events.
- POST /api/v1/refresh: evaluate current 5-minute bucket for authenticated tenant; operator required; repeats return existing decisions.
- POST /api/v1/integrations/{id}/explanation: optional AI for latest persisted snapshot; bounded timeout; deterministic fallback; never changes health.
- GET /api/cron/refresh: CRON_SECRET bearer; bounded tenant batch for MVP, same refresh service. No AI on cron path.

FastAPI /docs and /openapi.json are the executable contracts. Timestamps are UTC ISO-8601; rates are fractions; latency is milliseconds. 401 invalid/missing token, 403 wrong role, 404 tenant-scoped missing integration, 422 invalid input, 503 missing storage. No secrets in responses.
