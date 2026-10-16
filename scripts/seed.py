"""Seed synthetic demo tenants using the same offline generator as tests."""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import get_settings
from app.db.migrations import initialize_database
from app.db.session import get_engine
from app.health.service import bucket_for, refresh
from app.ingestion.service import ingest
from app.models.entities import Integration, Tenant
from generate_synthetic_data import (
    SCENARIOS,
    generate_events,
    integrations_for,
    tenant_specs,
    validate_options,
)


def seed(*, scenario="all", duration_minutes=90, tenants=3, random_seed=42):
    settings = get_settings()
    if settings.app_env not in ("demo", "test"):
        raise SystemExit(
            "Seed is local/demo-only. Use admin.py to provision production tenants."
        )
    at = bucket_for(datetime.now(timezone.utc))
    start = at - timedelta(minutes=duration_minutes)
    validate_options(scenario, duration_minutes, tenants, random_seed, start)
    engine = get_engine()
    initialize_database(engine)
    events = 0
    with Session(engine) as db:
        created = []
        for tenant in tenant_specs(tenants, random_seed):
            if db.get(Tenant, tenant["id"]):
                continue
            db.add(Tenant(**tenant))
            db.flush()
            for spec in integrations_for(scenario):
                db.add(
                    Integration(
                        tenant_id=tenant["id"],
                        id=spec.id,
                        name=spec.name,
                        category=spec.type,
                        owner=spec.owner,
                        latency_target_ms=spec.latency_target_ms,
                        max_gap_minutes=spec.max_gap_minutes,
                    )
                )
            created.append(tenant["id"])
        if not created:
            print(
                "Requested demo tenants already exist; no data changed. See data/synthetic/README.md for isolated reseeding."
            )
            return
        db.commit()
        pending = []
        pending_tenant = None
        for event in generate_events(
            scenario=scenario,
            duration_minutes=duration_minutes,
            tenants=tenants,
            seed=random_seed,
            start=start,
        ):
            if event["tenant_id"] not in created:
                continue
            if pending and (
                pending_tenant != event["tenant_id"] or len(pending) == 1000
            ):
                result = ingest(
                    db,
                    pending_tenant,
                    pending,
                    allow_historical=True,
                    now=at,
                    source_type="DEMO",
                )
                if result["rejected"]:
                    raise ValueError("Generated records failed ingestion validation")
                events += result["accepted"]
                pending.clear()
            pending_tenant = event["tenant_id"]
            pending.append(event)
        if pending:
            result = ingest(
                db,
                pending_tenant,
                pending,
                allow_historical=True,
                now=at,
                source_type="DEMO",
            )
            if result["rejected"]:
                raise ValueError("Generated records failed ingestion validation")
            events += result["accepted"]
        for tenant_id in created:
            for offset in range(5, duration_minutes + 1, 5):
                refresh(db, tenant_id, start + timedelta(minutes=offset))
    print(
        f"Seeded {len(created)} tenants, {len(created) * len(integrations_for(scenario))} integration series and {events} events."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument(
        "--duration", type=int, default=90, help="Minutes; multiple of 5, minimum 60"
    )
    parser.add_argument("--tenants", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        seed(
            scenario=args.scenario,
            duration_minutes=args.duration,
            tenants=args.tenants,
            random_seed=args.seed,
        )
    except ValueError as exc:
        parser.error(str(exc))
