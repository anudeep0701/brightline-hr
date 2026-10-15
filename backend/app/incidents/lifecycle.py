from datetime import timedelta

from sqlalchemy import select

from app.metrics.calculation import utc
from app.models.entities import Incident, Snapshot


def advance(session, snapshot):
    current = session.scalar(
        select(Incident).where(
            Incident.tenant_id == snapshot.tenant_id,
            Incident.integration_id == snapshot.integration_id,
            Incident.resolved_at.is_(None),
        )
    )
    if snapshot.status in ("degraded", "unhealthy"):
        if current is None:
            current = Incident(
                tenant_id=snapshot.tenant_id,
                integration_id=snapshot.integration_id,
                opening_snapshot_id=snapshot.id,
                last_snapshot_id=snapshot.id,
                opened_at=snapshot.bucket,
                recovery_streak=0,
            )
            session.add(current)
        current.recovery_streak = 0
    elif current is not None:
        previous = session.get(Snapshot, current.last_snapshot_id)
        consecutive = utc(snapshot.bucket) - utc(previous.bucket) == timedelta(
            minutes=5
        )
        current.recovery_streak = (
            (current.recovery_streak + 1 if consecutive else 1)
            if snapshot.status == "healthy"
            else 0
        )
        if current.recovery_streak >= 2:
            current.resolved_at = snapshot.bucket
    if current is not None:
        current.last_snapshot_id = snapshot.id
