"""The supplied dataset uses the real ingestion, metric, policy and incident path."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from app.health.config import DEFAULT_POLICY
from app.ingestion.service import ingest
from app.models.entities import Incident, Integration, RequestEvent, Snapshot
from app.services.freshness import freshness, latest_telemetry
from sqlalchemy import func, select

from scripts.replay_official_data import SOURCE, main, normalize, replay

DIGEST = "ef3e4f8600b8c56274b43f5a9c5ea747c4d7c67fd2f85cedeb734afa4023234b"


def test_official_source_and_timeout_mapping():
    original = SOURCE.read_bytes()
    events, end, source_end, digest = normalize()
    assert digest == hashlib.sha256(original).hexdigest() == DIGEST
    assert len(events) == len({e["request_id"] for e in events}) == 60
    assert end == source_end == datetime(2026, 8, 4, 10, tzinfo=timezone.utc)
    assert sum(e["timed_out"] for e in events) == 5
    assert all(e["http_status"] == 504 for e in events if e["timed_out"])
    assert sum(e["http_status"] >= 400 for e in events) == 17
    assert SOURCE.read_bytes() == original


def test_official_replay_metrics_decisions_and_incidents(db):
    result = replay(db.get_bind())
    rows = {r["integration_id"]: r for r in result["integrations"]}
    assert result["accepted"] == 60 and len(rows) == 5
    assert all(r["request_count"] == 12 and r["reason"] for r in rows.values())
    for identity in ["starter-slack", "starter-workday"]:
        assert rows[identity]["status"] == "HEALTHY"
        assert rows[identity]["error_rate"] == pytest.approx(1 / 12)
    for identity in ["starter-adp", "starter-docusign", "starter-greenhouse"]:
        assert rows[identity]["status"] == "UNHEALTHY"
    greenhouse = rows["starter-greenhouse"]
    assert greenhouse["error_rate"] == 0.5
    assert greenhouse["timeout_rate"] == pytest.approx(5 / 12)
    assert greenhouse["p95_ms"] == 30000 and "Timeout rate" in greenhouse["reason"]
    assert rows["starter-adp"]["error_rate"] == pytest.approx(5 / 12)
    assert rows["starter-docusign"]["error_rate"] == pytest.approx(4 / 12)
    assert db.scalar(select(func.count()).select_from(Incident)) == 3
    events, at, *_ = normalize()
    counts = ingest(db, "brightline", events, now=at, allow_historical=True)
    assert counts["duplicates"] == 60 and counts["accepted"] == 0
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 60
    # The replay is a configuration profile, not a modification of production policy.
    assert DEFAULT_POLICY.min_requests == 20 and DEFAULT_POLICY.error_critical == 0.05


def test_rebase_preserves_offsets_ids_outcomes_and_current_evidence(db):
    at = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    exact, _, _, _ = normalize()
    rebased, end, _, _ = normalize(rebase_at=at)
    shift = datetime.fromisoformat(rebased[0]["timestamp"]) - datetime.fromisoformat(
        exact[0]["timestamp"]
    )
    for before, after in zip(exact, rebased, strict=True):
        assert {k: v for k, v in before.items() if k != "timestamp"} == {
            k: v for k, v in after.items() if k != "timestamp"
        }
        assert (
            datetime.fromisoformat(after["timestamp"])
            - datetime.fromisoformat(before["timestamp"])
            == shift
        )
    replay(db.get_bind(), rebase_at=at)
    integration = db.get(Integration, ("brightline", "starter-slack"))
    snapshot = db.scalar(
        select(Snapshot)
        .where(Snapshot.integration_id == integration.id)
        .order_by(Snapshot.bucket.desc())
    )
    telemetry = latest_telemetry(db, "brightline")[integration.id]
    assert (
        freshness(integration, snapshot, telemetry, now=end)["current_evidence_status"]
        == "HEALTHY"
    )
    stale = freshness(integration, snapshot, telemetry, now=end + timedelta(minutes=40))
    assert stale["current_evidence_status"] == "UNKNOWN"
    assert (
        SOURCE.read_bytes()
        and hashlib.sha256(SOURCE.read_bytes()).hexdigest() == DIGEST
    )


def test_exact_historical_replay_does_not_claim_current_health(db):
    replay(db.get_bind())
    integration = db.get(Integration, ("brightline", "starter-slack"))
    snapshot = db.scalar(
        select(Snapshot)
        .where(Snapshot.integration_id == integration.id)
        .order_by(Snapshot.bucket.desc())
    )
    state = freshness(
        integration,
        snapshot,
        latest_telemetry(db, "brightline")[integration.id],
        now=datetime(2026, 11, 9, tzinfo=timezone.utc),
    )
    assert (
        snapshot.status == "HEALTHY" and state["current_evidence_status"] == "UNKNOWN"
    )
    with pytest.raises(ValueError, match="empty disposable"):
        replay(db.get_bind())


def test_unknown_official_status_is_rejected(tmp_path):
    data = json.loads(SOURCE.read_text())
    data["logs"][0]["status"] = "pending"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Unsupported"):
        normalize(path)


def test_official_replay_cannot_run_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(SystemExit):
        main([])
