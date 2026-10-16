"""Offline tests: never construct a real provider client or use real credentials."""

import hashlib
import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.ai.enrichment import PROMPT_VERSION, explain
from app.ai.evidence import build_evidence
from app.config import Settings
from app.health.service import bucket_for, refresh
from app.models.entities import Incident, RequestLog, Snapshot
from app.schemas.enrichment import EnrichmentReport
from sqlalchemy import select


def snapshot_at(db, at, tenant="a"):
    refresh(db, tenant, at)
    return db.scalar(
        select(Snapshot).where(
            Snapshot.tenant_id == tenant,
            Snapshot.bucket == at,
        )
    )


def mock_client(monkeypatch, parse):
    def construct(**kwargs):
        assert kwargs == dict(api_key="fake-test-key", timeout=8, max_retries=0)
        return nullcontext(SimpleNamespace(responses=SimpleNamespace(parse=parse)))

    monkeypatch.setattr("app.ai.enrichment.OpenAI", construct)


def report(**overrides):
    return (
        dict(
            summary="No telemetry is available for this window.",
            likely_issue_category="insufficient_evidence",
            suggested_checks=["Inspect telemetry freshness."],
            confidence=0.1,
            what_changed="No earlier snapshot is available for comparison.",
        )
        | overrides
    )


def test_missing_key_exact_fallback_and_audit_cache(db, monkeypatch):
    snapshot = snapshot_at(db, bucket_for(datetime.now(timezone.utc)))
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI", lambda **kw: pytest.fail("No client without a key")
    )
    result = explain(db, snapshot, Settings())
    assert result.explanation == snapshot.reason_text == result.report["summary"]
    assert result.fallback_code == "MISSING_API_KEY"
    assert result.prompt_version == PROMPT_VERSION
    assert result.report["confidence"] == 0
    assert (
        result.evidence_digest
        == hashlib.sha256(
            json.dumps(
                result.evidence_payload,
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )
    assert explain(db, snapshot, Settings()).id == result.id


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError, RuntimeError])
def test_provider_failures_do_not_leak_or_mutate(db, monkeypatch, caplog, failure):
    snapshot = snapshot_at(db, bucket_for(datetime.now(timezone.utc)))
    before = json.dumps(snapshot.evidence, sort_keys=True)

    def parse(**kwargs):
        raise failure("secret-provider-detail")

    mock_client(monkeypatch, parse)
    result = explain(db, snapshot, Settings(openai_api_key="fake-test-key"))
    assert result.explanation == snapshot.reason_text
    assert result.source == "deterministic" and result.fallback_code == "AI_UNAVAILABLE"
    assert "secret-provider-detail" not in caplog.text
    assert "fake-test-key" not in caplog.text
    assert json.dumps(snapshot.evidence, sort_keys=True) == before
    assert snapshot.status == "UNKNOWN"


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": float("nan")},
        {"confidence": 1.1},
        {"summary": ""},
        {"status": "HEALTHY"},
        {"likely_issue_category": "auth"},
        {"suggested_checks": ["x"] * 6},
        {"suggested_checks": ["x" * 301]},
    ],
)
def test_invalid_or_ungrounded_output_falls_back(db, monkeypatch, overrides):
    snapshot = snapshot_at(db, bucket_for(datetime.now(timezone.utc)))
    mock_client(
        monkeypatch, lambda **kw: SimpleNamespace(output_parsed=report(**overrides))
    )
    result = explain(db, snapshot, Settings(openai_api_key="fake-test-key"))
    assert result.source == "deterministic"
    assert result.explanation == snapshot.reason_text


def test_known_aggregate_evidence_only_and_success_cache(db, monkeypatch):
    at = bucket_for(datetime.now(timezone.utc))
    db.add(
        RequestLog(
            tenant_id="a",
            integration_id="payroll",
            event_id="private-request-id",
            occurred_at=at - timedelta(seconds=30),
            status_code=401,
            latency_ms=80,
            timed_out=False,
            error_category="auth",
            error_message="private-email@example.com",
            raw_event={"authorization": "secret-raw-log"},
        )
    )
    db.commit()
    snapshot = snapshot_at(db, at)
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        assert kwargs["store"] is False and kwargs["max_output_tokens"] == 1000
        assert kwargs["text_format"] is EnrichmentReport
        payload = json.loads(kwargs["input"])
        assert payload["metrics"]["error_rate"] == 1
        assert payload["consecutive_bad_windows"] == 0
        assert payload["baseline"] is not None
        assert "auth" in payload["allowed_issue_categories"]
        for private in (
            "private-request-id",
            "private-email",
            "secret-raw-log",
            "tenant_id",
            "fake-test-key",
        ):
            assert private not in kwargs["input"]
        return SimpleNamespace(
            output_parsed=EnrichmentReport(
                **report(
                    summary="One authentication failure was observed; traffic is insufficient.",
                    likely_issue_category="auth",
                )
            )
        )

    mock_client(monkeypatch, parse)
    result = explain(db, snapshot, Settings(openai_api_key="fake-test-key"))
    assert result.source == "openai:gpt-6-luna" and result.fallback_code is None
    assert result.report["likely_issue_category"] == "auth"
    assert (
        explain(db, snapshot, Settings(openai_api_key="fake-test-key")).id == result.id
    )
    assert len(calls) == 1
    assert snapshot.status == "UNKNOWN"


def test_previous_snapshot_and_incident_are_tenant_scoped_and_as_of(db):
    at = bucket_for(datetime.now(timezone.utc)) - timedelta(hours=1)
    prior = snapshot_at(db, at)
    other = snapshot_at(db, at + timedelta(minutes=5), "b")
    current = snapshot_at(db, at + timedelta(minutes=10))
    future = snapshot_at(db, at + timedelta(minutes=15))
    db.add_all(
        [
            Incident(
                tenant_id="a",
                integration_id="payroll",
                opening_snapshot_id=prior.id,
                last_snapshot_id=current.id,
                opened_at=at,
                resolved_at=current.bucket,
            ),
            Incident(
                tenant_id="b",
                integration_id="payroll",
                opening_snapshot_id=other.id,
                last_snapshot_id=other.id,
                opened_at=other.bucket,
            ),
            Incident(
                tenant_id="a",
                integration_id="payroll",
                opening_snapshot_id=future.id,
                last_snapshot_id=future.id,
                opened_at=future.bucket,
            ),
        ]
    )
    db.commit()
    evidence = build_evidence(db, current)
    assert evidence["changes"]["previous_snapshot_id"] == prior.id
    assert evidence["incident_start_time"] == at.isoformat()
    assert evidence["changes"]["deltas"] == dict(
        request_count=0, error_rate=None, timeout_rate=None, p95_ms=None
    )
    assert build_evidence(db, prior)["changes"] is None


def test_deterministic_changes_are_numeric_and_null_safe(db):
    at = bucket_for(datetime.now(timezone.utc))
    prior = snapshot_at(db, at)
    db.add(
        RequestLog(
            tenant_id="a",
            integration_id="payroll",
            event_id="new",
            occurred_at=at + timedelta(minutes=1),
            status_code=200,
            latency_ms=120,
            timed_out=False,
            error_category="none",
        )
    )
    db.commit()
    current = snapshot_at(db, at + timedelta(minutes=5))
    result = explain(db, current, Settings())
    assert result.evidence_payload["changes"]["previous_snapshot_id"] == prior.id
    assert result.evidence_payload["changes"]["deltas"]["request_count"] == 1
    assert "Request count changed by +1.00" in result.report["what_changed"]
    assert "p95 latency changed" not in result.report["what_changed"]


def test_legacy_record_is_regenerated(db):
    from app.models.entities import Enrichment

    snapshot = snapshot_at(db, bucket_for(datetime.now(timezone.utc)))
    legacy = Enrichment(
        tenant_id="a",
        integration_id="payroll",
        snapshot_id=snapshot.id,
        generated_at=snapshot.evaluated_at,
        source="deterministic",
        explanation="legacy",
        evidence_digest="old",
        prompt_version="legacy-v1",
    )
    db.add(legacy)
    db.commit()
    result = explain(db, snapshot, Settings())
    assert result.id == legacy.id and result.prompt_version == PROMPT_VERSION
    assert result.explanation == snapshot.reason_text


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_noncompleted_response_falls_back_even_if_parsed(db, monkeypatch, status):
    snapshot = snapshot_at(db, bucket_for(datetime.now(timezone.utc)))
    mock_client(
        monkeypatch,
        lambda **kw: SimpleNamespace(
            status=status,
            output_parsed=EnrichmentReport(**report()),
        ),
    )
    result = explain(db, snapshot, Settings(openai_api_key="fake-test-key"))
    assert result.source == "deterministic"
    assert result.explanation == snapshot.reason_text
