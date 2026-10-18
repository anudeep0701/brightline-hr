# Reproducible synthetic integration telemetry

All records are generated offline. Names are fictional; error messages are static synthetic text, never copied from customer logs. No configuration, `.env.local`, database, or external API is read by the generator.

## Generate

From the repository root, after installing `backend/requirements-dev.txt`:

```bash
.venv/bin/python scripts/generate_synthetic_data.py \
  --scenario all --duration 90 --tenants 3 --seed 42
```

Default output is `data/synthetic/generated/requests.jsonl` plus `manifest.json`. The output directory is ignored by Git. The manifest records the seed, generator version, UTC interval, fictional tenants, event counts by scenario, and dataset SHA-256. Only those two generated files are replaced when rerunning into the same output directory.

Arguments:

| Argument | Meaning |
| --- | --- |
| `--scenario` | `all` or one of the ten names below |
| `--duration` / `--duration-minutes` | Integer minutes, a multiple of five and at least 60; default 90 |
| `--tenants` / `--num-tenants` | Positive tenant count; default 3 |
| `--seed` | Nonnegative deterministic random seed; default 42 |
| `--start` | Timezone-aware ISO timestamp aligned to a five-minute boundary; default `2026-10-15T12:00:00+00:00` |
| `--output` | Output directory; default `data/synthetic/generated` |

The fixed default start means the same command produces identical bytes, independent of execution time. Use the locked dependency versions for reproducibility across machines. An explicit start, duration, scenario or seed changes the requested dataset. Each tenant/integration has an independent NumPy random stream, so adding tenants does not alter existing tenants' events. Faker generates fictional tenant display names; request IDs use UUID5. Within a dataset, request IDs are globally unique. Files are grouped by tenant and integration, then chronologically within each series; they are not globally time-sorted. The generator streams events to avoid retaining the full output in memory.

The minimum duration provides enough baseline, rolling-window washout and two consecutive healthy recovery checks. This deliberately avoids silently generating truncated recovery examples.

## Scenarios and expected operational behavior

`all` creates ten integration series per tenant, including all seven requested providers. A focused scenario applies that scenario to each of the seven base providers for comparison across latency targets.

| Scenario | Default series | Construction / expected outcome |
| --- | --- | --- |
| `healthy` | Workday Payroll | Variable load and lognormal latency below its target; healthy |
| `elevated_error_rate` | ADP Payroll | Every ninth request fails with a mixture of 429/503; unhealthy even with low latency |
| `latency_only_degradation` | DocuSign | All requests succeed, durations 1.7–2.7× target; initially degraded by P95 alone; sustained degradation confirms unhealthy under the default three-window policy |
| `complete_outage` | Greenhouse ATS | All attempts fail; mixture of fast 503 responses and 30-second 504 timeouts; unhealthy |
| `intermittent_failure` | Okta Directory Sync | Five-minute failure bursts every fifteen minutes; rolling windows capture recurring instability |
| `authentication_failures` | Slack Notifications | Fast 401 responses with `AUTH_TOKEN_EXPIRED`; unhealthy, demonstrating that fast is not healthy |
| `low_traffic` | Twilio Notifications | One request every ten minutes; fresh but insufficient evidence, unknown |
| `recovery_after_incident` | ADP Payroll (Recovery) | Healthy baseline, a 50% error period, then sustained healthy traffic; incident opens and resolves after rolling errors expire and two adjacent healthy checks |
| `brief_spike` | Slack Notifications (Brief spike) | One failed request plus one 6× latency outlier in one minute; visible in raw logs, but below 1% errors and below P95 influence in rolling windows; no incident |
| `sustained_bad_windows` | Workday Payroll (Sustained failures) | Healthy baseline followed by 50% errors through the end; consecutive bad windows leave an open incident |

Incident phases begin around one third of the requested duration. Recovery begins after a further quarter-duration (leaving at least 25 minutes to observe recovery). Failure placement is deterministic rather than probability-only, so a random draw cannot accidentally omit the operational scenario. Traffic count, event timing and durations remain seeded and varied. A provider's complete outage still produces failed request attempts; it does not model an exporter that stops emitting telemetry.

The brief spike is intentionally a small error/tail-latency spike. A minute of 100% failures at this traffic volume can breach the rolling policy across adjacent observations and correctly confirm an incident. The v2 engine applies documented confirmation/recovery hysteresis; the generator does not hide genuine repeated bad observations.

## Event schema

Every JSONL record contains `timestamp`, `tenant_id`, `integration_id`, `integration_name`, `integration_type`, `request_id`, `http_status`, `latency_ms`, `error_code`, and `error_message`, plus `scenario`, `timed_out`, and `latency_target_ms`. Timestamps are UTC ISO strings. Successful requests have JSON `null` error code/message. Errors use consistent status/code/message mappings. No request bodies, tokens, email addresses or phone numbers are included.

`to_ingestion_event(event)` converts a rich synthetic record into the existing API's sanitized schema. It drops tenant identity, names, error messages and other export-only fields. For HTTP ingestion, group records by tenant, authenticate with that tenant's token, and send batches of at most 1000. Fixed historical examples may fall outside the API's seven-day ingestion range; generate a recent explicit interval when testing HTTP ingestion. The generator itself never sends HTTP requests.

## Committed sample

`sample/` contains **two tenants, twenty series, 11,422 events, and all ten scenarios over sixty minutes**. Regenerate it exactly with:

```bash
.venv/bin/python scripts/generate_synthetic_data.py \
  --scenario all --duration 60 --tenants 2 --seed 42 \
  --output data/synthetic/sample
```

The corresponding default start is fixed. Tests verify both committed files byte-for-byte and check the manifest digest.

## Demo and tests

The demo imports this same generator, anchors its interval to the current completed five-minute boundary, loads sanitized records, and replays health evaluations in time order:

```bash
APP_ENV=demo DATABASE_URL=sqlite:///./data/synthetic-demo.db \
  .venv/bin/python scripts/seed.py --scenario all --duration 90 --tenants 3 --seed 42
```

Use a new ignored local database path for a fresh demo instead of modifying an existing database. To view this example, run the backend with the same `DATABASE_URL` (use an absolute database path or adjust it for the backend working directory). Existing tenant IDs are preserved without modifying their integrations/logs. The first tenant is `brightline` for compatibility with the local demo's identity; other tenants are `tenant-002`, `tenant-003`, etc. Other tenants can be inspected in the database or accessed using their own tokens provisioned by the existing admin CLI. Seeds are confined to `APP_ENV=demo` or `test`; production seeding is refused.

Tests import the generator directly, validate all exported events through the sanitized Pydantic ingestion schema, and replay each scenario through the actual metric, health and incident services:

```bash
cd backend
../.venv/bin/pytest -q
```

`generate_data.py` remains a compatibility wrapper around the new generator; it no longer implements a separate dataset.


For a fresh scenario without selecting/removing a persistent database, use `.venv/bin/python scripts/run_demo.py --scenario all`. It creates temporary data, replays evaluations and starts a keyless local backend. Stop/restart it with a focused scenario to reload fresh logs. See [dashboard/demo walkthrough](../../docs/DASHBOARD_AND_DEMO.md) for all five requested scenario commands.
