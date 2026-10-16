"""Measured lifecycle outcomes; no inferred fault onset, tickets or notification ROI."""

from datetime import timedelta
from statistics import mean

from sqlalchemy import and_, or_, select

from app.metrics.calculation import utc
from app.models.entities import Incident


def operational_impact(db, tenant_id, items, now):
    end = utc(now)
    start = end - timedelta(hours=24)
    rows = db.execute(
        select(Incident.opened_at, Incident.resolved_at).where(
            Incident.tenant_id == tenant_id,
            or_(
                and_(Incident.opened_at >= start, Incident.opened_at < end),
                and_(Incident.resolved_at >= start, Incident.resolved_at < end),
            ),
        )
    ).all()
    durations = [
        (utc(resolved) - utc(opened)).total_seconds()
        for opened, resolved in rows
        if resolved is not None and start <= utc(resolved) < end
    ]
    states = [item["freshness"]["current_evidence_status"] for item in items]
    healthy = states.count("HEALTHY")
    return dict(
        period_start=start,
        period_end=end,
        integrations_requiring_attention=len(states) - healthy,
        healthy_percentage=100 * healthy / len(states) if states else None,
        unknown_integrations=states.count("UNKNOWN"),
        stale_or_absent_integrations=sum(
            item["freshness"]["status"] != "RECENT_TRAFFIC"
            or item["freshness"]["evaluation_overdue"]
            for item in items
        ),
        incidents_detected=sum(start <= utc(opened) < end for opened, _ in rows),
        recovered_incidents=len(durations),
        mean_confirmed_incident_duration_seconds=mean(durations) if durations else None,
    )
