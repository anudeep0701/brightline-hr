"""Current-time assessment fixtures and the constrained public import capability."""

from datetime import datetime, timedelta, timezone

import pytest
from app.config import get_settings
from app.health.service import bucket_for
from app.ingestion.service import ingest
from app.models.entities import Incident, Integration, RequestEvent, Snapshot
from app.services.demo_data import clear_demo_imports, refresh_demo_data
from sqlalchemy import func, select
from tests.test_demo_access import connect
from tests.test_demo_access import demo as demo


def count(db):
    return db.scalar(select(func.count()).select_from(RequestEvent))


def test_fresh_baseline_is_current_bounded_reproducible_and_idempotent(demo, db):
    now = bucket_for(datetime.now(timezone.utc))
    first = refresh_demo_data(db, get_settings(), now=now)
    assert first["accepted"] == 96
    rows = list(db.scalars(select(RequestEvent).where(RequestEvent.tenant_id == "a")))
    assert all(now - timedelta(minutes=30) <= r.occurred_at < now for r in rows)
    assert all(r.source_type == "DEMO" for r in rows)
    latest = db.scalar(
        select(Snapshot)
        .where(Snapshot.tenant_id == "a")
        .order_by(Snapshot.bucket.desc())
        .limit(1)
    )
    assert latest.status == "HEALTHY"
    second = refresh_demo_data(db, get_settings(), now=now, force=True)
    assert second["accepted"] == second["evaluated"] == 0
    assert count(db) == 96
    assert (
        db.scalar(
            select(func.count())
            .select_from(RequestEvent)
            .where(RequestEvent.tenant_id == "b")
        )
        == 0
    )


def test_session_freshens_stale_demo_without_editing_old_rows(demo, db):
    at = datetime.now(timezone.utc) - timedelta(days=2)
    ingest(
        db,
        "a",
        [
            dict(
                timestamp=at.isoformat(),
                request_id="old",
                integration_id="payroll",
                http_status=200,
                latency_ms=100,
            )
        ],
        source_type="DEMO",
    )
    connect(demo)
    assert db.get(RequestEvent, ("a", "old")).occurred_at == at
    dashboard = demo.get("/api/v1/dashboard").json()
    item = dashboard["integrations"][0]
    assert item["freshness"]["status"] == "RECENT_TRAFFIC"
    assert not item["freshness"]["evaluation_overdue"]
    before = count(db)
    connect(demo)
    assert count(db) == before


def test_intentional_stale_unknown_and_low_volume_remain(demo, db):
    at = datetime.now(timezone.utc) - timedelta(hours=2)
    ingest(
        db,
        "a",
        [
            dict(
                timestamp=at.isoformat(),
                request_id="intentional",
                integration_id="payroll",
                http_status=200,
                latency_ms=100,
                scenario="stale_telemetry",
            )
        ],
        source_type="DEMO",
    )
    connect(demo)
    item = demo.get("/api/v1/dashboard").json()["integrations"][0]
    assert item["freshness"]["current_evidence_status"] == "UNKNOWN"
    assert item["freshness"]["status"] == "STALE_TELEMETRY"
    assert count(db) == 1


def test_baseline_has_real_incident_recovery_degradation_and_sparse_unknown(demo, db):
    for identity in [
        "adp-payroll",
        "slack-notifications",
        "adp-recovery",
        "twilio-notifications",
    ]:
        db.add(
            Integration(
                tenant_id="a",
                id=identity,
                name=identity,
                category="Payroll",
                owner="Ops",
            )
        )
    db.commit()
    connect(demo)
    items = {
        x["integration"]["id"]: x
        for x in demo.get("/api/v1/dashboard").json()["integrations"]
    }
    assert items["payroll"]["snapshot"]["status"] == "HEALTHY"
    assert items["adp-payroll"]["snapshot"]["status"] == "DEGRADED"
    assert items["slack-notifications"]["snapshot"]["status"] == "UNHEALTHY"
    assert items["twilio-notifications"]["snapshot"]["status"] == "UNKNOWN"
    assert items["twilio-notifications"]["freshness"]["status"] == "RECENT_TRAFFIC"
    assert db.scalar(
        select(Incident).where(
            Incident.tenant_id == "a",
            Incident.integration_id == "adp-recovery",
            Incident.resolved_at.is_not(None),
        )
    )


def upload(client, content, fmt="json", commit=False, digest=None):
    return client.post(
        "/api/imports/" + ("commit" if commit else "preview") + "?format=" + fmt,
        content=content,
        headers={
            "Content-Type": {
                "json": "application/json",
                "csv": "text/csv",
                "ndjson": "application/x-ndjson",
            }.get(fmt, "text/plain"),
            **(
                {"X-Confirm-Import": "true", "X-Preview-Digest": digest}
                if commit
                else {}
            ),
        },
    )


def event(**changes):
    return dict(
        timestamp=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        request_id="pilot",
        integration_id="payroll",
        http_status=503,
        latency_ms=100,
        **changes,
    )


@pytest.mark.parametrize("fmt", ["csv", "json", "ndjson"])
def test_demo_import_preview_commit_provenance_duplicates_and_cleanup(
    demo, db, monkeypatch, fmt
):
    import json

    monkeypatch.setattr(get_settings(), "demo_allow_file_import", True)
    connect(demo)
    row = event()
    content = (
        (",".join(row) + "\n" + ",".join(str(v) for v in row.values()) + "\n")
        if fmt == "csv"
        else json.dumps([row])
        if fmt == "json"
        else json.dumps(row) + "\n"
    )
    before = count(db)
    preview = upload(demo, content, fmt)
    assert preview.status_code == 200 and preview.json()["valid_records"] == 1
    assert count(db) == before
    result = upload(demo, content, fmt, True, preview.json()["file_digest"])
    assert result.status_code == 200 and result.json()["accepted"] == 1
    stored = db.get(RequestEvent, ("a", "pilot"))
    assert stored.source_type == "FILE_IMPORT"
    assert (
        stored.raw_event["demo_import_batch_id"]
        == result.headers["X-Demo-Import-Batch"]
    )
    assert upload(demo, content, fmt).json()["duplicates"] == 1
    assert clear_demo_imports(db, get_settings()) == 1
    assert count(db) == before
    assert db.scalar(select(func.count()).select_from(Snapshot)) > 0


@pytest.mark.parametrize(
    "content,fmt,status",
    [
        ("{", "json", 422),
        ("[]", "exe", 415),
        ("x" * (2 * 1024 * 1024 + 1), "json", 413),
    ],
)
def test_demo_import_rejects_bad_unsupported_oversized_files(
    demo, monkeypatch, content, fmt, status
):
    monkeypatch.setattr(get_settings(), "demo_allow_file_import", True)
    connect(demo)
    assert upload(demo, content, fmt).status_code == status


def test_cross_tenant_demo_file_is_blocked_and_partial_invalid_rows_reported(
    demo, db, monkeypatch
):
    import json

    monkeypatch.setattr(get_settings(), "demo_allow_file_import", True)
    connect(demo)
    bad_scope = [dict(event(), tenant_id="b")]
    preview = upload(demo, json.dumps(bad_scope))
    assert not preview.json()["can_import"]
    assert (
        upload(
            demo,
            json.dumps(bad_scope),
            commit=True,
            digest=preview.json()["file_digest"],
        ).status_code
        == 403
    )
    good = event()
    invalid = dict(good, request_id="bad", latency_ms=-1)
    content = json.dumps([good, good, invalid])
    preview = upload(demo, content)
    assert (
        preview.json()["valid_records"],
        preview.json()["duplicates"],
        preview.json()["rejected_records"],
    ) == (1, 1, 1)
    result = upload(demo, content, commit=True, digest=preview.json()["file_digest"])
    assert (
        result.json()["accepted"],
        result.json()["duplicates"],
        result.json()["rejected"],
    ) == (1, 1, 1)
    assert db.get(RequestEvent, ("b", "pilot")) is None


def test_upload_permission_and_refresh_fail_closed_without_demo(
    demo, client, monkeypatch
):
    connect(demo)
    assert upload(demo, "[]").status_code == 403
    assert demo.post("/api/demo/refresh?tenant_id=b").status_code == 403
    assert demo.post("/api/ingest", json={"events": []}).status_code == 401
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert upload(demo, "[]").status_code == 401
    assert demo.post("/api/demo/refresh").status_code == 401


def test_new_bucket_refills_but_does_not_overwrite_snapshots_or_uploaded_evidence(
    demo, db
):
    now = bucket_for(datetime.now(timezone.utc))
    refresh_demo_data(db, get_settings(), now=now)
    original = list(db.scalars(select(Snapshot)))
    old_values = {r.id: r.reason_text for r in original}
    next_time = now + timedelta(minutes=10)
    assert refresh_demo_data(db, get_settings(), now=next_time)["accepted"] == 96
    assert all(
        db.get(Snapshot, key).reason_text == value for key, value in old_values.items()
    )
    ingest(
        db,
        "a",
        [
            dict(
                timestamp=next_time.isoformat(),
                request_id="owner-import",
                integration_id="payroll",
                http_status=503,
                latency_ms=100,
            )
        ],
        now=next_time,
        source_type="FILE_IMPORT",
    )
    assert (
        refresh_demo_data(
            db, get_settings(), now=next_time + timedelta(minutes=10), force=True
        )["accepted"]
        == 0
    )


def test_cleanup_removes_only_tagged_demo_tenant_imports(demo, db):
    for tenant, key, tag in [
        ("a", "tagged", "demo-1"),
        ("b", "other", "demo-2"),
        ("a", "untagged", None),
    ]:
        ingest(
            db,
            tenant,
            [dict(event(), request_id=key)],
            source_type="FILE_IMPORT",
            import_batch_id=tag,
        )
    assert clear_demo_imports(db, get_settings()) == 1
    assert db.get(RequestEvent, ("b", "other")) and db.get(
        RequestEvent, ("a", "untagged")
    )


def test_demo_import_capacity_and_no_browser_provenance_override(demo, db, monkeypatch):
    import json

    monkeypatch.setattr(get_settings(), "demo_allow_file_import", True)
    monkeypatch.setattr("app.ingestion.uploads.MAX_DEMO_IMPORTS", 1)
    connect(demo)
    for index in range(2):
        content = json.dumps([dict(event(), request_id=f"cap-{index}")])
        preview = upload(demo, content)
        result = upload(
            demo, content, commit=True, digest=preview.json()["file_digest"]
        )
        assert result.status_code == (200 if index == 0 else 413)
    forged = json.dumps([dict(event(), demo_import_batch_id="forged")])
    assert upload(demo, forged).json()["rejected_records"] == 1


def test_bulk_path_preserves_validation_deduplication_and_normalized_values(db):
    rows = [
        dict(event(), request_id="bulk"),
        dict(event(), request_id="bulk"),
        dict(event(), request_id="bad", latency_ms=-1),
    ]
    now = datetime.now(timezone.utc)
    first = ingest(db, "a", rows, now=now, bulk=True)
    second = ingest(db, "b", rows, now=now)
    assert first == second
    a = db.get(RequestEvent, ("a", "bulk"))
    b = db.get(RequestEvent, ("b", "bulk"))
    for field in [
        "occurred_at",
        "latency_ms",
        "status_code",
        "source_type",
        "error_category",
    ]:
        assert getattr(a, field) == getattr(b, field)
