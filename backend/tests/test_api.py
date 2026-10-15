from datetime import datetime, timedelta, timezone

import pytest
from app.ai.enrichment import explain
from app.config import Settings
from app.health.service import bucket_for, refresh
from app.models.entities import Enrichment, Incident, RequestLog, Snapshot
from sqlalchemy import func, select

A = {"Authorization": "Bearer a"}
B = {"Authorization": "Bearer b"}


def payload(event="event-1", integration="payroll"):
    return {
        "logs": [
            dict(
                event_id=event,
                integration_id=integration,
                occurred_at=(
                    datetime.now(timezone.utc) - timedelta(minutes=1)
                ).isoformat(),
                status_code=503,
                latency_ms=100,
            )
        ]
    }


def test_auth_and_role(client):
    assert client.get("/api/v1/dashboard").status_code == 401
    assert (
        client.get(
            "/api/v1/dashboard", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/refresh", headers={"Authorization": "Bearer reader"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/dashboard", headers={"Authorization": "Bearer reader"}
        ).status_code
        == 200
    )


def test_idempotent_and_isolated_ingestion(client, db):
    p = payload()
    assert client.post("/api/v1/logs", headers=A, json=p).json()["inserted"] == 1
    assert client.post("/api/v1/logs", headers=A, json=p).json()["duplicates"] == 1
    assert client.get("/api/v1/integrations/payroll", headers=B).json()["logs"] == []
    assert client.post("/api/v1/logs", headers=B, json=p).json()["inserted"] == 1
    assert db.scalar(select(func.count()).select_from(RequestLog)) == 2


def test_atomic_validation(client, db):
    p = payload()
    p["logs"] += payload("event-2", "foreign")["logs"]
    assert client.post("/api/v1/logs", headers=A, json=p).status_code == 422
    assert db.scalar(select(func.count()).select_from(RequestLog)) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("latency_ms", -1),
        ("status_code", 999),
        ("occurred_at", "2026-10-15T12:00:00"),
        ("occurred_at", "2099-01-01T00:00:00Z"),
        ("error_category", "raw-secret"),
    ],
)
def test_rejected_inputs(client, field, value):
    p = payload()
    p["logs"][0][field] = value
    assert client.post("/api/v1/logs", headers=A, json=p).status_code == 422


def test_unknown_detail_is_tenant_scoped(client):
    assert client.get("/api/v1/integrations/foreign", headers=A).status_code == 404


def test_cron_fails_closed(client):
    assert client.get("/api/cron/refresh").status_code == 401
    assert (
        client.get(
            "/api/cron/refresh", headers={"Authorization": "Bearer test-cron-secret"}
        ).status_code
        == 200
    )


def add_window(db, at, failed):
    for n in range(30):
        db.add(
            RequestLog(
                tenant_id="a",
                integration_id="payroll",
                event_id=f"{at.isoformat()}-{n}",
                occurred_at=at - timedelta(seconds=n + 1),
                status_code=503 if failed else 200,
                latency_ms=100,
                timed_out=False,
                error_category="upstream" if failed else "none",
            )
        )
    db.commit()


def test_incident_recovery_and_duplicate_refresh(db):
    at = bucket_for(datetime.now(timezone.utc)) - timedelta(hours=1)
    add_window(db, at, True)
    assert refresh(db, "a", at)["created"] == 1
    assert refresh(db, "a", at)["created"] == 0
    incident = db.scalar(select(Incident))
    assert incident and incident.resolved_at is None
    # Old failures fall out of the window; skipped evaluations do not count as consecutive recovery.
    add_window(db, at + timedelta(minutes=20), False)
    refresh(db, "a", at + timedelta(minutes=20))
    assert incident.recovery_streak == 1 and incident.resolved_at is None
    add_window(db, at + timedelta(minutes=25), False)
    refresh(db, "a", at + timedelta(minutes=25))
    assert incident.resolved_at is not None
    add_window(db, at + timedelta(minutes=30), True)
    refresh(db, "a", at + timedelta(minutes=30))
    assert db.scalar(select(func.count()).select_from(Incident)) == 2


def test_unknown_does_not_resolve_incident(db):
    at = bucket_for(datetime.now(timezone.utc)) - timedelta(hours=2)
    add_window(db, at, True)
    refresh(db, "a", at)
    refresh(db, "a", at + timedelta(hours=1))
    incident = db.scalar(select(Incident))
    assert incident.resolved_at is None and incident.recovery_streak == 0


def test_ai_disabled_and_failure_never_mutates_health(db, monkeypatch):
    at = bucket_for(datetime.now(timezone.utc))
    refresh(db, "a", at)
    snapshot = db.scalar(select(Snapshot))
    before = snapshot.evidence.copy()
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    result = explain(db, snapshot, Settings(openai_api_key="fake-test-key"))
    assert result.source == "deterministic"
    assert snapshot.evidence == before and snapshot.status == "unknown"
    assert explain(db, snapshot, Settings()).id == result.id
    assert db.scalar(select(func.count()).select_from(Enrichment)) == 1


def test_production_configuration_fails_closed():
    with pytest.raises(ValueError):
        Settings(app_env="production", database_url="sqlite://")


def test_ai_absent_does_not_construct_client(db, monkeypatch):
    at = bucket_for(datetime.now(timezone.utc))
    refresh(db, "a", at)
    snapshot = db.scalar(select(Snapshot))

    def forbidden(**kwargs):
        raise AssertionError("Client must not be constructed without a key")

    monkeypatch.setattr("app.ai.enrichment.OpenAI", forbidden)
    assert explain(db, snapshot, Settings()).source == "deterministic"


@pytest.mark.parametrize("valid", [True, False])
def test_ai_structured_success_and_refusal(db, monkeypatch, valid):
    from types import SimpleNamespace

    from app.schemas.contracts import ExplanationText

    at = bucket_for(datetime.now(timezone.utc))
    refresh(db, "a", at)
    snapshot = db.scalar(select(Snapshot))
    original = snapshot.status

    def parse(**kwargs):
        assert kwargs["store"] is False
        assert "tenant_id" not in kwargs["input"]
        assert snapshot.id in kwargs["input"]
        return SimpleNamespace(
            output_parsed=ExplanationText(
                explanation="No fresh telemetry; check the log exporter."
            )
            if valid
            else None
        )

    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(parse=parse)),
    )
    result = explain(db, snapshot, Settings(openai_api_key="fake-test-key"))
    assert result.source == ("openai:gpt-4.1-mini" if valid else "deterministic")
    assert snapshot.status == original


def test_explanation_endpoint_requires_operator_and_isolated_snapshot(client):
    assert (
        client.post("/api/v1/integrations/payroll/explanation", headers=A).status_code
        == 409
    )
    client.post("/api/v1/refresh", headers=A)
    result = client.post("/api/v1/integrations/payroll/explanation", headers=A)
    assert result.status_code == 200 and result.json()["source"] == "deterministic"
    assert (
        client.post("/api/v1/integrations/payroll/explanation", headers=B).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/integrations/payroll/explanation",
            headers={"Authorization": "Bearer reader"},
        ).status_code
        == 403
    )


def test_late_arrival_does_not_rewrite_saved_evidence(db):
    at = bucket_for(datetime.now(timezone.utc))
    refresh(db, "a", at)
    first = db.scalar(select(Snapshot))
    first_evidence = first.evidence.copy()
    add_window(db, at, True)
    assert refresh(db, "a", at)["created"] == 0
    assert first.status == "unknown" and first.evidence == first_evidence
    refresh(db, "a", at + timedelta(minutes=5))
    latest = db.scalar(select(Snapshot).order_by(Snapshot.bucket.desc()))
    assert latest.status == "unhealthy"
    assert latest.evidence["metrics"]["request_count"] == 30
