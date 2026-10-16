"""Public endpoint contracts and boundary/security behavior using offline storage."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.config import get_settings
from app.db.session import get_db
from app.health.service import bucket_for, refresh
from app.main import app
from app.models.entities import Incident, Integration, Snapshot
from app.schemas.enrichment import GroundedPlan
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

A = {"Authorization": "Bearer a"}
B = {"Authorization": "Bearer b"}
READER = {"Authorization": "Bearer reader"}


def test_public_probes_and_storage_failure(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    previous = app.dependency_overrides[get_db]

    def unavailable():
        raise OperationalError("private-db-url", {}, Exception("private-db-password"))

    app.dependency_overrides[get_db] = unavailable
    try:
        assert client.get("/healthz").status_code == 200
        result = client.get("/readyz")
        assert result.status_code == 503
        assert result.json()["code"] == "storage_unavailable"
        assert "private-db" not in result.text
        assert client.get("/api/integrations", headers=A).status_code == 503
    finally:
        app.dependency_overrides[get_db] = previous


def test_readiness_detects_missing_migration_column(client, db):
    db.execute(text("ALTER TABLE enrichments DROP COLUMN report"))
    db.commit()
    assert client.get("/readyz").status_code == 503
    assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/health-summary",
        "/api/integrations",
        "/api/integrations/payroll",
        "/api/integrations/payroll/metrics",
        "/api/integrations/payroll/incidents",
    ],
)
def test_reads_require_auth_and_support_reader_role(client, path):
    result = client.get(path)
    assert result.status_code == 401 and result.json()["code"] == "unauthorized"
    assert client.get(path, headers=READER).status_code == 200
    assert client.get(path, headers=A, params={"tenant_id": "a"}).status_code == 200
    result = client.get(path, headers=A, params={"tenant_id": "b"})
    assert result.status_code == 403 and result.json()["code"] == "tenant_forbidden"


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/ingest", {"events": [{}]}),
        ("/api/evaluate", None),
        ("/api/integrations/payroll/explain", None),
    ],
)
def test_mutations_require_operator_and_match_tenant(client, path, body):
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers=READER).status_code == 403
    result = client.post(path, json=body, headers=A, params={"tenant_id": "b"})
    assert result.status_code == 403 and result.json()["code"] == "tenant_forbidden"


def test_list_filters_summary_counts_and_pagination(client, db):
    db.add(
        Integration(
            tenant_id="a",
            id="notify",
            name="Slack",
            category="Notifications",
            owner="Ops",
        )
    )
    db.commit()
    result = client.get("/api/integrations", headers=A).json()
    assert result["total"] == 2
    assert [x["integration"]["id"] for x in result["items"]] == ["notify", "payroll"]
    assert all(x["snapshot"] is None and x["stale"] for x in result["items"])
    page = client.get("/api/integrations?limit=1&offset=1", headers=A).json()
    assert page["total"] == 2 and page["items"][0]["integration"]["id"] == "payroll"
    assert client.get("/api/integrations?offset=100", headers=A).json()["items"] == []
    assert (
        client.get("/api/integrations?health_status=HEALTHY", headers=A).json()["total"]
        == 0
    )
    filtered = client.get(
        "/api/integrations?integration_type=payroll&health_status=UNKNOWN", headers=A
    ).json()
    assert (
        filtered["total"] == 1
        and filtered["items"][0]["integration"]["id"] == "payroll"
    )
    summary = client.get("/api/health-summary", headers=A).json()
    assert (
        summary["total_integrations"] == 2 and summary["status_counts"]["UNKNOWN"] == 2
    )
    assert sum(summary["status_counts"].values()) == 2
    assert summary["stale_integrations"] == 2 and summary["latest_evaluated_at"] is None
    assert (
        client.get("/api/health-summary?integration_type=payroll", headers=A).json()[
            "total_integrations"
        ]
        == 1
    )
    assert client.get("/api/integrations", headers=B).json()["total"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"health_status": "broken-secret"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"start_time": "2026-10-15T12:00:00"},
        {"end_time": "private-bad-date"},
        {"start_time": "2026-10-15T13:00:00Z", "end_time": "2026-10-15T12:00:00Z"},
        {"start_time": "2026-10-15T12:00:00Z", "end_time": "2026-10-15T12:00:00Z"},
        {"unexpected-secret": "private-value"},
    ],
)
def test_invalid_filters_are_safely_rejected(client, params):
    result = client.get("/api/integrations", headers=A, params=params)
    assert result.status_code == 422 and result.json()["code"] == "invalid_request"
    assert "secret" not in result.text and "private-" not in result.text


def test_latest_in_range_and_metric_history_half_open_bounds(client, db):
    start = bucket_for(datetime.now(timezone.utc)) - timedelta(hours=1)
    refresh(db, "a", start)
    refresh(db, "a", start + timedelta(minutes=5))
    refresh(db, "b", start + timedelta(minutes=5))
    second = db.scalar(
        select(Snapshot).where(
            Snapshot.tenant_id == "a", Snapshot.bucket == start + timedelta(minutes=5)
        )
    )
    params = {
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(minutes=5)).isoformat(),
    }
    items = client.get("/api/integrations", headers=A, params=params).json()["items"]
    assert (
        datetime.fromisoformat(items[0]["snapshot"]["bucket"].replace("Z", "+00:00"))
        == start
    )
    history = client.get(
        "/api/integrations/payroll/metrics", headers=A, params=params
    ).json()
    assert (
        history["total"] == 1 and history["items"][0]["metrics"]["request_count"] == 0
    )
    assert (
        datetime.fromisoformat(history["items"][0]["window_end"].replace("Z", "+00:00"))
        == start
    )
    page = client.get(
        "/api/integrations/payroll/metrics?limit=1&offset=1", headers=A
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    summary = client.get("/api/health-summary", headers=A, params=params).json()
    assert summary["status_counts"]["UNKNOWN"] == 1
    detail = client.get("/api/integrations/payroll", headers=A, params=params).json()
    assert detail["snapshot"]["id"] == second.id and len(detail["history"]) == 1
    # Offset ISO timestamps are converted to UTC before serialization.
    params["start_time"] = start.astimezone(timezone(timedelta(hours=-7))).isoformat()
    assert (
        client.get(
            "/api/integrations/payroll/metrics", headers=A, params=params
        ).json()["total"]
        == 1
    )


def test_incidents_overlap_activity_and_are_tenant_scoped(client, db):
    start = bucket_for(datetime.now(timezone.utc)) - timedelta(hours=1)
    refresh(db, "a", start)
    refresh(db, "b", start)
    ids = {x.tenant_id: x.id for x in db.scalars(select(Snapshot))}
    for tenant, opened, resolved in (
        ("a", start - timedelta(minutes=30), None),
        ("a", start - timedelta(minutes=20), start),
        ("a", start - timedelta(minutes=10), start + timedelta(minutes=1)),
        ("b", start - timedelta(minutes=10), None),
    ):
        db.add(
            Incident(
                tenant_id=tenant,
                integration_id="payroll",
                opening_snapshot_id=ids[tenant],
                last_snapshot_id=ids[tenant],
                opened_at=opened,
                resolved_at=resolved,
            )
        )
    db.commit()
    params = {
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(minutes=5)).isoformat(),
    }
    result = client.get(
        "/api/integrations/payroll/incidents", headers=A, params=params
    ).json()
    assert result["total"] == 2 and all(x["tenant_id"] == "a" for x in result["items"])
    params["state"] = "OPEN"
    assert (
        client.get(
            "/api/integrations/payroll/incidents", headers=A, params=params
        ).json()["total"]
        == 1
    )
    params["state"] = "RESOLVED"
    assert (
        client.get(
            "/api/integrations/payroll/incidents", headers=A, params=params
        ).json()["total"]
        == 1
    )
    assert client.get("/api/health-summary", headers=A).json()["open_incidents"] == 1


@pytest.mark.parametrize("suffix", ["", "/metrics", "/incidents", "/explain"])
def test_missing_integration_has_typed_not_found(client, suffix):
    request = client.post if suffix == "/explain" else client.get
    result = request("/api/integrations/missing" + suffix, headers=A)
    assert (
        result.status_code == 404 and result.json()["code"] == "integration_not_found"
    )


def test_ingest_evaluate_and_explain_work_keyless(client, monkeypatch):
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI", lambda **kw: pytest.fail("Must stay offline")
    )
    result = client.post(
        "/api/ingest",
        headers=A,
        json={
            "events": [
                dict(
                    request_id="api-event",
                    integration_id="payroll",
                    tenant_id="a",
                    http_status=503,
                    timestamp=(
                        datetime.now(timezone.utc) - timedelta(seconds=30)
                    ).isoformat(),
                    latency_ms=80,
                ),
                {"invalid": "private-message"},
            ]
        },
    )
    assert result.status_code == 200
    assert (result.json()["accepted"], result.json()["rejected"]) == (1, 1)
    duplicate = client.post(
        "/api/ingest",
        headers=A,
        json={
            "events": [
                dict(
                    request_id="api-event",
                    integration_id="payroll",
                    http_status=503,
                    timestamp=(
                        datetime.now(timezone.utc) - timedelta(seconds=30)
                    ).isoformat(),
                    latency_ms=80,
                ),
            ]
        },
    )
    assert duplicate.json()["duplicates"] == 1
    assert (
        client.post("/api/integrations/payroll/explain", headers=A).status_code == 409
    )
    assert client.post("/api/evaluate", headers=A).json()["created"] == 1
    assert client.post("/api/evaluate", headers=A).json()["created"] == 0
    detail = client.get("/api/integrations/payroll", headers=A).json()
    result = client.post("/api/integrations/payroll/explain", headers=A)
    assert result.status_code == 200 and result.json()["source"] == "deterministic"
    assert result.json()["explanation"] == detail["snapshot"]["reason_text"]
    assert result.json()["report"]["summary"] == detail["snapshot"]["reason_text"]
    assert (
        client.get("/api/integrations/payroll/metrics", headers=B).json()["total"] == 0
    )
    assert "raw_event" not in str(detail["logs"])


def test_successful_ai_response_preserves_nullable_fields(client, monkeypatch):
    # Regression: dropping None during serialization omitted a required fallback_code.
    monkeypatch.setattr(get_settings(), "openai_api_key", "fake-test-key")
    report = GroundedPlan(
        summary_fact_ids=["decision"],
        change_fact_ids=["changes"],
        likely_issue_category="unknown",
        check_ids=["freshness"],
        confidence="low",
    )
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kw: nullcontext(
            SimpleNamespace(
                responses=SimpleNamespace(
                    parse=lambda **kw: SimpleNamespace(output_parsed=report)
                ),
            )
        ),
    )
    client.post("/api/evaluate", headers=A)
    result = client.post("/api/integrations/payroll/explain", headers=A)
    assert result.status_code == 200 and result.json()["fallback_code"] is None
    assert result.json()["source"].startswith("openai:")
    assert "fake-test-key" not in result.text


def test_cors_preflight_and_error_responses(client):
    origin = "http://localhost:3000"
    result = client.options(
        "/api/ingest",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert (
        result.status_code == 200
        and result.headers["access-control-allow-origin"] == origin
    )
    assert "PUT" in result.headers["access-control-allow-methods"]
    denied = client.options(
        "/api/ingest",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert (
        denied.status_code == 400
        and "access-control-allow-origin" not in denied.headers
    )
    result = client.get("/api/integrations", headers={"Origin": origin})
    assert (
        result.status_code == 401
        and result.headers["access-control-allow-origin"] == origin
    )


def test_openapi_describes_all_contracts(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    expected = {
        "/healthz": "get",
        "/readyz": "get",
        "/api/health-summary": "get",
        "/api/integrations": "get",
        "/api/integrations/{integration_id}": "get",
        "/api/integrations/{integration_id}/metrics": "get",
        "/api/integrations/{integration_id}/incidents": "get",
        "/api/ingest": "post",
        "/api/evaluate": "post",
        "/api/integrations/{integration_id}/explain": "post",
    }
    for path, method in expected.items():
        assert paths[path][method]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert paths[path][method]["summary"]
    assert paths["/api/ingest"]["post"]["security"]
    assert "security" not in paths["/healthz"]["get"]
    assert paths["/api/integrations"]["get"]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/ErrorOut")
    assert client.get("/docs").status_code == 200


def test_unexpected_error_returns_safe_typed_response(client, caplog):
    from fastapi.testclient import TestClient

    previous = app.dependency_overrides[get_db]

    def failure():
        raise RuntimeError("private-unexpected-error")

    app.dependency_overrides[get_db] = failure
    try:
        with TestClient(app, raise_server_exceptions=False) as safe_client:
            result = safe_client.get("/readyz")
        assert result.status_code == 500
        assert result.json() == {
            "detail": "Internal server error",
            "code": "internal_error",
        }
        assert "private-unexpected-error" not in caplog.text
    finally:
        app.dependency_overrides[get_db] = previous


def test_status_filter_applies_to_latest_decision_not_any_historical_match(client, db):
    from app.models.entities import RequestLog

    at = bucket_for(datetime.now(timezone.utc)) - timedelta(minutes=5)
    for index in range(30):
        db.add(
            RequestLog(
                tenant_id="a",
                integration_id="payroll",
                event_id=f"failed-{index}",
                occurred_at=at - timedelta(seconds=30),
                status_code=503,
                latency_ms=100,
                timed_out=False,
                error_category="upstream",
            )
        )
    db.commit()
    refresh(db, "a", at)
    refresh(db, "a", at + timedelta(minutes=5))
    assert (
        client.get("/api/integrations?health_status=DEGRADED", headers=A).json()[
            "total"
        ]
        == 0
    )
    result = client.get("/api/integrations?health_status=UNHEALTHY", headers=A).json()
    assert (
        result["total"] == 1 and result["items"][0]["snapshot"]["status"] == "UNHEALTHY"
    )
    summary = client.get(
        "/api/health-summary?health_status=UNHEALTHY", headers=A
    ).json()
    assert summary["status_counts"]["UNHEALTHY"] == 1 and summary["open_incidents"] == 1
    historic = client.get(
        "/api/integrations",
        headers=A,
        params={
            "health_status": "DEGRADED",
            "end_time": (at + timedelta(minutes=5)).isoformat(),
        },
    ).json()
    assert (
        historic["total"] == 1
        and historic["items"][0]["snapshot"]["status"] == "DEGRADED"
    )


def test_workspace_options_are_token_scoped_even_in_demo(client, monkeypatch):
    result = client.get("/api/workspace", headers=A)
    assert result.status_code == 200
    assert result.json()["tenants"] == [{"id": "a", "name": "a"}]
    assert (
        result.json()["role"] == "operator"
        and result.json()["can_switch_tenants"] is False
    )
    monkeypatch.setattr(get_settings(), "app_env", "demo")
    assert client.get("/api/workspace", headers=A).json()["tenants"] == [
        {"id": "a", "name": "a"}
    ]
    assert client.get("/api/workspace?tenant_id=b", headers=A).status_code == 403
    demo = client.get("/api/workspace?tenant_id=b")
    assert demo.status_code == 200 and demo.json()["tenant_id"] == "b"
    assert demo.json()["can_switch_tenants"] is True
    assert {x["id"] for x in demo.json()["tenants"]} == {"a", "b"}
    assert client.get("/api/integrations?tenant_id=b").json()["tenant_id"] == "b"


def test_previous_snapshot_and_cached_summary_are_read_only(client, db, monkeypatch):
    at = bucket_for(datetime.now(timezone.utc)) - timedelta(minutes=5)
    refresh(db, "a", at)
    refresh(db, "a", at + timedelta(minutes=5))
    row = client.get("/api/v1/dashboard", headers=A).json()["integrations"][0]
    assert row["previous_snapshot"]["id"] != row["snapshot"]["id"]
    assert row["previous_snapshot"]["bucket"] < row["snapshot"]["bucket"]
    assert (
        client.get("/api/integrations/payroll", headers=A).json()["enrichment"] is None
    )
    generated = client.post("/api/integrations/payroll/explain", headers=A).json()
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI", lambda **kw: pytest.fail("GET must never invoke AI")
    )
    detail = client.get("/api/integrations/payroll", headers=READER).json()
    assert detail["enrichment"]["id"] == generated["id"]
    assert detail["enrichment"]["snapshot_id"] == detail["snapshot"]["id"]
    assert (
        client.get("/api/integrations/payroll", headers=B).json()["enrichment"] is None
    )


def test_postgres_demo_identity_cannot_select_another_tenant(monkeypatch):
    from app.api.auth import principal
    from starlette.requests import Request

    monkeypatch.setattr(get_settings(), "app_env", "demo")
    request = Request({"type": "http", "query_string": b"tenant_id=b", "headers": []})
    # The identity branch does not query storage; model a hosted dialect without using a real database.
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as rejected:
        principal(request, credentials=None, db=db)
    assert rejected.value.status_code == 401
    assert rejected.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/health-summary"),
        ("post", "/api/evaluate"),
        ("post", "/api/integrations/payroll/brief"),
    ],
)
def test_demo_flag_cannot_bypass_workspace_auth_on_postgresql(
    client, db, monkeypatch, method, path
):
    monkeypatch.setattr(get_settings(), "app_env", "demo")
    # Only the authentication dialect check is exercised; no PG SQL is executed.
    monkeypatch.setattr(db.get_bind().dialect, "name", "postgresql")
    result = getattr(client, method)(path)
    assert result.status_code == 401
    assert result.json()["code"] == "unauthorized"
