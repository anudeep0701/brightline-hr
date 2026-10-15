# Synthetic data
Run `python scripts/generate_data.py` from the repository root to generate ignored JSONL metadata. Fixed seed 42 and an explicit UTC anchor make scenarios reproducible. `seed.py` loads this generator directly without requiring JSONL files.

Scenarios: Gusto error outage; DocuSign latency degradation; Greenhouse, Okta, Slack healthy; Workday telemetry gap; Checkr sparse traffic; ADP historical outage and recovery. Each integration uses its own latency target. Synthetic owner labels are teams, not real people. Demo data does not continuously advance; reseed deliberately after it becomes stale.
