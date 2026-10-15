"""Run only against an isolated empty test database (CI provisions one)."""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.session import get_engine
from app.health.service import bucket_for, refresh
from app.models.entities import Incident, Integration, RequestLog, Snapshot, Tenant
from migrate import migrate

migrate()
migrate()
engine = get_engine()
tenant = "ci-" + uuid4().hex
at = bucket_for(datetime.now(timezone.utc))
try:
    with Session(engine) as db:
        db.add(Tenant(id=tenant, name="CI isolation"))
        db.flush()
        db.add(
            Integration(
                tenant_id=tenant,
                id="payroll",
                name="Payroll",
                category="Payroll",
                owner="Ops",
                latency_target_ms=1000,
                max_gap_minutes=30,
            )
        )
        db.flush()
        for n in range(30):
            db.add(
                RequestLog(
                    tenant_id=tenant,
                    integration_id="payroll",
                    event_id=str(n),
                    occurred_at=at - timedelta(seconds=n + 1),
                    status_code=503,
                    latency_ms=100,
                    timed_out=False,
                    error_category="upstream",
                )
            )
        db.commit()

    def run(_):
        with Session(engine) as db:
            return refresh(db, tenant, at)["created"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(results) == [0, 1], results
    with Session(engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Incident)
                .where(Incident.tenant_id == tenant)
            )
            == 1
        )
        assert (
            db.scalar(select(Snapshot.status).where(Snapshot.tenant_id == tenant))
            == "unhealthy"
        )
        enabled = (
            db.execute(
                text(
                    "SELECT relname FROM pg_class WHERE relrowsecurity AND relname IN ('tenants','access_tokens','integrations','request_logs','health_snapshots','incidents','enrichments')"
                )
            )
            .scalars()
            .all()
        )
        assert len(enabled) == 7
    print(
        "PostgreSQL migrations, RLS flags, concurrent refresh and incident uniqueness passed"
    )
finally:
    with engine.begin() as connection:
        for table in (
            "incidents",
            "health_snapshots",
            "request_logs",
            "integrations",
            "tenants",
        ):
            column = "id" if table == "tenants" else "tenant_id"
            connection.execute(
                text(f"DELETE FROM {table} WHERE {column}=:tenant"), {"tenant": tenant}
            )
