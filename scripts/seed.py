"""Initialize a local/demo dataset; never resets or deletes existing customer data."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import get_settings
from app.db.session import get_engine
from app.health.service import bucket_for, refresh
from app.models.entities import Base, Integration, RequestLog, Tenant
from generate_data import INTEGRATIONS, generate


def seed():
    settings = get_settings()
    if settings.app_env not in ("demo", "test"):
        raise SystemExit(
            "Seed is local/demo-only. Use admin.py to provision production tenants."
        )
    engine = get_engine()
    Base.metadata.create_all(engine)
    at = bucket_for(datetime.now(timezone.utc))
    with Session(engine) as db:
        if db.get(Tenant, "brightline"):
            print(
                "Demo already exists; no data changed. Remove the local demo database explicitly to regenerate."
            )
            return
        db.add(Tenant(id="brightline", name="Brightline HR"))
        db.flush()
        for key, name, category, owner, target, scenario in INTEGRATIONS:
            db.add(
                Integration(
                    tenant_id="brightline",
                    id=key,
                    name=name,
                    category=category,
                    owner=owner,
                    latency_target_ms=target,
                    max_gap_minutes=30,
                )
            )
        db.flush()
        rows = generate(at)
        for row in rows:
            row["occurred_at"] = datetime.fromisoformat(row["occurred_at"])
            db.add(RequestLog(tenant_id="brightline", **row))
        db.commit()
        for minutes_ago in range(120, -1, -5):
            refresh(db, "brightline", at - timedelta(minutes=minutes_ago))
    print(
        f"Seeded 8 integrations and {len(rows)} events; 25 historical evaluation buckets."
    )


if __name__ == "__main__":
    seed()
