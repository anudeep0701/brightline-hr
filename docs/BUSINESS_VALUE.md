# Operational value and pilot measurement

Implementation checklist:
- [x] Add a tenant-scoped impact projection to the existing dashboard response, with no schema migration.
- [x] Show current attention/freshness and 24-hour incident outcomes with explicit demo labeling.
- [x] Verify calculations, scope isolation, policy configuration and provider independence.
- [x] Document production KPI evidence requirements and a shadow-mode pilot.

Contract: `/api/v1/dashboard` adds `operational_impact` with UTC `period_start`, `period_end`, current integration counts, healthy percentage, incidents opened/resolved in the period, and mean confirmed duration for incidents resolved in the period. Missing duration/percentage denominators return null, never zero. Current counts cover the authenticated tenant, independent of dashboard search filters. Incident ranges are `[start, end)`; durations span opening to resolution, even if opening preceded the range. These are lifecycle measures, not verified customer-impact measures. Existing raw events, snapshots and incidents remain authoritative; no new tables or provider-specific policy paths are required.

## Morning operating view

Marcus Webb can scan current health counts, tenant-wide attention/healthy share, and the severity-ordered attention list. Each attention item shows why it needs attention, evaluation and last telemetry times, recent direction, and a deterministic first investigation check. Detail pages retain policy evidence, categorized errors, incident/recovery history and optional advisory AI. Unknown evidence requires attention, including a recent evaluation whose underlying telemetry is stale. Current counts are refreshed with the view; incident outcomes are computed on the server for the trailing 24 hours at `server_time`. Search/status/type filters affect lists, not the tenant-wide impact section.

Confirmed incident openings are counted once, not once per bad window. Recoveries count incidents whose resolution is in the window; duration is the full opening-to-resolution interval for that cohort. Open incidents are excluded from the duration mean, so the mean can look favorable while long incidents remain open; the dashboard separately shows open incidents. Incidents that straddle a period are counted only according to their own opening/resolution timestamps. Timestamps describe evaluated window boundaries, not independently measured fault onset, detection processing time or customer impact. Backfilled telemetry can produce historical incidents and must not be interpreted as live detection performance.

**Demo / simulated operational impact** labels demo-mode results. These are real calculations over stored synthetic evidence, not measured customer savings or production-proven ROI. Production mode describes observed lifecycle outcomes only; it does not assert that received telemetry is genuine production data. There is no event-level demo/production provenance flag: use separate tenants/environments for pilot, replay and operational telemetry. No new environment variables are required.

## Production KPI measurement plan

Agree definitions, a baseline period, review ownership and a pilot success criterion with Ops before enabling operational use. Compare equivalent incident severity/provider cohorts and report sample sizes, missing observations and monitoring coverage. Preserve unknown periods rather than counting them as healthy. The following are measurement designs, not product claims or implemented new integrations.

| KPI | Definition and required evidence | Current support / limitation |
| --- | --- | --- |
| MTTD | Mean of detection time minus independently established fault onset, for matched incidents. Record onset source and actual detection time. | Openings and snapshot `evaluated_at` exist; ground-truth onset does not. Do not treat the first failing request or confirmation-window delay as complete MTTD. |
| MTTR | Mean of confirmed resolution minus detection for resolved incidents; also report open-incident age and cohort count. | The dashboard calculates **mean confirmed incident duration**, opening-window to resolution-window, for the resolved-in-last-24h cohort. This is a policy lifecycle proxy; it excludes pre-detection failure and rolling-window/recovery hold time is included. |
| Detected before customer tickets | Matched incidents with actual detection before first related ticket divided by matched incidents with reliable report times. Report unmatched and ticket-free incidents separately. | No customer-report time or ticket linkage is recorded. No early-detection percentage is displayed. A future pilot can collect a reviewed mapping to the customer's existing ticket timestamps. |
| False-positive rate | Operator-reviewed false incidents / all reviewed incidents, with undecided cases and review coverage shown separately. | No adjudication labels exist. Hysteresis tests demonstrate spike resistance, not a measured false-positive rate. |
| Alert-noise reduction | Compare duplicate delivered notifications per incident before/after, using an agreed deduplication rule and comparable traffic. | One open incident per integration and idempotent evaluation prevent duplicate incident records. There is no notification delivery ledger; no notification-suppression count or reduction percentage is claimed. |
| Operator investigation time | Median active investigation minutes from explicit start/stop records, by severity; distinguish elapsed time and active work. | No operator activity timer exists. AI usage/token latency is not a substitute. Collect reviewed timing samples during the pilot. |
| Customer-impact duration | Time from confirmed customer-impact onset to confirmed recovery for linked affected workflows/customers. | Incident duration and aggregate request failures do not establish customer impact or affected customer count. Add a reviewed workflow-impact mapping during a pilot. |
| Integration availability | Choose either successful attempts / valid attempts, or time meeting a documented SLO / monitored eligible time. Report retry policy, coverage, unknown time and weighting. | Raw attempts and rollups support request success ratios. Rolling windows overlap: do not sum them as independent traffic or uptime. The dashboard's current healthy percentage is a share of integrations with sufficient fresh healthy evidence, not availability. |

For a small pilot, collect missing onset/ticket/review/investigation evidence in a customer-approved review worksheet keyed by tenant/integration/incident ID. No new service is needed. Do not upload customer text to AI to fill measurement gaps. Weekly review should examine false alarms, missed incidents, evidence gaps, traffic coverage, latency baselines and resolved/open cohorts before tuning policy. Record policy changes, owner, hypothesis, date and results in the pilot change log; snapshots retain the exact policy and fingerprint used in each decision. This is continuous improvement with an audit trail, rather than a promise of a particular ROI.

## Customer onboarding and shadow-mode pilot

1. **Agree scope.** Select a tenant, one staging integration, owning Ops engineer, expected traffic pattern and measurable pilot criteria. Separate staging/replays from production observation. Define privacy/retention needs and the customer's source of fault/ticket truth.
2. **Create tenant and register integration.** A trusted backend administrator uses the existing CLI with an exported development `DATABASE_URL` (no environment file is loaded):
   ```bash
   .venv/bin/python scripts/admin.py pilot-acme "Acme pilot" --integration workday-payroll
   ```
   The CLI prompts privately for a new 32+ character random workspace bearer token and hashes it. This workspace token is for Ops access, not customer ingestion. The integration initially has category `Custom` and its ID as its name; a trusted administrator can update name/category/owner metadata in the tenant-scoped database. ORM registration creates its default `integration_config` row. Repeat registration for additional integrations using unique workspace credentials with this existing CLI; a full onboarding portal is intentionally absent.
3. **Issue the separate ingestion-only credential.**
   ```bash
   .venv/bin/python scripts/ingestion_keys.py create pilot-acme --name staging-collector
   ```
   Save the full one-time secret privately in the customer's backend secret store. Only its hash and safe metadata are stored. It is scoped to one tenant, accepts ingestion only and provides no policy, database, AI or administrative access. See [external ingestion](EXTERNAL_INGESTION.md) for the existing request example and revocation commands.
4. **Send staging telemetry.** Normalize the customer's request logs into the existing schema: timezone-aware timestamp, tenant/integration identity, stable tenant-unique request ID, HTTP status, latency, and optional errors. Send `POST /api/ingest` using the ingestion credential. Check accepted/rejected/duplicate results, replay an identical batch and verify idempotency. Cross-tenant payloads must fail authorization. Do not reuse a request ID for different providers in the same tenant.
5. **Validate classifications.** Confirm healthy, errors, latency-only, insufficient traffic, outage and recovery against agreed expectations. Verify data/evaluation freshness and actual evaluator schedule. Compare deterministic reason text and thresholds in detail views. The five-to-fifteen-minute configured evaluation cadence is separate from the dashboard's 60-second read refresh. Deploy/configure the existing scheduler explicitly; a running UI alone does not evaluate traffic.
6. **Run in shadow mode.** Send authorized production telemetry to a separate production-observation tenant/environment. Observe → classify → advise → **human acts**. Incidents are records for review; this product has no external notification delivery or remediation actions. Keep existing operational processes as the pilot's authority and manually compare results. Readers cannot trigger paid AI; operator AI requests remain advisory and optional.
7. **Calibrate with Ops.** Use the existing tenant-scoped policy GET/PUT API below, review traffic minima and service expectations per integration, then replay held-out scenarios. Policy changes reset consecutive-window continuity by fingerprint and do not rewrite historical decisions. Allow enough fresh windows for confirmation and recovery before judging a change. Document the review and retain a reference period.
8. **Enable operational use deliberately.** Ops signs off on telemetry coverage, expected behaviors, ownership, runbooks, scheduler readiness, measured pilot evidence and escalation procedure. AI has no right to change policy or close incidents. Any future automated remediation would require a separate explicit authorization/control design; it is not implemented by this accelerator.

## Configurable, reusable health accelerator

The reusable path is **provider adapter → normalized telemetry → shared ingestion → metrics → per-integration policy → snapshots/incidents → operator evidence and optional AI**. Only an adapter/log exporter needs to understand provider-specific log formats; it must never choose health status. Workday, ADP, DocuSign, Greenhouse, Okta, Slack and Twilio demos already use that same path. Salesforce, ServiceNow, SAP, Microsoft Graph and Stripe need telemetry normalization and registration, not a rewritten health engine. Tests exercise those future provider names against the same policy; these tests do not implement or claim live connectors.

Policies are persisted in `integration_config`, validated by `HealthPolicy`, and writable through the existing operator-only endpoint. No source edits or new admin UI are needed:

```bash
# Export API_BASE_URL and an authorized WORKSPACE_TOKEN privately in your process.
curl --fail --silent --show-error \
  -H "Authorization: Bearer $WORKSPACE_TOKEN" \
  "$API_BASE_URL/api/v1/integrations/workday-payroll/config" \
  -o /tmp/brightline-pilot-policy.json
# Edit policy values in this non-secret JSON file, preserving the full contract.
${EDITOR:-vi} /tmp/brightline-pilot-policy.json
curl --fail --silent --show-error -X PUT \
  -H "Authorization: Bearer $WORKSPACE_TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/brightline-pilot-policy.json \
  "$API_BASE_URL/api/v1/integrations/workday-payroll/config"
```

| Customer control | Existing configuration fields |
| --- | --- |
| Error warning / critical / recovery | `error_warning`, `error_critical`, `error_recovery` (fractions, not percentages) |
| Latency target / relative limits | `latency_target_ms`, `latency_warning_multiplier`, `latency_critical_multiplier`, `latency_recovery_multiplier`; baseline lookback/volume/delta settings |
| Evidence minimum | `min_requests` |
| Window and refresh | `evaluation_window_minutes`, `refresh_minutes` |
| Incident confirmation | `unhealthy_bad_windows`, `sustained_degraded_windows` |
| Recovery confirmation | `healthy_recovery_windows` |
| Telemetry freshness | `max_gap_minutes`; evaluation overdue also uses twice `refresh_minutes` |
| Timeouts | `timeout_warning`, `timeout_critical`, `timeout_recovery` |

Reason semantics are shared across integrations; retain current codes for API/audit compatibility:

| Meaning | Existing reusable evidence |
| --- | --- |
| High error rate | `ERROR_RATE_CRITICAL` / `ERROR_RATE_ELEVATED` signal codes |
| Latency degradation | `LATENCY_TARGET_*` / `LATENCY_BASELINE_*` signal codes |
| Sustained failure / confirmation | `UNHEALTHY_CONFIRMATION_PENDING`, `SUSTAINED_DEGRADATION`, persisted bad-window streak |
| Authentication failure | `auth` normalized error category accompanying error-rate evidence; no separate provider-specific status policy |
| Insufficient traffic / stale evidence | `INSUFFICIENT_REQUESTS`, `STALE_TELEMETRY`, `NO_TELEMETRY`; current freshness can supersede historical healthy evidence for display |
| Recovery | `RECOVERY_PENDING`, `RECOVERY_MARGIN_NOT_MET`, recorded healthy-window streak and resolution evidence |

There is no separate fake impact/AI demo path. Counts derive from persisted incidents and the same freshness projection used for real ingestion. Impact queries are tenant-scoped and bounded to incident openings/resolutions in the trailing day; no all-history snapshot scan is needed. For larger volumes, query profiling and lifecycle indexes can be added based on evidence, without new infrastructure.
