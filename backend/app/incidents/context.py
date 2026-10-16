"""Read-only recovery evidence derived from immutable, tenant-owned snapshots."""

from datetime import timedelta

from sqlalchemy import select

from app.metrics.calculation import utc
from app.models.entities import Snapshot


def incident_context(session, incident):
    def owned(snapshot_id):
        return session.scalar(
            select(Snapshot).where(
                Snapshot.id == snapshot_id,
                Snapshot.tenant_id == incident.tenant_id,
                Snapshot.integration_id == incident.integration_id,
            )
        )

    opening = owned(incident.opening_snapshot_id)
    last = owned(incident.last_snapshot_id)
    policy = (last or opening).evidence.get("thresholds", {}) if last or opening else {}
    required = policy.get("healthy_recovery_windows")
    began = None
    if last and last.healthy_window_streak and policy.get("refresh_minutes"):
        start = utc(last.bucket) - timedelta(
            minutes=policy["refresh_minutes"] * (last.healthy_window_streak - 1)
        )
        first = session.scalar(
            select(Snapshot).where(
                Snapshot.tenant_id == incident.tenant_id,
                Snapshot.integration_id == incident.integration_id,
                Snapshot.bucket == start,
                Snapshot.bucket >= incident.opened_at,
            )
        )
        if first and first.evidence.get("recovery_thresholds_met"):
            began = utc(first.bucket).isoformat()
    condition = (
        f"{required} adjacent windows with sufficient fresh traffic (minimum {policy.get('min_requests', 'unknown')} requests), error rate ≤ {policy['error_recovery']:.2%}, "
        f"timeout rate ≤ {policy['timeout_recovery']:.2%}, P95 ≤ {policy['latency_target_ms'] * policy['latency_recovery_multiplier']:g} ms, "
        "and the stored healthy-baseline recovery margin when applicable. Borderline or insufficient evidence resets the recovery streak."
        if all(
            key in policy
            for key in (
                "healthy_recovery_windows",
                "error_recovery",
                "timeout_recovery",
                "latency_target_ms",
                "latency_recovery_multiplier",
            )
        )
        else "Historical recovery policy is unavailable; inspect the original snapshot evidence."
    )
    if last and last.evidence.get("baseline_used"):
        baseline = last.evidence.get("metrics", {}).get("baseline", {})
        if baseline.get("p95_ms") is not None and all(
            key in policy
            for key in ("baseline_min_delta_ms", "latency_recovery_multiplier")
        ):
            condition += f" Baseline margin: P95 delta < {policy['baseline_min_delta_ms']:g} ms or P95 ≤ {baseline['p95_ms'] * policy['latency_recovery_multiplier']:g} ms."
    return dict(
        id=incident.id,
        opened_at=utc(incident.opened_at).isoformat(),
        opening_reason_code=opening.reason_code if opening else None,
        opening_reason_text=opening.reason_text if opening else None,
        recovery_began_at=began,
        resolved_at=utc(incident.resolved_at).isoformat()
        if incident.resolved_at
        else None,
        recovery_condition=condition,
        healthy_windows_required=required,
        healthy_windows_observed=last.healthy_window_streak if last else 0,
        opening_snapshot_id=incident.opening_snapshot_id,
        resolution_snapshot_id=last.id if last and incident.resolved_at else None,
    )
