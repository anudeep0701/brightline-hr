"""Public assessment sessions never become general workspace/exporter credentials."""

import hashlib
import time

import pytest
from app.api.demo import COOKIE_NAME, SESSION_SECONDS
from app.config import Settings, get_settings
from app.ingestion.credentials import issue_key
from app.main import app
from app.models.entities import AccessToken, IngestionAPIKey, Integration, Snapshot
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

HEADERS = {"X-Demo-Request": "1", "Origin": "https://testserver"}


@pytest.fixture
def demo(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_tenant_slug", "a")
    monkeypatch.setattr(
        settings, "demo_session_secret", "offline-demo-test-signing-only-32-characters"
    )
    client.base_url = "https://testserver"
    client.headers.update(HEADERS)
    return client


def connect(client):
    result = client.post("/api/demo/session")
    assert result.status_code == 200, result.text
    return result


def test_demo_is_disabled_by_default_and_real_bearer_access_remains(client):
    assert client.get("/api/demo/session").json() == {"demo_mode": False}
    assert client.post("/api/demo/session").status_code == 404
    assert client.get("/api/workspace").status_code == 401
    assert (
        client.get("/api/workspace", headers={"Authorization": "Bearer a"}).status_code
        == 200
    )


def test_session_is_httponly_secure_bounded_and_exposes_no_workspace_token(demo, db):
    result = connect(demo)
    assert set(result.json()) == {"demo_mode", "tenant_id", "tenant_name", "expires_at"}
    assert result.json()["tenant_id"] == "a"
    assert 3595 <= result.json()["expires_at"] - int(time.time()) <= SESSION_SECONDS
    cookie = result.headers["set-cookie"].lower()
    for flag in ["httponly", "secure", "samesite=lax", "path=/", "max-age=3600"]:
        assert flag in cookie
    assert "domain=" not in cookie
    assert result.headers["cache-control"] == "no-store"
    assert get_settings().demo_session_secret not in result.text
    assert db.scalar(select(func.count()).select_from(AccessToken)) == 3
    assert db.scalar(select(func.count()).select_from(IngestionAPIKey)) == 0
    assert "token" not in result.json()


def test_cookie_reuses_session_across_workspace_requests(demo):
    connect(demo)
    for _ in range(2):
        result = demo.get("/api/workspace")
        assert result.status_code == 200
        assert result.json()["tenant_id"] == "a"
        assert result.json()["can_switch_tenants"] is False
        assert result.json()["tenants"] == [{"id": "a", "name": "a"}]
    assert demo.get("/api/v1/dashboard").status_code == 200


def test_cookie_works_after_client_recreation_and_with_production_auth_rules(
    demo, monkeypatch
):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    connect(demo)
    with TestClient(app, base_url="https://testserver", cookies=demo.cookies) as fresh:
        result = fresh.get("/api/workspace")
        assert result.status_code == 200
        assert result.json()["mode"] == "production"
        assert result.json()["can_switch_tenants"] is False


def test_ingestion_credentials_still_work_independently_of_demo_cookie(demo, db):
    connect(demo)
    _, key = issue_key(db, "b", "Offline test exporter")
    from datetime import datetime, timezone

    event = dict(
        timestamp=datetime.now(timezone.utc).isoformat(),
        request_id="export-test",
        integration_id="payroll",
        http_status=200,
        latency_ms=100,
    )
    response = demo.post(
        "/api/ingest",
        headers={"Authorization": "Bearer " + key},
        json={"events": [event]},
    )
    assert response.status_code == 200 and response.json()["accepted"] == 1


def test_signing_secret_rotation_invalidates_sessions(demo, monkeypatch):
    connect(demo)
    monkeypatch.setattr(
        get_settings(), "demo_session_secret", "different-offline-test-signing-secret"
    )
    assert demo.get("/api/workspace").status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/workspace",
        "/api/v1/dashboard",
        "/api/integrations",
        "/api/data-sources",
        "/api/health-summary",
    ],
)
def test_query_cannot_select_another_tenant(demo, path):
    connect(demo)
    assert demo.get(path + "?tenant_id=b").status_code == 403


@pytest.mark.parametrize(
    "path", ["/api/demo/session?tenant_id=b", "/api/demo/session?tenant_id=a"]
)
def test_session_issuance_ignores_browser_tenant_selection(demo, path):
    assert demo.post(path, json={"tenant_id": "b"}).json()["tenant_id"] == "a"


def test_ai_and_evaluate_remain_scoped_to_configured_tenant(demo, db):
    db.add(
        Integration(
            tenant_id="b",
            id="private-b",
            name="Private B",
            category="Payroll",
            owner="Ops",
        )
    )
    db.commit()
    connect(demo)
    assert demo.post("/api/evaluate?tenant_id=b").status_code == 403
    assert demo.post("/api/evaluate").status_code == 200
    assert {s.tenant_id for s in db.scalars(select(Snapshot))} == {"a"}
    for action in ["brief", "explain", "investigate"]:
        payload = {"topic": "error_driver"} if action == "investigate" else None
        path = "/api/integrations/payroll/" + action
        response = demo.post(path, json=payload)
        assert response.status_code == 200 and response.json()["audit"]["fallback_used"]
        assert demo.post(path + "?tenant_id=b", json=payload).status_code == 403
        assert (
            demo.post("/api/integrations/private-b/" + action, json=payload).status_code
            == 404
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/ingest",
        "/api/v1/logs",
        "/api/v1/request-events",
        "/api/imports/preview?format=json",
        "/api/imports/commit?format=json",
    ],
)
def test_demo_cannot_ingest_or_import_telemetry(demo, path):
    connect(demo)
    assert demo.post(path, json={"events": []}).status_code in {401, 403}


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin",
        "/api/admin/tenants",
        "/api/credentials",
        "/api/ingestion-keys",
        "/api/ingestion-keys/key/revoke",
        "/api/workspace/tokens",
    ],
)
def test_demo_has_no_admin_credential_creation_or_revocation_capability(demo, path):
    connect(demo)
    assert demo.post(path).status_code in {403, 404, 405}


def test_demo_cannot_change_policy_or_invoke_cron(demo):
    connect(demo)
    assert demo.put("/api/v1/integrations/payroll/config", json={}).status_code == 403
    assert demo.get("/api/cron/refresh").status_code == 401
    cookie = demo.cookies.get(COOKIE_NAME)
    assert demo.post(
        "/api/ingest",
        headers={"Authorization": "Bearer " + cookie},
        json={"events": []},
    ).status_code in {401, 403}


def test_invalid_tenant_is_unavailable_and_cannot_fall_back(demo, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_tenant_slug", "missing")
    assert demo.post("/api/demo/session").status_code == 503
    assert demo.get("/api/workspace").status_code == 401


@pytest.mark.parametrize(
    "values",
    [
        {"demo_tenant_slug": ""},
        {"demo_session_secret": ""},
        {"demo_session_secret": "short"},
        {
            "demo_session_secret": "independent-secret-for-config-test",
            "cron_secret": "independent-secret-for-config-test",
        },
    ],
)
def test_incomplete_demo_configuration_fails_closed(values):
    with pytest.raises(ValidationError):
        Settings(
            database_url="sqlite://",
            app_env="test",
            demo_mode=True,
            **(
                {
                    "demo_tenant_slug": "a",
                    "demo_session_secret": "offline-signing-for-settings-validation",
                }
                | values
            ),
        )


def test_cookie_expiry_and_renewal(demo, monkeypatch):
    monkeypatch.setattr("app.api.demo.time.time", lambda: 10000)
    connect(demo)
    monkeypatch.setattr("app.api.demo.time.time", lambda: 10000 + SESSION_SECONDS - 1)
    assert demo.get("/api/workspace").status_code == 200
    monkeypatch.setattr("app.api.demo.time.time", lambda: 10000 + SESSION_SECONDS)
    assert demo.get("/api/workspace").status_code == 401
    connect(demo)
    assert demo.get("/api/workspace").status_code == 200


def test_tampering_config_change_and_disabling_revoke_demo_scope(demo, monkeypatch):
    connect(demo)
    cookie = demo.cookies.get(COOKIE_NAME)
    demo.cookies.clear()
    demo.cookies.set(
        COOKIE_NAME, cookie[:-3] + "000", domain="testserver.local", path="/"
    )
    assert demo.get("/api/workspace").status_code == 401
    demo.cookies.clear()
    connect(demo)
    monkeypatch.setattr(get_settings(), "demo_tenant_slug", "b")
    assert demo.get("/api/workspace").status_code == 401
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert demo.get("/api/workspace").status_code == 401


def test_csrf_protection_for_session_and_demo_mutations(demo):
    assert (
        demo.post(
            "/api/demo/session", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert (
        demo.post("/api/demo/session", headers={"X-Demo-Request": ""}).status_code
        == 403
    )
    connect(demo)
    assert (
        demo.post(
            "/api/evaluate", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert demo.post("/api/evaluate", headers={"X-Demo-Request": ""}).status_code == 403
    assert (
        demo.post("/api/evaluate", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )


def test_cookie_never_authenticates_as_a_workspace_bearer(demo):
    connect(demo)
    cookie = demo.cookies.get(COOKIE_NAME)
    assert (
        demo.get(
            "/api/workspace", headers={"Authorization": "Bearer " + cookie}
        ).status_code
        == 401
    )
    assert hashlib.sha256(cookie.encode()).hexdigest() != cookie


def test_production_csrf_accepts_tls_termination_but_rejects_http_origins(
    demo, monkeypatch
):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    demo.base_url = "http://testserver"
    assert demo.post("/api/demo/session").status_code == 200
    assert (
        demo.post(
            "/api/demo/session", headers={"Origin": "http://testserver"}
        ).status_code
        == 403
    )
