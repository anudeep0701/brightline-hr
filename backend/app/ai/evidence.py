"""Build an allowlisted, tenant-scoped evidence packet. Never include raw logs."""

from sqlalchemy import or_, select

from app.models.entities import HealthIncident, HealthSnapshot

METRIC_FIELDS = (
    "request_count",
    "success_count",
    "error_count",
    "error_rate",
    "timeout_rate",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "top_error_categories",
)


def build_evidence(session, snapshot):
    previous = session.scalar(
        select(HealthSnapshot)
        .where(
            HealthSnapshot.tenant_id == snapshot.tenant_id,
            HealthSnapshot.integration_id == snapshot.integration_id,
            HealthSnapshot.bucket < snapshot.bucket,
        )
        .order_by(HealthSnapshot.bucket.desc())
        .limit(1)
    )
    incident = session.scalar(
        select(HealthIncident)
        .where(
            HealthIncident.tenant_id == snapshot.tenant_id,
            HealthIncident.integration_id == snapshot.integration_id,
            HealthIncident.opened_at <= snapshot.bucket,
            or_(
                HealthIncident.resolved_at.is_(None),
                HealthIncident.resolved_at >= snapshot.bucket,
            ),
        )
        .order_by(HealthIncident.opened_at.desc())
        .limit(1)
    )
    metrics = snapshot.evidence["metrics"]
    changes = None
    if previous:
        prior = previous.evidence["metrics"]
        changes = dict(
            previous_snapshot_id=previous.id,
            previous_window_end=previous.bucket.isoformat(),
            previous_status=previous.status,
            current_status=snapshot.status,
            # Overlapping windows are comparisons, not independent samples.
            deltas={
                key: metrics[key] - prior[key]
                if metrics.get(key) is not None and prior.get(key) is not None
                else None
                for key in ("request_count", "error_rate", "timeout_rate", "p95_ms")
            },
            previous_error_categories=prior.get("top_error_categories", []),
        )
    baseline = metrics.get("baseline")
    return dict(
        snapshot_id=snapshot.id,
        status=snapshot.status,
        observed_status=snapshot.observed_status,
        reason_code=snapshot.reason_code,
        reason_text=snapshot.reason_text,
        evaluated_at=snapshot.evaluated_at.isoformat(),
        window_start=snapshot.evidence.get("window_start"),
        window_end=snapshot.bucket.isoformat(),
        evidence_sufficient=snapshot.evidence_sufficient,
        health_evidence_confidence=snapshot.confidence,
        metrics={key: metrics.get(key) for key in METRIC_FIELDS},
        baseline={
            key: baseline.get(key)
            for key in (
                "request_count",
                "error_rate",
                "timeout_rate",
                "p95_ms",
                "window_start",
                "window_end",
            )
        }
        if baseline
        else None,
        baseline_used=snapshot.evidence.get("baseline_used", False),
        thresholds=snapshot.evidence.get("thresholds", {}),
        signal_reason_codes=snapshot.evidence.get("signal_reason_codes", []),
        consecutive_bad_windows=snapshot.bad_window_streak,
        consecutive_degraded_windows=snapshot.degraded_window_streak,
        consecutive_healthy_windows=snapshot.healthy_window_streak,
        incident_start_time=incident.opened_at.isoformat() if incident else None,
        changes=changes,
    )


def allowed_categories(evidence):
    allowed = {"unknown"}
    allowed.update(
        x["category"] for x in evidence["metrics"].get("top_error_categories") or []
    )
    if not evidence["evidence_sufficient"]:
        allowed.add("insufficient_evidence")
    if "LATENCY" in evidence["reason_code"] or any(
        "LATENCY" in code for code in evidence.get("signal_reason_codes", [])
    ):
        allowed.add("latency")
    return sorted(allowed)


def changes_text(evidence):
    changes = evidence["changes"]
    if changes is None:
        return "No earlier snapshot is available for comparison."
    values = changes["deltas"]
    parts = [f"Status: {changes['previous_status']} → {changes['current_status']}."]
    for key, label, scale, unit in (
        ("request_count", "Request count", 1, ""),
        ("error_rate", "Error rate", 100, " percentage points"),
        ("timeout_rate", "Timeout rate", 100, " percentage points"),
        ("p95_ms", "p95 latency", 1, " ms"),
    ):
        if values[key] is not None:
            parts.append(f"{label} changed by {values[key] * scale:+.2f}{unit}.")
    return " ".join(parts)
