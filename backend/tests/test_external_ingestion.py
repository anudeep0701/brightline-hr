"""External ingestion contract: tenant-bound keys, least privilege and real storage."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.config import get_settings
from app.ingestion.credentials import (
    authenticate_key,
    issue_key,
    key_digest,
    revoke_key,
)
from app.models.entities import AccessToken, IngestionAPIKey, Integration, RequestEvent
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def external_keys(db):
    # Explicit fake secrets for repeatable tests; production issuance uses secrets.token_urlsafe(32).
    keys = {tenant: "bl_ingest_" + tenant * 43 for tenant in ("a", "b")}
    for index, (tenant, secret) in enumerate(keys.items(), 1):
        db.add(
            IngestionAPIKey(
                id=f"00000000-0000-0000-0000-{index:012d}",
                tenant_id=tenant,
                digest=key_digest(secret),
                name=f"Customer exporter {tenant}",
                created_at=datetime(2026, 10, 15, 11, tzinfo=timezone.utc),
            )
        )
    db.commit()
    return keys


def auth(keys, tenant="a"):
    return {"Authorization": f"Bearer {keys[tenant]}"}


def send(client, keys, events, tenant="a", **kwargs):
    return client.post(
        "/api/ingest", headers=auth(keys, tenant), json={"events": events}, **kwargs
    )


def test_valid_production_style_batch_uses_authenticated_tenant_and_utc(
    client, db, external_keys, monitoring_clock, request_window, monkeypatch
):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    rows = request_window(count=2, errors=1)
    for row in rows:
        row.pop("tenant_id")
        row.update(integration_name="Workday Payroll", integration_type="payroll")
    offset = timezone(timedelta(hours=5, minutes=30))
    rows[0]["timestamp"] = (
        datetime.fromisoformat(rows[0]["timestamp"]).astimezone(offset).isoformat()
    )
    result = send(client, external_keys, rows)
    assert result.status_code == 200
    assert (
        result.json()["accepted"],
        result.json()["rejected"],
        result.json()["duplicates"],
    ) == (2, 0, 0)
    assert result.json()["validation_errors"] == []
    stored = db.get(RequestEvent, ("a", rows[0]["request_id"]))
    assert stored.tenant_id == stored.raw_event["tenant_id"] == "a"
    assert stored.occurred_at == datetime.fromisoformat(
        rows[0]["timestamp"]
    ).astimezone(timezone.utc)
    assert stored.received_at == monitoring_clock.now
    assert (
        db.scalar(
            select(func.count())
            .select_from(RequestEvent)
            .where(RequestEvent.tenant_id == "b")
        )
        == 0
    )
    assert external_keys["a"] not in result.text and "OPENAI" not in result.text


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer invalid-key",
        "Basic invalid-key",
        "Bearer bl_ingest_short",
        "Bearer bl_ingest_" + "z" * 43,
    ],
)
def test_missing_or_invalid_credentials_return_401(
    client, request_window, monitoring_clock, authorization
):
    response = client.post(
        "/api/ingest",
        json={"events": request_window(count=1)},
        headers={"Authorization": authorization} if authorization is not None else {},
    )
    assert (
        response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    )


def test_explicit_bad_credentials_never_fall_back_to_local_demo(
    client, monitoring_clock, request_window, monkeypatch
):
    monkeypatch.setattr(get_settings(), "app_env", "demo")
    response = client.post(
        "/api/ingest",
        headers={"Authorization": "Basic invalid"},
        json={"events": request_window(count=1)},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/workspace", None),
        ("GET", "/api/health-summary", None),
        ("GET", "/api/integrations", None),
        ("GET", "/api/integrations/payroll", None),
        ("GET", "/api/integrations/payroll/metrics", None),
        ("GET", "/api/integrations/payroll/incidents", None),
        ("POST", "/api/evaluate", None),
        ("POST", "/api/integrations/payroll/explain", None),
        ("POST", "/api/v1/logs", {"logs": [{}]}),
        ("PUT", "/api/v1/integrations/payroll/config", None),
    ],
)
def test_ingestion_key_never_grants_monitoring_or_operator_privileges(
    client, external_keys, method, path, body
):
    if method == "PUT":
        body = client.get(path, headers={"Authorization": "Bearer a"}).json()
    response = client.request(method, path, headers=auth(external_keys), json=body)
    assert response.status_code == 403 and response.json()["code"] == "forbidden"


def test_key_namespace_cannot_be_promoted_by_workspace_token_collision(
    client, db, external_keys
):
    # Even if a database operator mistakenly reuses the exact same plaintext for a workspace token,
    # the reserved ingestion namespace remains ingestion-only at the HTTP boundary.
    db.add(
        AccessToken(
            digest=hashlib.sha256(external_keys["a"].encode()).hexdigest(),
            tenant_id="a",
            role="operator",
        )
    )
    db.commit()
    assert client.post("/api/evaluate", headers=auth(external_keys)).status_code == 403


@pytest.mark.parametrize("attempt", ["tenant", "integration"])
def test_forbidden_record_rejects_entire_batch_before_any_writes(
    client, db, external_keys, monitoring_clock, request_window, attempt
):
    db.add(
        Integration(
            tenant_id="b",
            id="foreign-provider",
            name="Foreign provider",
            category="payroll",
            owner="Ops",
        )
    )
    db.commit()
    rows = request_window(count=2)
    if attempt == "tenant":
        rows[1]["tenant_id"] = "b"
    else:
        rows[1]["integration_id"] = "foreign-provider"
    response = send(client, external_keys, rows)
    assert (
        response.status_code == 403 and response.json()["code"] == "ingestion_forbidden"
    )
    assert (
        response.json()["accepted"],
        response.json()["rejected"],
        response.json()["duplicates"],
    ) == (0, 2, 0)
    assert response.json()["validation_errors"][0]["code"] == "batch_not_processed"
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0


def test_tenant_query_cannot_override_key_including_local_demo(
    client, external_keys, monitoring_clock, request_window, monkeypatch
):
    monkeypatch.setattr(get_settings(), "app_env", "demo")
    result = send(
        client, external_keys, request_window(count=1), params={"tenant_id": "b"}
    )
    assert result.status_code == 403 and result.json()["code"] == "tenant_forbidden"


def test_retries_across_keys_remain_idempotent_and_do_not_overwrite(
    client, db, external_keys, monitoring_clock, request_window
):
    rows = request_window(count=2)
    assert send(client, external_keys, rows).json()["accepted"] == 2
    retry = [dict(row, http_status=503, latency_ms=6000) for row in rows]
    response = send(client, external_keys, retry)
    assert (response.json()["accepted"], response.json()["duplicates"]) == (0, 2)
    assert db.get(RequestEvent, ("a", rows[0]["request_id"])).status_code == 200
    # A new source credential for the same tenant cannot bypass event identity.
    replacement, secret = issue_key(db, "a", "Rotated exporter")
    assert send(client, {"a": secret}, rows).json()["duplicates"] == 2
    assert replacement.tenant_id == "a"
    # Identical provider/request IDs are separate when another authenticated tenant sends them.
    assert (
        send(
            client,
            external_keys,
            [dict(row, tenant_id="b") for row in rows],
            tenant="b",
        ).json()["accepted"]
        == 2
    )
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 4


@pytest.mark.parametrize(
    "body",
    [{}, {"events": []}, {"events": "PRIVATE_BAD_ENVELOPE"}, {"events": [None] * 1001}],
)
def test_invalid_batch_envelope_is_422_without_echoing_payload(
    client, external_keys, body
):
    response = client.post("/api/ingest", headers=auth(external_keys), json=body)
    assert response.status_code == 422 and response.json()["code"] == "invalid_request"
    assert "PRIVATE_BAD_ENVELOPE" not in response.text


def test_all_invalid_events_return_422_with_safe_validation_errors(
    client, db, external_keys, monitoring_clock, request_window
):
    malformed = dict(request_window(count=1)[0], latency_ms="PRIVATE_BAD_VALUE")
    response = send(client, external_keys, [malformed, None])
    assert response.status_code == 422
    assert response.json()["accepted"] == 0 and response.json()["rejected"] == 2
    assert response.json()["validation_errors"][0]["fields"] == ["latency_ms"]
    assert "PRIVATE_BAD_VALUE" not in response.text
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0


def test_valid_peers_survive_malformed_records_and_future_timestamps(
    client, db, external_keys, monitoring_clock, request_window
):
    rows = request_window(count=2)
    future = dict(
        rows[0],
        request_id="future",
        timestamp=(monitoring_clock.now + timedelta(seconds=1)).isoformat(),
    )
    response = send(client, external_keys, [rows[0], None, future, rows[1]])
    assert response.status_code == 200
    assert (
        response.json()["accepted"],
        response.json()["rejected"],
        response.json()["duplicates"],
    ) == (2, 2, 0)
    assert [error["index"] for error in response.json()["validation_errors"]] == [1, 2]
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 2


def test_issuance_stores_only_hash_and_revocation_takes_effect(
    client, db, monitoring_clock, request_window, monkeypatch
):
    calls = []

    def secure_bytes(length):
        calls.append(length)
        return (
            "x" * 43
        )  # Test-only factory; the production factory is cryptographically random.

    monkeypatch.setattr("app.ingestion.credentials.secrets.token_urlsafe", secure_bytes)
    key, secret = issue_key(db, "a", "Customer backend")
    assert calls == [32] and len(secret) == 53
    assert key.digest == key_digest(secret) and len(key.digest) == 64
    assert key.digest != hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in str(
        {column.name: getattr(key, column.name) for column in key.__table__.columns}
    )
    assert authenticate_key(db, secret).tenant_id == "a"
    assert send(client, {"a": secret}, request_window(count=1)).status_code == 200
    revoked = revoke_key(db, key.id)
    assert (
        revoke_key(db, key.id).revoked_at == revoked.revoked_at
    )  # Repeat is harmless.
    assert authenticate_key(db, secret) is None
    assert send(client, {"a": secret}, request_window(count=1)).status_code == 401


def test_database_rejects_plaintext_generated_key_in_digest_column(db):
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                IngestionAPIKey(
                    tenant_id="a",
                    digest="bl_ingest_" + "x" * 43,
                    name="Invalid storage",
                )
            )
            db.flush()


def test_example_matches_production_event_schema():
    import json

    from app.schemas.ingestion import RequestBatch, RequestEventInput

    sample = (
        Path(__file__).resolve().parents[2] / "docs/examples/production-ingest.json"
    )
    batch = RequestBatch.model_validate(json.loads(sample.read_text()))
    assert all(
        RequestEventInput.model_validate(event).tenant_id is None
        for event in batch.events
    )


def test_generated_file_and_external_batch_use_the_same_ingestion_rules(
    client, db, external_keys, monitoring_clock, tmp_path
):
    import json

    from app.ingestion.files import ingest_file

    from scripts.generate_synthetic_data import generate_events

    generated = [
        row
        for row in generate_events(
            scenario="healthy",
            tenants=1,
            seed=42,
            start=monitoring_clock.now - timedelta(minutes=60),
            duration_minutes=60,
        )
        if row["integration_id"] == "workday-payroll"
    ][-100:]
    external = [dict(row, tenant_id="a", integration_id="payroll") for row in generated]
    offline = [dict(row, tenant_id="b", integration_id="payroll") for row in generated]
    path = tmp_path / "generated.json"
    path.write_text(json.dumps(offline))
    response = send(client, external_keys, external)
    file_result = ingest_file(db, "b", path)
    assert response.status_code == 200
    assert response.json()["accepted"] == file_result["accepted"] == 100
    assert file_result["rejected"] == response.json()["rejected"] == 0
    snapshots = []
    for tenant in ("a", "b"):
        assert (
            client.post(
                "/api/evaluate", headers={"Authorization": f"Bearer {tenant}"}
            ).status_code
            == 200
        )
        snapshots.append(
            client.get(
                "/api/integrations/payroll",
                headers={"Authorization": f"Bearer {tenant}"},
            ).json()["snapshot"]
        )
    assert snapshots[0]["status"] == snapshots[1]["status"] == "HEALTHY"
    assert snapshots[0]["metrics"] == snapshots[1]["metrics"]
    assert snapshots[0]["reason_text"] == snapshots[1]["reason_text"]


def test_trusted_cli_shows_secret_only_on_create_and_metadata_on_list(
    db, monkeypatch, capsys
):
    import sys

    from scripts import ingestion_keys as cli

    monkeypatch.setattr(cli, "get_engine", lambda: db.get_bind())
    monkeypatch.setattr(
        "app.ingestion.credentials.secrets.token_urlsafe", lambda length: "y" * 43
    )
    monkeypatch.setattr(
        sys, "argv", ["ingestion_keys.py", "create", "a", "--name", "Customer exporter"]
    )
    cli.main()
    secret = "bl_ingest_" + "y" * 43
    created = capsys.readouterr().out
    assert created.count(secret) == 1
    key = authenticate_key(db, secret)
    monkeypatch.setattr(sys, "argv", ["ingestion_keys.py", "list", "a"])
    cli.main()
    listing = capsys.readouterr().out
    assert "Customer exporter" in listing and key.id in listing
    assert secret not in listing and key.digest not in listing
    monkeypatch.setattr(sys, "argv", ["ingestion_keys.py", "revoke", key.id])
    cli.main()
    assert secret not in capsys.readouterr().out
    assert authenticate_key(db, secret) is None
