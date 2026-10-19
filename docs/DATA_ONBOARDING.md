# Connect your request logs

## Pilot

**Export logs → upload CSV/JSON → validate → evaluate health.**

1. Ask your Brightline administrator to register your tenant and integrations, then issue an **operator workspace token**. Connect that token using **Workspace access**. Production workspaces require authentication. The public synthetic assessment instead opens an automatic fixed-tenant demo session; its owner may explicitly enable the same preview/confirmation workflow with `DEMO_ALLOW_FILE_IMPORT=true`. Upload only synthetic assessment data to that shared public workspace.
2. Open **Data sources**. Choose a UTF-8 CSV, JSON, NDJSON or JSONL file, with at most **1,000 records and 2 MiB**. Export these required fields:

   ```csv
   timestamp,request_id,integration_id,http_status,latency_ms
   2026-10-15T11:59:00Z,staging-request-001,workday-payroll,200,125
   ```

   Replace the integration ID with a registered ID and export actual timezone-aware request timestamps. Optional fields: `error_code`, `error_message`, `integration_name`, `integration_type`. JSON accepts an array or an `events`/`logs` array envelope. NDJSON/JSONL uses one JSON record per nonblank line. Existing normalized aliases (`occurred_at`, `event_id`, `status_code`) also work. CSV nullable metadata can be blank. There is no arbitrary column-mapping UI: rename columns before upload.
3. Select **Validate file**. Nothing is stored during preview. Counts show total records, valid **new** records, duplicates, rejected records, and records referencing unknown integrations. Valid new + duplicates + rejected equals total. Record numbers refer to data records, excluding the CSV header and blank NDJSON lines. Representative errors identify safe field names without echoing raw values.
4. Correct errors, or explicitly **Confirm import** of the valid rows. Invalid rows are reported and skipped; duplicates are ignored. **Any tenant mismatch or unknown integration blocks the entire import**, including otherwise valid rows. A file's tenant ID cannot grant access; your authenticated workspace determines scope. Confirmation resubmits the same file and its digest, and revalidates against current storage. Another ingestion between preview and confirmation can change final duplicate/accepted counts; final results are authoritative.
5. Select **Evaluate current health**, then open **Integration health**. Evaluation uses the same deterministic policy and incident lifecycle as production telemetry. A completed evaluation window is immutable: if it was already recorded, new requests appear in the next scheduled window. Verify the actual evaluator schedule; dashboard polling only reloads the view.

Authenticated operator file imports allow backfill older than seven days but reject future timestamps. Backfill is preserved as raw evidence; it does **not** rewrite prior snapshots, rewind incidents, or make old traffic look currently healthy. Historical recomputation requires an explicit offline replay plan. Send recent staging telemetry to validate the live health workflow.

## Production

**Generate tenant ingestion key → POST telemetry to `/api/ingest` → monitor ingestion and health.**

A trusted administrator issues a dedicated ingestion-only key with the existing backend CLI:

```bash
.venv/bin/python scripts/ingestion_keys.py create YOUR_TENANT --name staging-exporter
```

Save the **entire once-displayed secret** privately in your customer's backend secret store. Only its hash and safe metadata are stored. Existing plaintext keys cannot be retrieved through this UI/API. This key grants no workspace, database, policy or OpenAI access. Keep it separate from the operator workspace token.

Normalize logs into an events batch. Generate `events.json` with your exporter, then send it using an exported ingestion secret and backend URL:

```bash
curl --fail-with-body -X POST "$API_BASE_URL/api/ingest" \
  -H "Authorization: Bearer $INGESTION_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @events.json
```

```json
{
  "events": [{
    "timestamp": "<actual recent ISO-8601 timestamp with timezone>",
    "request_id": "<stable tenant-unique request ID>",
    "integration_id": "<registered integration ID>",
    "http_status": 200,
    "latency_ms": 125
  }]
}
```

Replace placeholders before sending. API ingestion accepts up to 1,000 records, timestamps from the past seven days, and no future events. Request IDs must be unique across integrations within a tenant; retries must retain the same IDs. Check `accepted`, `duplicates`, `rejected`, and `validation_errors`. Cross-tenant/unknown-integration API attempts return 403 before writes. Entirely invalid external batches return 422. There is no URL-pull feature.

**Observed data sources** shows Live API, File Import, Demo or Unknown source, plus last received time, last event time, last evaluation and freshness. Backfilled events can be newly received yet old; receipt time alone is not proof of fresh telemetry. Multiple source labels mean that stored events came through multiple paths. Labels are assigned by trusted backend ingestion code, not customer data. Duplicate retries preserve the original event and source. Existing events become Unknown source because their historical origin cannot be proven. Freshness indicates observed evidence, not exporter uptime or a notification-delivery SLA.

## Future connector model

Customer-specific pull connectors can be added where required. Each adapter would normalize provider logs and submit them through the same tenant-scoped domain ingestion path. Scheduling, connector credentials and provider-specific pagination would belong to that adapter; the health engine would remain shared. Live provider connectors are intentionally outside the initial production MVP. No new third-party service, queue, or arbitrary URL-fetch capability was added.

## Administrator setup

This release adds **migration 006** for `request_events.source_type`, with UNKNOWN as the conservative default. It preserves existing events; no earlier migration was edited. With `DATABASE_URL` exported privately, apply pending PostgreSQL migrations manually before starting this release:

```bash
.venv/bin/python scripts/migrate.py
```

For an existing local demo SQLite database, use the explicit initializer; it adds the provenance field without deleting events:

```bash
.venv/bin/python scripts/init_db.py
```

No environment file is loaded or changed. No new required environment variable is introduced. API_BASE_URL and INGESTION_API_KEY above are curl-example shell variables, not new application configuration.

## Upload API and security notes

- Operator-only `POST /api/imports/preview?format=csv|json|ndjson|jsonl` receives raw file bytes, with `text/csv`, `application/json`, or `application/x-ndjson` respectively. Preview returns counts, safe row errors, `can_import`, and `file_digest` (SHA-256).
- `POST /api/imports/commit?format=...` receives the same bytes with `X-Confirm-Import: true` and `X-Preview-Digest: <digest>`. The digest detects changed bytes; it is not an authorization credential or proof of a prior preview. Authorization is independently checked on every request. The UI requires the two-step flow.
- Ingestion-only keys cannot access upload endpoints. Readers can inspect data sources but cannot upload. Optional tenant filters must match the authenticated tenant.
- Uploaded bytes remain in bounded request memory and are not staged on disk or exposed publicly. Filenames are never sent as filesystem paths or used by the server. Unsupported types return 415, malformed documents 422, and size/record-limit violations 413.
- Imported events are retained in the existing request-event storage, including supported optional error fields. Redact secrets and personal data before export; preview/AI do not require raw messages. Existing retention/backup and ingestion-capacity pilot work still applies.
- Browser uploads are intentionally small. Split larger pilots into reviewed files or use the existing trusted file CLI, which streams batches and reports per-batch results. There is no resumable/background upload infrastructure.
