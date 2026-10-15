"""Reproducible synthetic request metadata: no real users, payloads or secrets."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.health.service import bucket_for

INTEGRATIONS = [
    ("gusto", "Gusto", "Payroll", "Payroll operations", 1000, "errors"),
    ("docusign", "DocuSign", "E-signature", "People operations", 1000, "slow"),
    (
        "greenhouse",
        "Greenhouse",
        "Applicant tracking",
        "Talent operations",
        1200,
        "healthy",
    ),
    ("okta", "Okta", "Directory sync", "IT operations", 800, "healthy"),
    ("slack", "Slack", "Notifications", "People operations", 800, "healthy"),
    ("workday", "Workday", "HR directory", "IT operations", 1200, "stale"),
    ("checkr", "Checkr", "Background checks", "Talent operations", 1000, "sparse"),
    ("adp", "ADP", "Payroll", "Payroll operations", 1000, "recovered"),
]


def generate(at=None, seed=42):
    at = bucket_for(at or datetime.now(timezone.utc))
    rng = np.random.default_rng(seed)
    fake = Faker()
    fake.seed_instance(seed)
    rows = []
    for key, name, category, owner, target, scenario in INTEGRATIONS:
        for minute in range(1440):
            if scenario == "stale" and minute < 60:
                continue
            if scenario == "sparse" and minute % 10:
                continue
            count = 1 if scenario == "sparse" else 3
            for j in range(count):
                occurred = at - timedelta(
                    minutes=minute, seconds=int(rng.integers(1, 59))
                )
                recent = minute < 45
                failed = (scenario == "errors" and recent and j == 0) or (
                    scenario == "recovered" and 40 < minute < 90 and j == 0
                )
                latency = float(max(30, rng.normal(target * 0.35, target * 0.08)))
                if scenario == "slow" and recent:
                    latency = target * float(rng.uniform(1.8, 2.7))
                status = 503 if failed else 200
                rows.append(
                    dict(
                        event_id=f"{key}-{fake.uuid4()}",
                        integration_id=key,
                        occurred_at=occurred.isoformat(),
                        status_code=status,
                        latency_ms=round(latency, 2),
                        timed_out=False,
                        error_category="upstream" if failed else "none",
                    )
                )
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/requests.jsonl")
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = generate()
    path.write_text("".join(json.dumps(x) + "\n" for x in rows))
    print(f"Wrote {len(rows)} synthetic events to {path}")
