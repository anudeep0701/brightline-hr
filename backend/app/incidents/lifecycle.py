"""Project confirmed state transitions into incidents; policy owns all hysteresis."""

from sqlalchemy import select

from app.models.entities import Incident


def advance(session, snapshot):
    current = session.scalar(
        select(Incident).where(
            Incident.tenant_id == snapshot.tenant_id,
            Incident.integration_id == snapshot.integration_id,
            Incident.resolved_at.is_(None),
        )
    )
    if current is None and snapshot.status == "UNHEALTHY":
        current = Incident(
            tenant_id=snapshot.tenant_id,
            integration_id=snapshot.integration_id,
            opening_snapshot_id=snapshot.id,
            last_snapshot_id=snapshot.id,
            opened_at=snapshot.bucket,
            recovery_streak=0,
        )
        session.add(current)
    if current is not None:
        current.last_snapshot_id = snapshot.id
        current.recovery_streak = snapshot.healthy_window_streak
        if snapshot.status == "HEALTHY":
            current.resolved_at = snapshot.bucket
