# Backend API contract

The public API is under `/api`. Existing `/api/v1` routes remain supported for the dashboard. FastAPI provides executable schemas at `/openapi.json`, interactive Swagger at `/docs`, and ReDoc at `/redoc`. Metadata describes endpoint behavior, query constraints, response models and workspace-token authorization.

## Authentication and tenancy

Monitoring and operator endpoints require an opaque workspace bearer token in `Authorization: Bearer <workspace-token>`. Tokens are hashed at rest and map to one tenant and either reader or operator access. Local `APP_ENV=demo` alone allows credential-free access to the seeded Brightline tenant. Production fails closed on invalid configuration. OpenAI API keys are never workspace tokens and never belong in browser requests.

Readers can inspect all GET data endpoints. Operators can also ingest, evaluate, explain and replace health configuration. For token-based access, an optional `tenant_id` query filter must match the authenticated tenant or returns 403. Credential-free local demo mode with SQLite can select another synthetic tenant; this exception is unavailable for PostgreSQL and production. This filter does not grant cross-tenant access. There is no implicit administrator or all-tenant data query. Probes are public; the scheduler uses its separate CRON_SECRET bearer token.

External ingestion uses a separate tenant-scoped ingestion-only key on `POST /api/ingest`. See [external ingestion](EXTERNAL_INGESTION.md) for issuance, rotation, strict tenant authorization and the production batch contract. Existing workspace operator tokens remain compatible.

## Public routes

| Method and path | Behavior and response |
| --- | --- |
| `GET /healthz` | Process liveness: `{"status":"ok"}`. No database or OpenAI access. |
| `GET /readyz` | Database connectivity and every required table/column readable: `{"status":"ready"}`. Missing migrations or unavailable storage return 503. Does not provision data or contact OpenAI. |
| `GET /api/workspace` | Authorized identity, role and tenant options; all synthetic tenants only in credential-free local SQLite demo mode. |
| `GET /api/health-summary` | Tenant ID, generation time, total integrations, counts by HEALTHY/DEGRADED/UNHEALTHY/UNKNOWN, stale count, current open incident count and latest evaluation time. |
| `GET /api/integrations` | Paginated integration configuration summaries, latest/previous snapshots and stale flags. |
| `GET /api/integrations/{id}` | Current snapshot, bounded snapshot history, sanitized logs, incidents and an optional cached enrichment for the current snapshot. GET never invokes AI. |
| `GET /api/integrations/{id}/metrics` | Paginated persisted rollups with ID, window start/end, calculation time and metrics. Reads never trigger calculation. |
| `GET /api/integrations/{id}/incidents` | Paginated incident history including opening/last snapshot IDs, opening/resolution times and recovery streak. |
| `POST /api/ingest` | Ingestion key or workspace operator; `{"events":[...]}` envelope with 1–1000 records. Returns accepted/rejected/duplicate counts and safe `validation_errors`, plus compatibility aliases. |
| `POST /api/evaluate` | Operator-only current server-time evaluation for the token tenant, respecting per-integration cadence. Returns `created` and UTC `bucket`. No body or historical-time override. |
| `POST /api/integrations/{id}/brief` | Operator-only, cached evidence-grounded brief with compact audit metadata and deterministic fallback. |
| `POST /api/integrations/{id}/investigate` | Operator-only fixed topic; optional owned resolved incident for recovery. Read-only guidance, no arbitrary prompt/tool/tenant selection. |
| `POST /api/integrations/{id}/explain` | Operator-only structured assistance for the latest persisted snapshot; 409 before first evaluation. AI failure/missing key returns exact deterministic reason_text. |

A missing integration returns 404, including metrics/incidents/explanation reads; a known integration with no evaluations returns empty metric/incident collections and a null snapshot. Unevaluated integrations count as UNKNOWN, while absence of observations does not manufacture a persisted decision. GET endpoints never evaluate or mutate health.

## Filters and pagination

- `tenant_id`: optional on every public data endpoint; must match the token tenant. Credential-free local SQLite demo mode may choose one of its synthetic tenants.
- `health_status`: uppercase enum on summary and integration list. Filters the **latest** selected snapshot, not any historical matching snapshot. Missing snapshots match UNKNOWN.
- `integration_type`: summary and integration list; exact case-insensitive match against the stored integration category, e.g. `payroll`.
- `start_time` / `end_time`: timezone-aware timestamps on GET data endpoints. Ranges are half-open `[start_time, end_time)`, with start strictly before end. Omit either bound for an open range. Naive timestamps, invalid bounds and unknown query fields return 422.
- Summary/list select the latest snapshot **within** the requested range for each integration. With no range, they use the current latest snapshot. Staleness always compares the selected snapshot with the current server clock at twice the integration cadence. Open incident count means currently unresolved incidents for the filtered integrations that overlap the requested range; it is not an as-of unresolved count.
- Metrics filter by `window_end`. Incidents match activity overlap: opened before end and unresolved or resolved strictly after start. Incident history additionally accepts `state=OPEN` or `state=RESOLVED`.
- Detail time filters apply to history/log/incident collections. Its top-level snapshot remains the current latest decision. Without time bounds, snapshot history defaults to 24 hours; detail returns at most 288 snapshots, 50 sanitized logs and 20 incidents. Use dedicated history endpoints for pagination.
- Integration lists use `limit=50` by default, maximum 200. Metric/incident history uses `limit=100`, maximum 500. `offset` defaults to zero and must be nonnegative. Collections return `{tenant_id, total, limit, offset, items}`; histories also include integration_id. total is measured after filtering and before pagination. Integrations sort by ID; history sorts newest first with stable ID tie-breaks.

All response timestamps use UTC ISO-8601. Rates are fractions, not percentages. Latency is milliseconds. Snapshot results include status, observed_status, metrics, confidence/evidence sufficiency, machine-readable reason_code, deterministic reason_text, counters, evaluated_at and complete policy evidence. Raw request payloads/error messages are never exposed through the detail log collection.

## Examples

After running the seeded local demo backend on port 8000, credential-free calls work only in demo mode:

```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/readyz
curl -s http://localhost:8000/api/health-summary
curl -s 'http://localhost:8000/api/integrations?health_status=UNHEALTHY&integration_type=payroll&limit=20'
curl -s -X POST http://localhost:8000/api/evaluate
```

For authenticated environments add `-H 'Authorization: Bearer <workspace-token>'` to data requests. The token determines the tenant; request data cannot override it. A generated-event ingest body looks like:

```json
{
  "events": [
    {
      "request_id": "provider-attempt-001",
      "timestamp": "2026-10-15T10:00:00Z",
      "integration_id": "<existing-integration-id>",
      "http_status": 503,
      "latency_ms": 1800,
      "error_code": "SERVICE_UNAVAILABLE",
      "error_message": "Provider request failed"
    }
  ]
}
```

Replace the ID with a provisioned integration and the timestamp with a recent past UTC time (online ingestion accepts the preceding seven days). Malformed records, future timestamps and stale online records are rejected per record while valid peers persist. With an ingestion key, tenant mismatches or unprovisioned integrations reject the entire batch with 403 before writes; an entirely invalid batch returns 422. Legacy workspace operator batches retain per-record scope rejections. Retrying the same request ID for the same tenant reports a duplicate rather than storing another event. See [ingestion contract](DATABASE_AND_INGESTION.md) for CSV/JSON/JSONL offline imports and aliases.

## Errors and CORS

Application errors use a predictable `{"detail":"Safe explanation","code":"machine_readable_code"}` envelope. Submitted payload/query values, connection strings, SQL and provider exception details are not echoed in validation or storage errors.

| HTTP status | Meaning |
| --- | --- |
| 401 | Missing/invalid/revoked workspace or ingestion credential; WWW-Authenticate: Bearer. Invalid scheduler authorization also returns 401. |
| 403 | Reader attempting mutation, tenant filter mismatch, ingestion batch scope violation or ingestion key used on another endpoint. |
| 404 | Integration absent in the authenticated tenant, or unknown route. |
| 409 | Explanation requested before any persisted snapshot. |
| 422 | Invalid envelope, query constraints, timestamp/range or policy shape. Mixed valid/invalid ingestion records return 200 with explicit counts; all-invalid ingestion-key batches return 422 with counts/errors. |
| 500 | Unexpected application failure with sanitized response. |
| 503 | Storage unavailable, schema migrations missing, unprovisioned tenant or scheduler capacity exceeded. |

`CORS_ALLOWED_ORIGINS` is read from the backend environment as a comma-separated list of exact browser origins. Allowed methods are GET, POST and PUT, with Authorization and Content-Type headers. Preflight is handled by middleware; disallowed origins receive no access-control allow-origin header. Cookie credentials are disabled. Production requires exact HTTPS origins without paths. No environment file is loaded, created or edited by the API.

## Existing compatibility and scheduler routes

- `GET /api/v1/dashboard`: current integration list, latest evidence and active incidents.
- `GET /api/v1/integrations/{id}`: existing detail shape.
- `GET/PUT /api/v1/integrations/{id}/config`: read or replace the complete validated policy; operator required for PUT. Changes affect future decisions and reset streak continuity.
- `POST /api/v1/logs`: legacy logs envelope; same idempotent ingestion service.
- `POST /api/v1/request-events`: generated events envelope; same service as `/api/ingest`.
- `POST /api/v1/refresh`: same current evaluation service as `/api/evaluate`.
- `POST /api/v1/integrations/{id}/explanation`: same optional assistance service as `/api/integrations/{id}/explain`.
- `GET /api/cron/refresh`: CRON_SECRET authorization and bounded tenant batch. No OpenAI work on this path.

Routes are thin adapters. `app/services/operations.py` owns operational queries and orchestration, while ingestion, metric calculation, health policy, incident transitions and AI enrichment remain in their existing domain modules. Query/output schemas live in `app/schemas`; authorization and exception translation stay at the HTTP boundary.

See [health engine](HEALTH_ENGINE.md) and [AI enrichment](AI_ENRICHMENT.md) for the deterministic and advisory contracts respectively.

New detail/list responses include observed/received/evaluated freshness timestamps and current evidence status, separate from immutable recorded snapshots. Summary adds `current_evidence_status_counts`; existing `status_counts` and server health-status filters retain recorded-decision semantics. Detail/incident history includes opening/recovery condition metadata. See [AI operations](AI_OPERATIONS.md) for the new fact-grounded brief/copilot/recovery contract.

### Operational impact projection

The existing authenticated `GET /api/v1/dashboard` response now includes typed `operational_impact`. It is tenant-wide, independent of list filters. `period_start`/`period_end` delimit a trailing 24-hour UTC interval `[start, end)` for `incidents_detected` (confirmed openings) and `recovered_incidents` (resolutions). `mean_confirmed_incident_duration_seconds` is the full mean opening-to-resolution duration for that resolved cohort, or null when no incident resolved. Current-state fields are `integrations_requiring_attention`, `healthy_percentage` (0–100, null with no integrations), `unknown_integrations`, and `stale_or_absent_integrations` (telemetry missing/stale or evaluation overdue). Healthy share uses current evidence rather than a stale persisted HEALTHY decision. No MTTD, ticket lead-time, customer ROI or delivered-notification suppression is inferred. See [business value and pilot measurement](BUSINESS_VALUE.md) for definitions and limitations.
