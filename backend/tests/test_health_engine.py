from datetime import datetime, timedelta, timezone

import pytest
from app.health.service import refresh
from app.models.entities import (
    Incident,
    Integration,
    MetricRollup,
    RequestLog,
    Snapshot,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
AUTH = {"Authorization": "Bearer a"}


def add_window(db, at, *, errors=0, count=100, latency=300, suffix=""):
    for n in range(count):
        db.add(
            RequestLog(
                tenant_id="a",
                integration_id="payroll",
                event_id=f"{int(at.timestamp())}-{suffix}-{n}",
                occurred_at=at - timedelta(seconds=n % 240 + 1),
                status_code=503 if n < errors else 200,
                latency_ms=latency,
                timed_out=False,
                error_category="upstream" if n < errors else "none",
            )
        )
    db.commit()


def snapshots(db):
    return db.scalars(
        select(Snapshot).where(Snapshot.tenant_id == "a").order_by(Snapshot.bucket)
    ).all()


def configure(db, **values):
    policy = db.get(Integration, ("a", "payroll")).config
    for key, value in values.items():
        setattr(policy, key, value)
    db.commit()


def test_single_bad_window_then_recovery_does_not_open_incident(db):
    configure(db, evaluation_window_minutes=5)
    add_window(db, AT, errors=20)
    refresh(db, "a", AT)
    add_window(db, AT + timedelta(minutes=5))
    refresh(db, "a", AT + timedelta(minutes=5))
    add_window(db, AT + timedelta(minutes=10))
    refresh(db, "a", AT + timedelta(minutes=10))
    assert [x.status for x in snapshots(db)] == ["DEGRADED", "DEGRADED", "HEALTHY"]
    assert db.scalar(select(Incident)) is None


def test_sustained_degradation_confirms_then_resolves_and_reopens(db):
    configure(db, evaluation_window_minutes=5)
    for minute in (0, 5, 10):
        at = AT + timedelta(minutes=minute)
        add_window(db, at, errors=2)
        refresh(db, "a", at)
    assert [x.status for x in snapshots(db)] == ["DEGRADED", "DEGRADED", "UNHEALTHY"]
    incident = db.scalar(select(Incident))
    assert incident.opened_at == AT + timedelta(minutes=10)
    for minute in (15, 20):
        at = AT + timedelta(minutes=minute)
        add_window(db, at)
        refresh(db, "a", at)
    assert incident.resolved_at == AT + timedelta(minutes=20)
    for minute in (25, 30):
        at = AT + timedelta(minutes=minute)
        add_window(db, at, errors=50)
        refresh(db, "a", at)
    assert db.scalar(select(func.count()).select_from(Incident)) == 2


def test_unknown_never_resolves_and_recovery_is_not_double_counted(db):
    configure(db, evaluation_window_minutes=5)
    for minute in (0, 5):
        at = AT + timedelta(minutes=minute)
        add_window(db, at, errors=50)
        refresh(db, "a", at)
    incident = db.scalar(select(Incident))
    refresh(db, "a", AT + timedelta(minutes=10))
    assert snapshots(db)[-1].status == "UNKNOWN" and incident.resolved_at is None
    for minute in (15, 20):
        at = AT + timedelta(minutes=minute)
        add_window(db, at)
        refresh(db, "a", at)
    assert snapshots(db)[-2].status == "UNHEALTHY"
    assert snapshots(db)[-1].status == "HEALTHY" and incident.resolved_at is not None
    assert incident.recovery_streak == 2


def test_configurable_window_cadence_and_repeated_refresh(db):
    configure(db, evaluation_window_minutes=30, refresh_minutes=10)
    add_window(db, AT - timedelta(minutes=20), errors=20)
    add_window(db, AT, errors=20)
    refresh(db, "a", AT)
    assert snapshots(db)[0].evidence["metrics"]["request_count"] == 200
    assert refresh(db, "a", AT + timedelta(minutes=5))["created"] == 0
    add_window(db, AT + timedelta(minutes=10), errors=20)
    refresh(db, "a", AT + timedelta(minutes=10))
    assert snapshots(db)[-1].status == "UNHEALTHY"
    assert len(snapshots(db)) == 2
    assert db.scalar(select(func.count()).select_from(MetricRollup)) == 2


def test_skipped_bucket_cannot_confirm_new_incident(db):
    configure(db, evaluation_window_minutes=5)
    for minute in (0, 10):
        at = AT + timedelta(minutes=minute)
        add_window(db, at, errors=20)
        refresh(db, "a", at)
    assert [x.bad_window_streak for x in snapshots(db)] == [1, 1]
    assert db.scalar(select(Incident)) is None


def test_configuration_change_resets_confirmation_and_retains_audit(db):
    add_window(db, AT, errors=20)
    refresh(db, "a", AT)
    configure(db, error_critical=0.1)
    add_window(db, AT + timedelta(minutes=5), errors=20)
    refresh(db, "a", AT + timedelta(minutes=5))
    old, new = snapshots(db)
    assert old.evidence["thresholds"]["error_critical"] == 0.05
    assert new.evidence["thresholds"]["error_critical"] == 0.1
    assert new.bad_window_streak == 1 and new.status == "DEGRADED"
    assert db.scalar(select(Incident)) is None


def test_baseline_uses_disjoint_history_and_detects_relative_latency(db):
    configure(db, latency_target_ms=2000)
    add_window(db, AT - timedelta(minutes=30), latency=200)
    add_window(db, AT, latency=650)
    refresh(db, "a", AT)
    snapshot = snapshots(db)[0]
    assert snapshot.evidence["baseline_used"]
    assert snapshot.observed_status == "UNHEALTHY"
    assert snapshot.evidence["metrics"]["baseline"]["request_count"] == 100
    assert snapshot.evidence["metrics"]["request_count"] == 100
    assert "LATENCY_BASELINE_CRITICAL" in snapshot.evidence["signal_reason_codes"]


def test_api_policy_updates_are_validated_authorized_and_tenant_scoped(client, db):
    url = "/api/v1/integrations/payroll/config"
    policy = client.get(url, headers=AUTH).json()
    assert (
        policy["evaluation_window_minutes"] == 15
        and policy["unhealthy_bad_windows"] == 2
    )
    response = client.put(
        url,
        headers=AUTH,
        json=dict(policy, error_warning=0.03, error_critical=0.1, refresh_minutes=15),
    )
    assert response.status_code == 200
    assert db.get(Integration, ("a", "payroll")).config.error_warning == 0.03
    assert db.get(Integration, ("b", "payroll")).config.error_warning == 0.01
    assert (
        client.put(url, headers=AUTH, json=dict(policy, error_warning=0.2)).status_code
        == 422
    )
    assert (
        client.put(
            url, headers={"Authorization": "Bearer reader"}, json=policy
        ).status_code
        == 403
    )


def test_snapshot_api_exposes_every_health_result_field(client, db):
    add_window(db, AT, errors=20)
    refresh(db, "a", AT)
    response = client.get("/api/v1/integrations/payroll", headers=AUTH)
    assert response.status_code == 200
    result = response.json()["snapshot"]
    assert result["status"] == "DEGRADED" and result["observed_status"] == "UNHEALTHY"
    assert result["confidence"] == 1 and result["evidence_sufficient"]
    assert (
        result["reason_code"] == "UNHEALTHY_CONFIRMATION_PENDING"
        and result["reason_text"]
    )
    assert result["evaluated_at"].endswith("Z")
    assert {
        "success_count",
        "timeout_rate",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "top_error_categories",
    } <= result["metrics"].keys()


def test_backdated_refresh_does_not_rewind_state(db):
    add_window(db, AT)
    refresh(db, "a", AT)
    assert refresh(db, "a", AT - timedelta(minutes=5))["created"] == 0
    assert len(snapshots(db)) == 1


def test_health_does_not_invoke_ai_even_when_ai_raises(db, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("AI must never determine health")

    monkeypatch.setattr("app.ai.enrichment.OpenAI", forbidden)
    for minute in (0, 5):
        at = AT + timedelta(minutes=minute)
        add_window(db, at, errors=50)
        refresh(db, "a", at)
    assert (
        snapshots(db)[-1].status == "UNHEALTHY"
        and db.scalar(select(Incident)) is not None
    )


def test_database_rejects_incoherent_policy(db):
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.get(Integration, ("a", "payroll")).config.error_critical = 0.001
            db.flush()


def test_persisted_defaults_match_the_single_policy_definition(db):
    from app.health.config import DEFAULT_POLICY, HealthPolicy
    from app.health.policy import fingerprint

    stored = HealthPolicy.model_validate(db.get(Integration, ("a", "payroll")).config)
    assert stored == DEFAULT_POLICY
    assert fingerprint(stored) == fingerprint(DEFAULT_POLICY)


def test_refresh_fifteen_minute_cadence_and_configured_confirmation_count(db):
    configure(
        db,
        refresh_minutes=15,
        evaluation_window_minutes=15,
        unhealthy_bad_windows=3,
        sustained_degraded_windows=3,
    )
    for minute in (0, 15, 30):
        at = AT + timedelta(minutes=minute)
        add_window(db, at, errors=20)
        refresh(db, "a", at)
        assert refresh(db, "a", at + timedelta(minutes=5))["created"] == 0
    assert [x.status for x in snapshots(db)] == ["DEGRADED", "DEGRADED", "UNHEALTHY"]
    assert db.scalar(select(Incident)).opened_at == AT + timedelta(minutes=30)
