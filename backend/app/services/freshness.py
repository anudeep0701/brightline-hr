"""Current evidence freshness, separate from immutable historical health decisions."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.metrics.calculation import utc
from app.models.entities import RequestEvent


def latest_telemetry(db, tenant_id, integration_id=None):
    statement = select(
        RequestEvent.integration_id,
        func.max(RequestEvent.occurred_at),
        func.max(RequestEvent.received_at),
    ).where(RequestEvent.tenant_id == tenant_id)
    if integration_id is not None:
        statement = statement.where(RequestEvent.integration_id == integration_id)
    return {
        row[0]: (row[1], row[2])
        for row in db.execute(statement.group_by(RequestEvent.integration_id))
    }


def freshness(integration, snapshot, telemetry, now=None):
    now = now or datetime.now(timezone.utc)
    last_event, last_received = telemetry or (None, None)
    recent = bool(
        last_event
        and timedelta(0)
        <= now - utc(last_event)
        <= timedelta(minutes=integration.config.max_gap_minutes)
    )
    overdue = not snapshot or now - utc(snapshot.bucket) > timedelta(
        minutes=integration.config.refresh_minutes * 2
    )
    return dict(
        status="RECENT_TRAFFIC"
        if recent
        else "STALE_TELEMETRY"
        if last_event
        else "NO_TELEMETRY",
        current_evidence_status=snapshot.status
        if recent and not overdue
        else "UNKNOWN",
        last_event_at=utc(last_event) if last_event else None,
        last_event_received_at=utc(last_received) if last_received else None,
        last_evaluated_at=utc(snapshot.evaluated_at) if snapshot else None,
        evaluation_overdue=overdue,
        max_gap_minutes=integration.config.max_gap_minutes,
    )
