# Deterministic health engine — 2026-10-v2

The engine evaluates request telemetry, without an OpenAI client, prompt, inference call or enrichment dependency. FastAPI refresh calls Polars metrics, a pure Python policy/state machine, and a transactional snapshot/incident projection. AI assistance is a separate operator action after a decision is persisted.

## Configuration and defaults

`backend/app/health/config.py::HealthPolicy` is the sole source of live defaults. Every field persists on the tenant's `integration_config` row. The ORM constructor and admin tooling read those defaults; the classifier never uses duplicate hardcoded threshold values. SQL migration literals are immutable records of initialization defaults, not a second runtime policy.

| Setting | Default | Meaning |
| --- | --- | --- |
| evaluation_window_minutes | 15 | Event-time rolling interval |
| refresh_minutes | 5 | One decision per completed cadence bucket; allowed 5, 10 or 15 |
| min_requests | 20 | Minimum evidence before any confident classification |
| max_gap_minutes | 30 | Expected request activity/freshness interval |
| latency_target_ms | 1000 | Provider-specific absolute P95 reference |
| error_warning / error_critical | 0.01 / 0.05 | Inclusive warning/critical error fractions |
| timeout_warning / timeout_critical | 0.01 / 0.05 | Inclusive warning/critical timeout fractions |
| error_recovery / timeout_recovery | 0.005 / 0.005 | Maximum fractions allowed to count a recovery window |
| latency_warning_multiplier / latency_critical_multiplier | 1.5 / 3 | Inclusive P95 warning/critical ratios |
| latency_recovery_multiplier | 1.25 | Maximum P95 ratio allowed during recovery |
| baseline_enabled | true | Use eligible historical latency evidence |
| baseline_lookback_minutes | 1440 | Historical period before the current window begins |
| baseline_min_requests | 100 | Minimum historical sample |
| baseline_min_delta_ms | 100 | Minimum absolute P95 change before comparing baseline ratios |
| unhealthy_bad_windows | 2 | Adjacent bad observations required to confirm critical state |
| sustained_degraded_windows | 3 | Adjacent moderate observations that escalate to unhealthy |
| healthy_recovery_windows | 2 | Adjacent clean observations required to leave a bad state and resolve an incident |
| top_error_limit | 5 | Number of ranked error categories returned |

Validation requires ordered warning/critical thresholds, stricter recovery margins, a window covering the cadence, positive sample counts, finite rates/ratios, at least two confirmation/recovery windows, and sustained escalation that cannot bypass confirmation. Corresponding PostgreSQL constraints protect common invalid direct writes. Use the typed API for updates rather than bypassing validation through SQL.

Authenticated endpoints:

- `GET /api/v1/integrations/{id}/config`: reader or operator; returns the complete policy.
- `PUT /api/v1/integrations/{id}/config`: operator; validates and replaces the policy. Omitted fields take documented defaults, so use GET, edit values, then PUT to preserve other settings.

Configuration writes use the same tenant lock as ingestion and refresh. A SHA-256 configuration fingerprint is stored on every result. A changed fingerprint resets confirmation/recovery counters for the next decision. Previously saved metrics, thresholds and reasons never change. A policy change within an already evaluated bucket takes effect in the next bucket.

## Metrics and window boundaries

For completed bucket T and configured width W, the current interval is **[T−W, T)**. Events at the start are included; events exactly at T or later are excluded. Retries are distinct attempts, not unique business workflows. Duplicated request IDs are deduplicated at ingestion before metrics calculation.

Each result contains request_count, success_count, error_count, error_rate, timeout_count, timeout_rate, p50_ms, p95_ms, p99_ms, error_categories and ranked top_error_categories. HTTP ≥400 and timeouts are failures. Explicit timeout flags and HTTP 408/504 count as timeouts, including requests with a misleading HTTP 200 plus an explicit timeout flag. Success count is the remaining non-failed attempts. Empty windows return null rates/percentiles rather than suggesting zero-error health.

Latency percentiles use Polars **nearest** quantiles over all observed attempts, including failed/timeout durations. Error categories are derived from status/timeout with one shared categorizer: timeout, auth, rate_limit, upstream and validation. Categories sort by descending count, then name for deterministic tie-breaking. Fractions in the top-category list are proportions of failures, not all requests. P99 is an investigation signal; P95 drives classification to avoid a single tail outlier dominating a small sample. Twenty events is a policy sufficiency floor, not a claim that P99 is statistically precise at that volume.

Daily counts/error rate are separately labeled 24-hour context. They do not wash out current-window failures. Rollups preserve the actual configured interval and the metrics; linked snapshots preserve the decision and policy.

## Historical comparison

Baseline history is **[T−W−lookback, T−W)** and does not overlap the current window. It is calculated from distinct raw events, not an average of overlapping snapshot percentiles. The baseline is eligible only with enough requests, error/timeout rates below the warning thresholds, positive P95, and P95 below the absolute latency warning threshold. Dirty or sparse history falls back to the configured target; no baseline does not force UNKNOWN when current samples and an explicit target suffice.

Compare P95 against the absolute target and, when eligible, the historical P95. Baseline comparison additionally requires the configured absolute delta, preventing tiny millisecond changes against near-zero baselines from producing exaggerated ratios. The worst breached signal wins; a historically slow baseline cannot excuse violation of the absolute target. Error/timeout rates use absolute thresholds because ratios against a zero-error baseline are unstable. Baseline use, eligibility reason, underlying metrics and interval are saved in evidence.

## Observed versus stabilized state

The observed state describes one current window:

- UNKNOWN: stale/missing telemetry, too few requests, or incomplete required metrics. There is **no low-volume burst exception** in v2.
- HEALTHY: sufficient current evidence, no error/timeout warning, and P95 within applicable target/baseline boundaries.
- DEGRADED: at least one warning signal.
- UNHEALTHY: at least one critical signal.

A separate pure state machine produces the stabilized `status`:

1. The first critical observation is displayed as DEGRADED with `UNHEALTHY_CONFIRMATION_PENDING`. After the configured adjacent bad-window count, a critical observation confirms UNHEALTHY and opens an incident. Bad means observed DEGRADED or UNHEALTHY; a moderate window followed by a critical window can therefore confirm ongoing trouble.
2. Moderate degradation remains DEGRADED initially. Reaching the configured consecutive moderate-window limit confirms UNHEALTHY with `SUSTAINED_DEGRADATION`, even without a critical metric breach.
3. A confirmed UNHEALTHY state stays active through moderate observations. A raw HEALTHY observation must meet the tighter recovery thresholds and the consecutive recovery count before the state becomes HEALTHY. Pending recovery retains the prior bad state with an explicit reason. The same recovery gate prevents DEGRADED/HEALTHY boundary flapping even when no incident has opened.
4. UNKNOWN is shown immediately when evidence is insufficient. It resets counters and never closes an incident. Returning fresh healthy evidence after UNKNOWN still requires the full recovery count for an open incident.
5. Counters advance only when snapshot buckets are exactly one configured cadence apart and configuration fingerprints match. Gaps, unknowns and policy changes reset streaks. Existing open incidents are retained until newly confirmed recovery.

For example, with default settings: critical → critical produces DEGRADED → UNHEALTHY and one incident. Moderate → moderate → moderate produces DEGRADED → DEGRADED → UNHEALTHY. After confirmed unhealthy, clean → clean produces UNHEALTHY (recovery pending) → HEALTHY (incident resolved). A single bad window followed by clean → clean produces DEGRADED → DEGRADED → HEALTHY without opening an incident.

These are adjacent **rolling** observations, not statistically independent windows: at a five-minute cadence, fifteen-minute windows overlap. A real one-minute outage can contaminate multiple evaluations and legitimately confirm an incident. The synthetic brief-spike case has an isolated error and latency outlier below the rolling thresholds. Hysteresis does not promise to suppress every short outage.

## Result and incident audit

Every newly calculated result and API snapshot exposes canonical uppercase status, observed_status, metrics, evidence_sufficient, confidence, reason_code, deterministic reason_text and evaluated_at. It also records the bucket, counters, policy version, complete configuration, fingerprint, signal reason codes, baseline evidence and recovery/continuity facts.

`confidence` is an **evidence sufficiency score**, not a probability that the integration works. It is min(current request count / required count, 1) for fresh telemetry, zero for stale/missing/incomplete required evidence. `evidence_sufficient` states whether classification requirements actually passed. Sparse UNKNOWN windows may have a fractional evidence score. Severity scores 100/60/0 are ordinal presentation bands and UNKNOWN has no severity score; they are not uptime percentages.

Primary reason codes include NO_TELEMETRY, STALE_TELEMETRY, INSUFFICIENT_REQUESTS, INCOMPLETE_METRICS, WITHIN_POLICY, ERROR_RATE_ELEVATED/CRITICAL, TIMEOUT_RATE_ELEVATED/CRITICAL, LATENCY_TARGET_ELEVATED/CRITICAL, LATENCY_BASELINE_ELEVATED/CRITICAL, UNHEALTHY_CONFIRMATION_PENDING, SUSTAINED_DEGRADATION, UNHEALTHY_RECOVERY_REQUIRED, RECOVERY_PENDING and RECOVERY_MARGIN_NOT_MET. Individual breached signals remain in evidence even when a state-machine reason is primary.

Only confirmed UNHEALTHY opens an incident. Further observations update the active incident's last snapshot/recovery count. Confirmed HEALTHY resolves it; no second incident-specific recovery counter delays resolution again. UNKNOWN never resolves it. A later newly confirmed breach creates a new incident. The partial unique index enforces one open incident per tenant/integration.

## Scheduling, migration and verification

The Vercel cron trigger remains every five minutes. Each integration uses its own configured 5/10/15-minute bucket and skips already evaluated buckets. The browser refreshes views every sixty seconds. The legacy refresh response `bucket` reports the scheduler base tick; each snapshot carries its actual integration-specific bucket and window. Manual/repeated/concurrent calls are idempotent, and older refresh timestamps cannot rewind history or incidents. The dashboard labels evaluations overdue after two configured cadences as unknown without rewriting historical decisions.

Apply `scripts/migrate.py` to add `003_health_engine.sql` after the preserving storage migrations. It initializes policy fields, upgrades status spelling to uppercase and adds result/counter columns. Legacy snapshots retain original metrics/policy evidence and are labeled LEGACY_SNAPSHOT with no invented sufficiency/confidence. Their streaks reset. Existing open incidents are preserved. SQLite demo files from earlier schema versions are refused; choose a fresh ignored demo file. No environment file or secret is changed by this feature.

Tests cover inclusive boundaries, low traffic, all requested metrics, disjoint baseline windows, contaminated baselines, tighter recovery margins, critical confirmation, sustained degradation, skipped windows, unknown during incidents, policy changes, different cadences, re-opening, storage/API contracts and an AI client that raises if called. Synthetic scenarios run through the real engine. PostgreSQL upgrade/concurrency execution remains a CI check when a local database is unavailable.

Operational latency is intentional: initial degraded evidence can appear after one cadence; default critical confirmation usually requires up to two cadences plus ingestion delay. Sustained moderate degradation requires three; recovery requires rolling-window washout plus the configured clean observations. Calibrate policy with production logs and operator feedback before changing defaults. Current analytics loads bounded history into Polars; large tenants need measured capacity planning/rollups before scaling beyond the pilot.
