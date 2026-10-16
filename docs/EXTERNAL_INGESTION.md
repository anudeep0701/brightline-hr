# External request-log ingestion

Customer exporters send HTTPS `POST /api/ingest` requests with `Authorization: Bearer <ingestion-api-key>` and a JSON `{"events": [...]}` body. The key identifies exactly one tenant and grants ingestion only. It cannot read monitoring data, evaluate health, request AI assistance, change configuration or administer credentials. It provides no database access and has no connection to OpenAI credentials.

## Provision and rotate

Configure the existing `DATABASE_URL` privately in the trusted backend/administration environment. No new environment variable is required, and no environment file is created or modified. Before onboarding, apply all versioned migrations, including `005_ingestion_api_keys.sql`, and provision the tenant and its integration IDs using the existing trusted administration process.

From the repository root:

```bash
.venv/bin/python scripts/migrate.py
.venv/bin/python scripts/ingestion_keys.py create brightline --name 'Customer payroll exporter'
.venv/bin/python scripts/ingestion_keys.py list brightline
.venv/bin/python scripts/ingestion_keys.py revoke <public-key-id>
```

Creation prints the public key ID and secret once, after persistence succeeds. Store the secret directly in the customer's private backend secret store. Never place it in committed examples, frontend code, browser storage or a `NEXT_PUBLIC` variable. Listing returns only safe metadata; a lost secret cannot be recovered. Rotate by issuing a replacement, updating the exporter, then revoking the old public key ID. Revocation is checked on every authenticated request. The CLI requires trusted database access; no public key-management endpoint is introduced.

Each generated `bl_ingest_` key contains 256 bits of cryptographic randomness. The database stores a domain-separated SHA-256 digest, tenant, public ID, non-secret name and creation/revocation times. Fast hashing is appropriate for these high-entropy random secrets, rather than human passwords. Workspace tokens use a separate credential table/domain; an ingestion key cannot be promoted by accidentally provisioning its value as a workspace token. PostgreSQL enables RLS without browser policies and revokes table access from PUBLIC and existing Supabase anon/authenticated roles. The trusted backend uses its private database role.

## Request contract

See the [JSON batch](examples/production-ingest.json) and [HTTP example](examples/production-ingest.http). Replace the placeholder URL, key, provisioned integration ID and fixed sample timestamps before sending. Sample timestamps must be in the preceding seven days and not in the future. Do not commit a populated HTTP example.

An envelope contains 1–1000 records. Each record requires:

| Field | Meaning |
| --- | --- |
| `timestamp` | Timezone-aware ISO-8601 request time; normalized and stored in UTC. |
| `integration_id` | Existing integration owned by the authenticated tenant. |
| `request_id` | Stable attempt ID, 1–128 characters: letters, digits, underscore, dot, colon or hyphen. |
| `http_status` | HTTP status from 100 to 599. |
| `latency_ms` | Nonnegative request duration in milliseconds. |

Optional fields include `tenant_id`, `integration_name`, `integration_type`, `error_code`, `error_message` and `timed_out`. Error code/message lengths are bounded to 128/2000 characters. Metadata names never create integrations or change their stored configuration. Unknown record fields are rejected. Existing internal aliases `occurred_at`, `event_id` and `status_code` remain supported; send one spelling per field. Redact customer secrets and personal data before exporting error messages.

Omit `tenant_id` in production batches: the authenticated credential controls ownership. If supplied, it must match. A `tenant_id` query filter also cannot override the credential. An absent integration and an integration owned by another tenant both produce the same `unknown_integration` rejection without revealing foreign ownership.

For ingestion keys, authorization preflight covers the entire validated batch before any insert. Any tenant/integration scope violation returns **403 and writes nothing**. Otherwise valid peers receive `batch_not_processed`; duplicates are not checked for a forbidden batch. Schema-invalid records cannot be ingested and receive safe validation errors.

## Results and retries

A successful batch returns typed JSON such as:

```json
{
  "accepted": 1,
  "rejected": 1,
  "duplicates": 0,
  "validation_errors": [{"index": 1, "code": "invalid_record", "fields": ["latency_ms"]}],
  "rejections": [{"index": 1, "code": "invalid_record", "fields": ["latency_ms"]}],
  "inserted": 1
}
```

`validation_errors` is the canonical safe error list; `rejections` and `inserted` remain compatibility aliases. Counts sum to the submitted record count for processed batches. Indexes are zero-based. Errors contain fixed codes and known field names, never submitted values, raw messages, keys, SQL or connection strings.

| HTTP | Behavior |
| --- | --- |
| 200 | Valid records accepted and retries counted as duplicates; malformed peers rejected independently. An all-duplicate batch succeeds. |
| 401 | Missing, malformed, unknown or revoked credential; `WWW-Authenticate: Bearer`. |
| 403 | Unauthorized tenant/integration; no writes. Valid ingestion keys also receive 403 on workspace/operator routes. |
| 422 | Invalid envelope, JSON or query; or every record invalid. All-invalid record batches include counts/errors plus `detail` and `code`. Envelope/query errors use the common `detail`/`code` response because no batch was processed. |
| 503 | Storage/schema unavailable; transaction aborts without reporting falsely accepted events. |
| 500 | Unexpected application failure with a sanitized response. |

No application rate limiter or 429 response is implemented in this MVP. Batch size is bounded, but this is not a substitute for deployment traffic controls.

Idempotency remains database-enforced on `(tenant_id, request_id)`, across integrations and key rotations. If provider IDs are unique only within an integration, prefix them with the integration/provider ID. Retries retain the original request ID and content; the first stored valid record wins, even if a subsequent payload differs. A new actual attempt needs a new ID. The same ID in another tenant is independent. Retry network failures or 503 responses with stable IDs; inspect partial results and correct rejected records. Fix authorization/configuration before retrying 403, and correct invalid data before retrying 422.

## Shared processing and compatibility

External API batches, generated demo events and JSON/JSONL/CSV file imports all call `app/ingestion/service.py`. The API adds strict authorization preflight to that same service. Validation, UTC handling, database constraints, savepoint isolation and idempotency use one implementation. Trusted offline imports alone may enable historical replay; API callers cannot bypass the online time bounds.

Existing workspace operator tokens remain accepted on `/api/ingest`; legacy operator/demo callers retain partial-rejection behavior for compatibility. Readers cannot ingest. Credential-free `/api/ingest` is limited to explicit local SQLite demo mode with no Authorization header. Invalid headers never fall back to demo access. Ingestion keys work only on canonical `/api/ingest`, not legacy `/api/v1` or scheduler endpoints.

Ingestion stores raw validated request metadata separately from metrics. It neither calls OpenAI nor evaluates health; the existing scheduled/operator evaluation consumes stored events. AI availability cannot affect acceptance or health classification.

## Verification

`backend/tests/test_external_ingestion.py` exercises valid/invalid/revoked credentials, ingestion-only permissions, accidental privilege promotion, tenant/integration isolation before writes, retries and rotation, malformed/partial batches, UTC normalization, CLI lifecycle and hash-only persistence. A generated-data parity test imports the same traffic through file and authenticated HTTP paths and compares resulting metrics/health.

Run `.venv/bin/python -m pytest -q backend/tests`. The isolated PostgreSQL CI check additionally exercises migration/RLS and credential issue/authenticate/revoke behavior. Local SQLite tests do not prove PostgreSQL migration or RLS execution; migration 005 has not been applied to a hosted database by this implementation.
