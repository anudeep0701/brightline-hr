"""Compatibility entrypoint; new consumers should use generate_synthetic_data.py."""

from datetime import datetime, timedelta, timezone

from generate_synthetic_data import CATALOG, generate_events, to_ingestion_event
from generate_synthetic_data import main as synthetic_main

INTEGRATIONS = [
    (x.id, x.name, x.type, x.owner, x.latency_target_ms, x.scenario) for x in CATALOG
]


def generate(at=None, seed=42):
    """Legacy single-tenant ingestion shape; explicit at gives reproducibility."""
    at = at or datetime.now(timezone.utc)
    at = at.astimezone(timezone.utc)
    at = at.replace(minute=at.minute // 5 * 5, second=0, microsecond=0)
    return [
        to_ingestion_event(event)
        for event in generate_events(
            start=at - timedelta(minutes=90), duration_minutes=90, tenants=1, seed=seed
        )
    ]


if __name__ == "__main__":
    raise SystemExit(synthetic_main())
