"""Response projection shared across API versions; raw logs need an explicit allowlist."""

from datetime import datetime

from app.metrics.calculation import utc
from app.models.entities import Enrichment, Integration, Snapshot


def serialize(model):
    if model is None:
        return None
    values = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        values[column.name] = (
            utc(value).isoformat() if isinstance(value, datetime) else value
        )
    if isinstance(model, Integration):
        values.update(
            latency_target_ms=model.latency_target_ms,
            max_gap_minutes=model.max_gap_minutes,
            evaluation_window_minutes=model.config.evaluation_window_minutes,
            refresh_minutes=model.config.refresh_minutes,
            min_requests=model.config.min_requests,
        )
    if isinstance(model, Enrichment):
        values["audit"] = (model.evidence_payload or {}).get("audit")
    if isinstance(model, Snapshot):
        values["metrics"] = model.evidence["metrics"]
    return values


def serialize_log(model):
    """Project only operator-safe metadata without touching raw payloads/messages."""
    return {
        "tenant_id": model.tenant_id,
        "event_id": model.event_id,
        "integration_id": model.integration_id,
        "occurred_at": utc(model.occurred_at).isoformat(),
        "status_code": model.status_code,
        "latency_ms": model.latency_ms,
        "timed_out": model.timed_out,
        "error_category": model.error_category,
    }
