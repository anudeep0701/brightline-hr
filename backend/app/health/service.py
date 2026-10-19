from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.health.config import DEFAULT_POLICY, HealthPolicy
from app.health.policy import evaluate
from app.incidents.lifecycle import advance
from app.metrics.calculation import calculate, utc
from app.models.entities import (
    Incident,
    Integration,
    MetricRollup,
    RequestLog,
    Snapshot,
    Tenant,
)


def bucket_for(now, cadence_minutes=DEFAULT_POLICY.refresh_minutes):
    seconds = cadence_minutes * 60
    return datetime.fromtimestamp(
        int(utc(now).timestamp()) // seconds * seconds, timezone.utc
    )


def snapshot_context(snapshot):
    if snapshot is None:
        return None
    return dict(
        bucket=utc(snapshot.bucket).isoformat(),
        status=snapshot.status,
        configuration_fingerprint=snapshot.evidence.get("configuration_fingerprint"),
        bad_window_streak=snapshot.bad_window_streak,
        degraded_window_streak=snapshot.degraded_window_streak,
        healthy_window_streak=snapshot.healthy_window_streak,
    )


def refresh(session, tenant_id, now=None, *, commit=True):
    now = utc(now or datetime.now(timezone.utc))
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    created = 0
    for integration in session.scalars(
        select(Integration).where(Integration.tenant_id == tenant_id)
    ):
        config = HealthPolicy.model_validate(integration.config)
        bucket = bucket_for(now, config.refresh_minutes)
        previous = session.scalar(
            select(Snapshot)
            .where(
                Snapshot.tenant_id == tenant_id,
                Snapshot.integration_id == integration.id,
            )
            .order_by(Snapshot.bucket.desc())
            .limit(1)
        )
        # Never rewrite an existing decision or rewind the incident state machine.
        if previous is not None and utc(previous.bucket) >= bucket:
            continue
        active = session.scalar(
            select(Incident).where(
                Incident.tenant_id == tenant_id,
                Incident.integration_id == integration.id,
                Incident.resolved_at.is_(None),
            )
        )
        start = bucket - timedelta(minutes=config.evaluation_window_minutes)
        earliest = min(
            bucket - timedelta(days=1),
            start - timedelta(minutes=config.baseline_lookback_minutes),
        )
        logs = session.scalars(
            select(RequestLog).where(
                RequestLog.tenant_id == tenant_id,
                RequestLog.integration_id == integration.id,
                RequestLog.occurred_at >= earliest,
                RequestLog.occurred_at < bucket,
            )
        ).all()
        metrics = calculate(logs, bucket, config)
        rollup = MetricRollup(
            tenant_id=tenant_id,
            integration_id=integration.id,
            window_start=start,
            window_end=bucket,
            calculated_at=now,
            metrics=metrics,
        )
        session.add(rollup)
        session.flush()
        result = evaluate(
            metrics,
            bucket,
            config,
            previous=snapshot_context(previous),
            incident_open=active is not None,
            evaluated_at=now,
        )
        result.pop(
            "metrics"
        )  # Metrics are stored in the linked rollup and immutable evidence.
        snapshot = Snapshot(
            tenant_id=tenant_id,
            integration_id=integration.id,
            bucket=bucket,
            metric_rollup_id=rollup.id,
            **result,
        )
        session.add(snapshot)
        session.flush()
        advance(session, snapshot)
        created += 1
    if commit:
        session.commit()
    return dict(created=created, bucket=bucket_for(now).isoformat())
