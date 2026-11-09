# Official supplied-data replay

The brief explicitly supplies `starter_kit/data/integration_logs.json`: 60 observations across Slack Notifications, ADP Payroll Sync, DocuSign Envelope API, Workday Directory Sync and Greenhouse ATS Sync. The unchanged 8 KiB input is retained at `data/provided/integration_logs.json` because the required implementation must run against it. SHA-256: `ef3e4f8600b8c56274b43f5a9c5ea747c4d7c67fd2f85cedeb734afa4023234b`.

The starter utility is optional and was replaced. It excludes timeout records from its error-rate denominator and averages only successful latency. Our normal metric service includes all attempts, explicit timeouts and latency percentiles. No new classifier is used for this replay.

## Commands from the root

After the README dependency setup:

```sh
.venv/bin/python scripts/replay_official_data.py
```

This runs offline, prints the five persisted decisions with reasons/metrics and exits. It uses disposable SQLite, ignores inherited database configuration and disables OpenAI. No environment file, hosted database or production tenant is accessed. Repeating the command starts a fresh database; stable source-derived request IDs also deduplicate within a replay.

For the existing frontend, stop other local servers and use two terminals:

```sh
.venv/bin/python scripts/replay_official_data.py --rebase-to-now --serve
```

```sh
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm --prefix frontend run dev
```

Open http://localhost:3000. The local SQLite workspace needs no bearer token. The exact historical replay remains historical and correctly becomes current UNKNOWN; explicit rebasing shifts all source timestamps by one constant offset, preserves request order/status/latency and leaves the input file unchanged. It never edits timestamps of stored rows. Finite replay data ages normally; rerun before presenting.

## Normalization and assumptions

| Supplied field | Normalized input |
| --- | --- |
| integration | Fixed registered integration ID; original name retained |
| timezone-free timestamp | Assume UTC; uniform offset only with explicit rebase |
| success/error | Original HTTP code, checked for consistency |
| timeout + null status_code | http_status=504 and timed_out=true; a transport outcome mapping, not an invented provider response |
| latency_ms | Original numeric duration, including 30,000 ms timeouts |
| absent request ID | Deterministic UUID5 from source digest and row index |
| absent tenant | Fixed disposable local Brightline workspace; source input cannot choose another tenant |

A sample-only policy uses 60-minute windows, a five-request floor and 10%/30% error/timeout warning/critical rates. These accommodate twelve observed attempts per provider/hour; one error is already 8.3%. They are not Brightline production targets. Provider latency targets are explicit configuration assumptions (500 ms Slack/Workday, 1,000 ms ADP/DocuSign/Greenhouse), not learned SLAs. Existing P95 multipliers, freshness, two-bad-window confirmation and recovery margins remain unchanged. Two adjacent final buckets provide two policy observations; no prior successful history is invented. The normal defaults remain 15 minutes, twenty requests and 1%/5% thresholds.

## Verified exact result, as of 2026-08-04 10:00 UTC

| Integration | Failures / attempts | Timeout rate | P95 | Health |
| --- | --- | --- | --- | --- |
| Slack Notifications | 1 / 12 (8.33%) | 0% | 150 ms | HEALTHY |
| ADP Payroll Sync | 5 / 12 (41.67%) | 0% | 415 ms | UNHEALTHY |
| DocuSign Envelope API | 4 / 12 (33.33%) | 0% | 880 ms | UNHEALTHY |
| Workday Directory Sync | 1 / 12 (8.33%) | 0% | 132 ms | HEALTHY |
| Greenhouse ATS Sync | 6 / 12 (50%) | 41.67% | 30,000 ms | UNHEALTHY |

`backend/tests/test_official_data.py` checks the exact source digest, all sixty records, timeout handling, policy decisions/incidents, idempotency, unchanged defaults, rebase invariants and historical/current UNKNOWN semantics. Sparse fixture outcomes are not production calibration or verified business impact.
