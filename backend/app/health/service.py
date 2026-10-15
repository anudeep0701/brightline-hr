from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.health.policy import evaluate
from app.incidents.lifecycle import advance
from app.metrics.calculation import calculate
from app.models.entities import Integration, RequestLog, Snapshot, Tenant


def bucket_for(now):
    return now.astimezone(timezone.utc).replace(
        minute=(now.minute // 5) * 5, second=0, microsecond=0
    )


def refresh(session, tenant_id, now=None):
    now = now or datetime.now(timezone.utc)
    bucket = bucket_for(now)
    # All tenant mutations use the same lock; snapshot uniqueness provides a second guard.
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    created = 0
    for integration in session.scalars(
        select(Integration).where(Integration.tenant_id == tenant_id)
    ):
        existing = session.scalar(
            select(Snapshot).where(
                Snapshot.tenant_id == tenant_id,
                Snapshot.integration_id == integration.id,
                Snapshot.bucket == bucket,
            )
        )
        if existing:
            continue
        logs = session.scalars(
            select(RequestLog).where(
                RequestLog.tenant_id == tenant_id,
                RequestLog.integration_id == integration.id,
                RequestLog.occurred_at >= bucket - timedelta(hours=24),
                RequestLog.occurred_at < bucket,
            )
        ).all()
        result = evaluate(
            calculate(logs, bucket),
            bucket,
            integration.latency_target_ms,
            integration.max_gap_minutes,
        )
        snapshot = Snapshot(
            tenant_id=tenant_id,
            integration_id=integration.id,
            bucket=bucket,
            evaluated_at=now,
            **result,
        )
        session.add(snapshot)
        session.flush()
        advance(session, snapshot)
        created += 1
    session.commit()
    return dict(created=created, bucket=bucket.isoformat())
