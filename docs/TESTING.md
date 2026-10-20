# Business behavior tests

Current submission totals and live/browser verification are in [VERIFICATION.md](VERIFICATION.md). Counts in the dated implementation follow-ups below describe those earlier stages; run the complete suites for the current result.
The suite checks operational outcomes rather than pursuing a coverage percentage. Unit tests isolate policy and metric boundaries; service tests verify persistence and incident transitions; API workflow tests exercise HTTP validation, ingestion, stored metrics, health decisions and incident history together. Only time and the optional AI boundary are faked in the new workflow suite. Core calculations and database-backed services run normally.

## Run

From the repository root with dependencies installed:

```bash
.venv/bin/python -m pytest -q backend/tests
```

Run the focused acceptance workflows:

```bash
.venv/bin/python -m pytest -q backend/tests/test_monitoring_workflows.py
```

Run presentation behavior tests:

```bash
cd frontend
npm test
```

GitHub Actions already discovers all backend tests, runs frontend tests and provisions an isolated PostgreSQL instance for `scripts/check_postgres.py`. No OpenAI credentials, production database, running API server or environment file is needed for these suites.

## Required behavior map

The names below refer to functions in [test_monitoring_workflows.py](../backend/tests/test_monitoring_workflows.py), supplemented by existing focused suites.

| Business requirement | Executable evidence |
| --- | --- |
| Healthy traffic becomes HEALTHY | `test_ingested_traffic_produces_explainable_health[healthy-requests]`: real ingested requests, persisted rollup and summary agree. |
| Moderate errors become DEGRADED | Same workflow's `moderate-errors` case: 2% errors produce a warning and explainable reason. |
| Sustained high errors become UNHEALTHY | `test_two_bad_windows_confirm_one_incident_without_double_counting[sustained-errors-with-fast-responses]`: fast successful latency cannot cancel 20% errors. |
| Severe latency is detected with few/no errors | Same workflow's `latency-outage-with-no-errors` case: every HTTP attempt succeeds, but 4,000ms P95 confirms unhealthy after adjacent bad windows. Baseline-relative degradation is also tested in `test_health.py` and `test_health_engine.py`. |
| A brief spike does not create a persistent incident | `test_brief_error_and_latency_spike_is_visible_without_persistent_incident`: an isolated error/6-second outlier remains stored, stays below rolling-policy influence, expires from the window and opens no incident. `test_health_engine.py` also tests one critical observation followed by confirmed recovery with a five-minute policy. |
| Low traffic is UNKNOWN | `low-traffic-even-if-all-fail`: five failed requests cannot manufacture sufficient evidence for an unhealthy classification. |
| Duplicate requests are idempotent | `test_malformed_records_and_conflicting_retries_cannot_corrupt_metrics`: a changed duplicate cannot overwrite the original event or inflate request/error counts; complete retries remain duplicates. |
| Malformed records are rejected safely | Same mixed-batch workflow: invalid values, foreign tenant records, future times and unknown integrations are rejected while later valid records persist; private submitted values are absent from reports. |
| Consecutive bad windows open an incident | Both two-window workflows: first critical observation is pending DEGRADED, second confirms UNHEALTHY and exactly one incident. Same-bucket reevaluation cannot count as another observation. |
| Consecutive healthy windows resolve an incident | `test_borderline_window_resets_recovery_and_two_clean_windows_resolve_once`: one good window is pending; two adjacent clean windows resolve the existing incident exactly once. |
| A borderline window does not flap health | Same recovery workflow: 0.7% errors are below the 1% warning threshold but above the 0.5% recovery margin; observed HEALTHY remains stabilized UNHEALTHY and resets the recovery streak. |
| OpenAI unavailability does not break monitoring | `test_ai_outage_does_not_block_monitoring_or_incident_recovery`: provider timeout returns exact deterministic reason_text while subsequent ingest/evaluate/recovery continue. |
| Health is independent of AI response | `test_opposing_ai_responses_cannot_change_identical_health_decisions`: deliberately contradictory, schema-valid summaries differ, while complete snapshots and incidents remain unchanged and the next deterministic decisions still match. |
| Tenant-scoped queries do not mix data | `test_same_provider_and_request_ids_never_mix_tenant_metrics_or_incidents`: identical provider/request IDs coexist under different tenants; one is in outage and one healthy, with separate metrics, logs, summaries and incidents. Evaluating one tenant cannot populate another tenant's history. |

## API contracts

[test_public_api.py](../backend/tests/test_public_api.py) verifies every requested public endpoint, plus workspace metadata and compatibility with the existing dashboard. It covers liveness/readiness, unavailable storage and missing schema columns, authentication and reader/operator permissions, query validation, safe errors, tenant restrictions, time-range boundaries, incident activity overlap, pagination, status/type filters, cached enrichment, CORS and OpenAPI response schemas.

The acceptance workflows add real event-to-incident journeys through `/api/ingest`, `/api/evaluate`, `/api/health-summary`, `/api/integrations`, integration detail/metrics/incidents and `/explain`. Tests assert business state, reasons, measurements and persistence invariants rather than merely HTTP 200 or internal function calls.

## Deterministic fixtures and isolation

[conftest.py](../backend/tests/conftest.py) creates an isolated in-memory SQLite database per test with real foreign keys and hashed fake workspace tokens. The API uses the real application with only its database dependency overridden.

The workflow `monitoring_clock` starts at **2026-10-15 12:00:00 UTC** and advances explicitly in five-minute steps. It controls ingestion, evaluation, operational reads and enrichment timestamps without sleeps or global system-clock changes. `request_window` uses an independent NumPy generator with **seed 42**, exact request/error counts and timestamps strictly before the evaluation boundary. Generated IDs intentionally match across tenants to test composite identity isolation. Rebuilding the same window reproduces the same records.

Most new workflows exercise the default fifteen-minute rolling window. Recovery-focused tests explicitly select the supported five-minute window so they isolate confirmation/recovery hysteresis from rolling-window washout. Full seeded generator replays remain in [test_synthetic_data.py](../backend/tests/test_synthetic_data.py), including byte-for-byte sample reproducibility and all ten operational scenarios.

The autouse OpenAI guard fails any unexpected client construction at the application's enrichment boundary. AI-specific tests replace it with explicit local fakes, including timeouts, refusals, invalid output and opposing summaries. No live provider request or paid token usage is involved. Real environment files are never loaded or modified by test fixtures.

SQLite validates business behavior and relational constraints, but does not demonstrate PostgreSQL row locking, concurrent writers, RLS or migration execution. Those are covered by the separate PostgreSQL CI script; a local Pytest pass does not claim that CI or hosted deployment has run.

## External ingestion acceptance

`test_external_ingestion.py` adds 34 cases covering production-style batches, missing/invalid/revoked credentials, endpoint permissions, accidental privilege promotion, cross-tenant and integration rejection before writes, key rotation/idempotency, malformed envelopes, safe partial errors, UTC normalization, hash-only persistence, CLI lifecycle and committed request examples. A fixed-seed generator parity test compares file-import and authenticated HTTP metrics/health. All provider calls remain local fakes. The complete backend suite now passes 210 tests; six frontend behavior tests and TypeScript checks also pass. PostgreSQL credential/RLS assertions are supplied in the isolated CI script; local SQLite results do not claim that CI ran.

## Grounded AI operations follow-up

`test_incident_assistance.py` adds **31 backend cases** covering persisted grounded selection plans and audit/minimal evidence storage; keyless/timeout/provider/invalid-plan fallback; forged facts/categories/actions/health fields; unchanged snapshots/incidents; all six focused questions; missing prior healthy evidence; cross-tenant/reader/prompt boundaries; selected resolved-incident evidence; cache retry/freshness invalidation; no-traffic versus error-free fresh traffic; and old events received recently. The existing 215 cases remain intact.

Frontend adds four behavior cases for current evidence UNKNOWN without rewriting historical HEALTHY, advisory confidence labels, scoped structured investigation requests and safe request errors. Totals: **246 backend**, **10 frontend**, plus **4 root launcher** tests. The normal secret-free smoke workflow also calls the new brief and recovery assistance routes through HTTP. Provider calls are mocked in tests; the browser verified keyless brief/copilot/audit/recovery behavior on the regular isolated synthetic demo.
