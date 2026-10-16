import csv
import json
from datetime import datetime, timedelta, timezone

import pytest
from app.config import Settings
from app.health.service import bucket_for, refresh
from app.ingestion.files import ingest_file
from app.ingestion.service import ingest
from app.models.entities import (
    HealthSnapshot,
    Integration,
    IntegrationConfig,
    MetricRollup,
    RequestEvent,
)
from pydantic import ValidationError
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError

HEADERS = {"Authorization": "Bearer a"}


def event(request_id="req-1", **updates):
    row = dict(
        timestamp=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        tenant_id="a",
        integration_id="payroll",
        integration_name="Payroll",
        integration_type="payroll",
        request_id=request_id,
        http_status=503,
        latency_ms=125.0,
        error_code="PROVIDER_UNAVAILABLE",
        error_message="Synthetic provider unavailable",
    )
    return dict(row, **updates)


def test_requested_tables_and_config_are_real_storage(db):
    tables = set(inspect(db.get_bind()).get_table_names())
    assert {
        "tenants",
        "integrations",
        "request_events",
        "integration_config",
        "metric_rollups",
        "health_snapshots",
        "health_incidents",
    } <= tables
    assert not {"request_logs", "incidents"} & tables
    integration = db.get(Integration, ("a", "payroll"))
    integration.latency_target_ms = 1700
    db.commit()
    assert db.get(IntegrationConfig, ("a", "payroll")).latency_target_ms == 1700


def test_api_mixed_batch_counts_and_no_raw_error_leaks(client, db):
    private = "DO_NOT_ECHO_THIS_VALUE"
    rows = [
        event(),
        event(),
        {"latency_ms": private},
        event("req-b", tenant_id="b"),
        None,
        event("unknown", integration_id="foreign"),
        event("req-2"),
    ]
    response = client.post(
        "/api/v1/request-events", headers=HEADERS, json={"events": rows}
    )
    assert response.status_code == 200
    result = response.json()
    assert (result["accepted"], result["rejected"], result["duplicates"]) == (2, 4, 1)
    assert result["accepted"] + result["rejected"] + result["duplicates"] == len(rows)
    assert private not in response.text
    assert [x["index"] for x in result["rejections"]] == [2, 3, 4, 5]
    stored = db.get(RequestEvent, ("a", "req-1"))
    assert stored.error_message == event()["error_message"]
    assert stored.raw_event["error_code"] == "PROVIDER_UNAVAILABLE"
    assert "metrics" not in stored.raw_event
    detail = client.get("/api/v1/integrations/payroll", headers=HEADERS).json()
    assert (
        "raw_event" not in detail["logs"][0]
        and "error_message" not in detail["logs"][0]
    )


def test_retry_and_duplicate_with_changed_data_never_overwrites(db):
    first = event()
    assert ingest(db, "a", [first])["accepted"] == 1
    changed = dict(first, http_status=401, latency_ms=999)
    result = ingest(db, "a", [changed, changed])
    assert result["duplicates"] == 2 and result["accepted"] == 0
    db.expire_all()
    stored = db.get(RequestEvent, ("a", "req-1"))
    assert stored.status_code == 503 and stored.latency_ms == 125
    assert ingest(db, "b", [dict(first, tenant_id="b")])["accepted"] == 1


def test_utc_normalization_and_naive_timestamp_rejection(db):
    offset = timezone(timedelta(hours=5, minutes=30))
    at = datetime.now(offset) - timedelta(minutes=1)
    result = ingest(
        db,
        "a",
        [
            event(timestamp=at.isoformat()),
            event("naive", timestamp=at.replace(tzinfo=None).isoformat()),
        ],
    )
    assert result["accepted"] == 1 and result["rejected"] == 1
    stored = db.get(RequestEvent, ("a", "req-1"))
    assert stored.occurred_at == at.astimezone(timezone.utc)
    assert stored.occurred_at.utcoffset() == timedelta(0)
    assert stored.received_at.utcoffset() == timedelta(0)


def test_database_rejects_naive_direct_write(db):
    with pytest.raises(StatementError):
        with db.begin_nested():
            db.add(
                RequestEvent(
                    tenant_id="a",
                    event_id="naive",
                    integration_id="payroll",
                    occurred_at=datetime(2026, 10, 15),
                    status_code=200,
                    latency_ms=100,
                )
            )
            db.flush()


def test_error_in_savepoint_does_not_poison_following_records(db, monkeypatch):
    execute = db.execute
    calls = 0

    def execute_with_one_bad_insert(statement, *args, **kwargs):
        nonlocal calls
        if getattr(statement, "is_insert", False):
            calls += 1
            if calls == 2:
                raise IntegrityError(
                    "redacted", None, Exception("private database detail")
                )
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute_with_one_bad_insert)
    result = ingest(db, "a", [event("one"), event("bad"), event("two")])
    assert (result["accepted"], result["rejected"]) == (2, 1)
    assert result["rejections"][0]["code"] == "constraint_violation"
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 2


def test_rollups_and_snapshots_are_separate_and_idempotent(db):
    at = bucket_for(datetime.now(timezone.utc))
    ingest(
        db,
        "a",
        [
            event(str(n), timestamp=(at - timedelta(seconds=n + 1)).isoformat())
            for n in range(30)
        ],
    )
    assert db.scalar(select(func.count()).select_from(MetricRollup)) == 0
    refresh(db, "a", at)
    snapshot = db.scalar(select(HealthSnapshot))
    rollup = db.get(MetricRollup, snapshot.metric_rollup_id)
    assert rollup.metrics["request_count"] == 30 and snapshot.status == "DEGRADED"
    assert rollup.tenant_id == snapshot.tenant_id == "a"
    assert snapshot.evidence["metrics"] == rollup.metrics
    refresh(db, "a", at)
    assert db.scalar(select(func.count()).select_from(MetricRollup)) == 1
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 30


@pytest.mark.parametrize("suffix", [".json", ".jsonl", ".csv"])
def test_file_loaders_partial_acceptance_and_retry(db, tmp_path, suffix):
    rows = [event("one"), event("one"), event("bad", latency_ms=-10), event("two")]
    path = tmp_path / f"events{suffix}"
    if suffix == ".json":
        path.write_text(json.dumps({"events": rows}))
    elif suffix == ".jsonl":
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\nnot valid JSON\n"
        )
    else:
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    first = ingest_file(db, "a", path, batch_size=2)
    assert (first["accepted"], first["duplicates"], first["rejected"]) == (
        2,
        1,
        2 if suffix == ".jsonl" else 1,
    )
    assert first["rejections"][0]["index"] == 2
    second = ingest_file(db, "a", path, batch_size=2)
    assert second["accepted"] == 0 and second["duplicates"] == 3


def test_generated_sample_import_and_explicit_historical_replay(db, tmp_path):
    from scripts.generate_synthetic_data import generate_events

    historical = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    ) - timedelta(days=30)
    row = next(
        generate_events(
            scenario="healthy", tenants=1, start=historical, duration_minutes=60
        )
    )
    row.update(tenant_id="a", integration_id="payroll")
    path = tmp_path / "generated.json"
    path.write_text(json.dumps([row]))
    assert ingest_file(db, "a", path)["rejected"] == 1
    assert ingest_file(db, "a", path, allow_historical=True)["accepted"] == 1
    assert (
        ingest(
            db,
            "a",
            [
                event(
                    "future",
                    timestamp=(
                        datetime.now(timezone.utc) + timedelta(days=1)
                    ).isoformat(),
                )
            ],
            allow_historical=True,
        )["rejected"]
        == 1
    )


@pytest.mark.parametrize("data", [{}, {"events": []}, {"events": [None] * 1001}])
def test_invalid_envelopes_are_rejected_before_ingestion(client, data):
    assert (
        client.post("/api/v1/request-events", headers=HEADERS, json=data).status_code
        == 422
    )


def test_missing_database_url_is_actionable_and_secrets_are_hidden(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL is not configured"):
        Settings()
    with pytest.raises(ValidationError) as caught:
        Settings(database_url="invalid://do-not-display-secret")
    assert "do-not-display-secret" not in str(caught.value)


def test_postgres_schema_uses_timezone_columns_and_composite_keys():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(RequestEvent.__table__).compile(dialect=postgresql.dialect()))
    assert (
        "TIMESTAMP WITH TIME ZONE" in ddl and "PRIMARY KEY (tenant_id, event_id)" in ddl
    )
    assert "FOREIGN KEY(tenant_id, integration_id)" in ddl


def test_cli_missing_database_does_not_read_environment_files(monkeypatch):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    for arguments in (
        ["scripts/init_db.py"],
        ["scripts/migrate.py"],
        ["scripts/ingestion_keys.py", "list", "a"],
        [
            "scripts/ingest_file.py",
            "data/synthetic/sample/requests.jsonl",
            "--tenant",
            "a",
        ],
    ):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "DATABASE_URL is not configured" in result.stderr
        assert "Traceback" not in result.stderr


def test_initialize_local_is_idempotent_and_refuses_legacy_demo(tmp_path):
    from app.db.migrations import initialize_database
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    initialize_database(engine)
    initialize_database(engine)
    assert "request_events" in inspect(engine).get_table_names()
    engine.dispose()
    legacy = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with legacy.begin() as connection:
        connection.execute(text("CREATE TABLE request_logs (id INTEGER)"))
    with pytest.raises(ValueError, match="Legacy SQLite demo schema"):
        initialize_database(legacy)
    assert inspect(legacy).get_table_names() == ["request_logs"]
    legacy.dispose()


def test_database_prevents_cross_tenant_rollup_reference(db):
    at = bucket_for(datetime.now(timezone.utc))
    refresh(db, "a", at)
    original = db.scalar(select(HealthSnapshot))
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                HealthSnapshot(
                    tenant_id="b",
                    integration_id="payroll",
                    bucket=at,
                    evaluated_at=at,
                    metric_rollup_id=original.metric_rollup_id,
                    status="HEALTHY",
                    score=100,
                    evidence=original.evidence,
                )
            )
            db.flush()


def test_file_rejection_counts_are_not_truncated_with_details(db, tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text("null\n" * 101)
    result = ingest_file(db, "a", path, batch_size=50)
    assert result["accepted"] == 0 and result["rejected"] == 101
    assert len(result["rejections"]) == 100 and result["rejections_omitted"] == 1


def test_envelope_errors_do_not_echo_submitted_values(client):
    response = client.post(
        "/api/v1/request-events",
        headers=HEADERS,
        json={"events": "DO_NOT_ECHO_ENVELOPE"},
    )
    assert response.status_code == 422
    assert "DO_NOT_ECHO_ENVELOPE" not in response.text
