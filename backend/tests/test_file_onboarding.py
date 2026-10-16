"""Customer uploads share event validation, tenant scope and persistence with the API."""

import csv
import io
import json
from datetime import timedelta

import pytest
from app.ingestion.credentials import issue_key
from app.models.entities import RequestEvent
from sqlalchemy import func, select
from tests.test_monitoring_workflows import headers


def event(clock, **changes):
    return dict(
        timestamp=(clock.now - timedelta(minutes=1)).isoformat(),
        request_id="pilot-1",
        integration_id="payroll",
        http_status=503,
        latency_ms=125,
        error_code="UPSTREAM",
        **changes,
    )


def encode(rows, format):
    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode()
    if format == "json":
        return json.dumps({"events": rows}).encode()
    return "\n".join(json.dumps(row) for row in rows).encode()


def upload(
    client, data, format="json", *, commit=False, digest=None, tenant="a", extra=None
):
    mime = {
        "csv": "text/csv",
        "json": "application/json",
        "ndjson": "application/x-ndjson",
        "jsonl": "application/x-ndjson",
    }.get(format, "application/octet-stream")
    auth = headers(tenant)
    if commit:
        auth.update({"X-Confirm-Import": "true", "X-Preview-Digest": digest or ""})
    auth.update(extra or {})
    return client.post(
        f"/api/imports/{'commit' if commit else 'preview'}?format={format}",
        headers={**auth, "Content-Type": mime},
        content=data,
    )


@pytest.mark.parametrize("format", ["csv", "json", "ndjson", "jsonl"])
def test_valid_preview_then_explicit_import(client, db, monitoring_clock, format):
    data = encode([event(monitoring_clock)], format)
    preview = upload(client, data, format)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert (
        result["total_records"],
        result["valid_records"],
        result["duplicates"],
        result["rejected_records"],
    ) == (1, 1, 0, 0)
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0
    assert result["can_import"]
    response = upload(client, data, format, commit=True, digest=result["file_digest"])
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1
    stored = db.get(RequestEvent, ("a", "pilot-1"))
    assert stored.source_type == "FILE_IMPORT" and stored.tenant_id == "a"
    assert stored.status_code == 503 and stored.latency_ms == 125
    assert stored.occurred_at.utcoffset() == timedelta(0)
    replay = upload(client, data, format).json()
    assert replay["duplicates"] == 1 and replay["valid_records"] == 0
    sources = client.get("/api/data-sources", headers=headers()).json()["items"][0]
    assert sources["sources"][0]["source_type"] == "FILE_IMPORT"
    assert sources["freshness"]["last_event_received_at"] is not None
    assert (
        client.get("/api/data-sources", headers=headers("b")).json()["items"][0][
            "sources"
        ]
        == []
    )


@pytest.mark.parametrize(
    "format,data",
    [
        ("json", b"{broken"),
        ("json", b"{}"),
        ("csv", b"a,a\n1,2"),
        ("csv", b'a,b\n"unterminated'),
        ("json", b"\xff"),
        ("json", b""),
    ],
)
def test_malformed_file_is_rejected_without_writes(client, db, format, data):
    response = upload(client, data, format)
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0


def test_unsupported_type_size_and_record_bounds(client, monitoring_clock):
    assert upload(client, b"anything", "exe").status_code == 415
    assert upload(client, b"x" * (2 * 1024 * 1024 + 1), "csv").status_code == 413
    assert (
        upload(client, encode([event(monitoring_clock)] * 1001, "json")).status_code
        == 413
    )


def test_partial_validation_and_duplicate_preview_match_commit(
    client, db, monitoring_clock
):
    good = event(monitoring_clock)
    rows = [good, good, {**good, "request_id": "bad", "latency_ms": -1}]
    data = encode(rows, "json")
    preview = upload(client, data).json()
    assert (
        preview["valid_records"],
        preview["duplicates"],
        preview["rejected_records"],
    ) == (1, 1, 1)
    assert preview["validation_errors"] == [
        {"index": 2, "code": "invalid_record", "fields": ["latency_ms"]}
    ]
    result = upload(client, data, commit=True, digest=preview["file_digest"])
    assert result.status_code == 200
    assert (
        result.json()["accepted"],
        result.json()["duplicates"],
        result.json()["rejected"],
    ) == (1, 1, 1)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"integration_id": "unregistered"}, "unknown_integration"),
        ({"tenant_id": "b"}, "tenant_mismatch"),
    ],
)
def test_unauthorized_rows_block_whole_import(
    client, db, monitoring_clock, changes, code
):
    rows = [
        event(monitoring_clock),
        {**event(monitoring_clock), "request_id": "forbidden", **changes},
    ]
    data = encode(rows, "json")
    preview = upload(client, data).json()
    assert not preview["can_import"]
    assert preview["validation_errors"][0]["code"] == code
    assert preview["unknown_integrations"] == (
        1 if code == "unknown_integration" else 0
    )
    assert (
        upload(client, data, commit=True, digest=preview["file_digest"]).status_code
        == 403
    )
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0
    assert (
        client.post(
            "/api/imports/preview?format=json&tenant_id=b",
            headers={**headers(), "Content-Type": "application/json"},
            content=data,
        ).status_code
        == 403
    )


def test_confirmation_and_unchanged_file_required(client, db, monitoring_clock):
    data = encode([event(monitoring_clock)], "json")
    assert (
        client.post(
            "/api/imports/commit?format=json",
            headers={**headers(), "Content-Type": "application/json"},
            content=data,
        ).status_code
        == 422
    )
    assert upload(client, data, commit=True, digest="wrong").status_code == 409
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0


def test_only_workspace_operators_can_upload(client, db, monitoring_clock):
    key, secret = issue_key(db, "a", "customer collector")
    data = encode([event(monitoring_clock)], "json")
    for credential, status in [(None, 401), ("reader", 403), (secret, 403)]:
        auth = {"Content-Type": "application/json"}
        if credential:
            auth["Authorization"] = "Bearer " + credential
        response = client.post(
            "/api/imports/preview?format=json", headers=auth, content=data
        )
        assert response.status_code == status
    assert db.get(type(key), key.id).digest != secret


def test_csv_and_production_api_have_equivalent_normalized_records(
    client, db, monitoring_clock
):
    rows = [event(monitoring_clock)]
    data = encode(rows, "csv")
    preview = upload(client, data, "csv").json()
    assert (
        upload(
            client, data, "csv", commit=True, digest=preview["file_digest"]
        ).status_code
        == 200
    )
    _, key = issue_key(db, "b", "production collector")
    response = client.post(
        "/api/ingest", headers={"Authorization": "Bearer " + key}, json={"events": rows}
    )
    assert response.status_code == 200 and response.json()["accepted"] == 1
    first, second = (db.get(RequestEvent, (tenant, "pilot-1")) for tenant in ("a", "b"))
    for field in (
        "occurred_at",
        "status_code",
        "latency_ms",
        "timed_out",
        "error_category",
        "error_code",
        "integration_id",
    ):
        assert getattr(first, field) == getattr(second, field)
    assert first.source_type == "FILE_IMPORT" and second.source_type == "LIVE_API"
    assert {k: v for k, v in first.raw_event.items() if k != "tenant_id"} == {
        k: v for k, v in second.raw_event.items() if k != "tenant_id"
    }


def test_ndjson_bad_lines_have_visible_row_errors_and_filenames_are_not_paths(
    client, db, monitoring_clock
):
    data = encode([event(monitoring_clock)], "ndjson") + b"\nnot json\n"
    preview = upload(
        client, data, "ndjson", extra={"X-Filename": "../../private/secret.env"}
    ).json()
    assert preview["valid_records"] == preview["rejected_records"] == 1
    assert preview["validation_errors"][0]["index"] == 1
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 0


def test_backfill_allowed_but_future_events_are_rejected(client, monitoring_clock):
    row = event(monitoring_clock)
    row["timestamp"] = (monitoring_clock.now - timedelta(days=30)).isoformat()
    data = encode([row], "json")
    preview = upload(client, data).json()
    assert preview["can_import"]
    assert (
        upload(client, data, commit=True, digest=preview["file_digest"]).json()[
            "accepted"
        ]
        == 1
    )
    future = {
        **row,
        "request_id": "future",
        "timestamp": (monitoring_clock.now + timedelta(seconds=1)).isoformat(),
    }
    response = upload(client, encode([future], "json")).json()
    assert response["rejected_records"] == 1
    assert response["validation_errors"][0]["code"] == "timestamp_out_of_range"


def test_commit_rechecks_duplicates_after_preview(client, monitoring_clock):
    row = event(monitoring_clock)
    data = encode([row], "json")
    preview = upload(client, data).json()
    assert preview["valid_records"] == 1
    assert (
        client.post("/api/ingest", headers=headers(), json={"events": [row]}).json()[
            "accepted"
        ]
        == 1
    )
    result = upload(client, data, commit=True, digest=preview["file_digest"]).json()
    assert result["accepted"] == 0 and result["duplicates"] == 1
    source = client.get("/api/data-sources", headers=headers()).json()["items"][0][
        "sources"
    ]
    assert [item["source_type"] for item in source] == ["LIVE_API"]


def test_source_cannot_be_forged_by_upload_or_api(client, monitoring_clock):
    row = {**event(monitoring_clock), "source_type": "DEMO"}
    data = encode([row], "json")
    preview = upload(client, data).json()
    assert preview["valid_records"] == 0 and preview["rejected_records"] == 1
    assert not preview["can_import"]
    result = client.post("/api/ingest", headers=headers(), json={"events": [row]})
    assert result.json()["accepted"] == 0 and result.json()["rejected"] == 1


def test_upload_cors_allows_confirmation_headers(client):
    result = client.options(
        "/api/imports/commit?format=csv",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-confirm-import,x-preview-digest",
        },
    )
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_explicit_sqlite_init_adds_provenance_without_losing_old_events():
    from app.db.migrations import initialize_database
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE request_events (tenant_id TEXT, event_id TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO request_events VALUES ('legacy-tenant','legacy-event')"
        )
    initialize_database(engine)
    initialize_database(engine)
    assert "source_type" in {
        column["name"] for column in inspect(engine).get_columns("request_events")
    }
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT tenant_id,event_id,source_type FROM request_events")
        ).one()
        assert tuple(row) == ("legacy-tenant", "legacy-event", "UNKNOWN")
    engine.dispose()
