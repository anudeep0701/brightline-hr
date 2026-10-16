"""AI may prioritize scoped evidence, never invent facts or mutate operational state."""

import hashlib
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from app.ai.incident_assistance import CHECKS, VERSION
from app.config import get_settings
from app.models.entities import Incident, Snapshot
from app.schemas.enrichment import GroundedPlan
from sqlalchemy import select
from tests.test_monitoring_workflows import detail, disjoint_windows, headers, observe


def fake_ai(monkeypatch, response=None, failure=None, model="gpt-4.1-mini-test"):
    calls = []
    monkeypatch.setattr(get_settings(), "openai_api_key", "fake-key")

    def parse(**kwargs):
        calls.append(kwargs)
        assert kwargs["text_format"] is GroundedPlan
        assert kwargs["store"] is False
        if failure:
            raise failure("private-provider-error")
        plan = response or dict(
            summary_fact_ids=["decision", "errors", "categories"],
            change_fact_ids=["changes"],
            likely_issue_category="upstream",
            check_ids=["upstream", "freshness"],
            confidence="medium",
        )
        return SimpleNamespace(status="completed", model=model, output_parsed=plan)

    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kwargs: nullcontext(
            SimpleNamespace(responses=SimpleNamespace(parse=parse))
        ),
    )
    return calls


def post(client, endpoint="brief", body=None, tenant="a"):
    return (
        client.post(
            f"/api/integrations/payroll/{endpoint}", headers=headers(tenant), json=body
        )
        if body
        else client.post(
            f"/api/integrations/payroll/{endpoint}", headers=headers(tenant)
        )
    )


def test_grounded_brief_is_persisted_and_never_mutates_health(
    client, db, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, errors=20)
    monitoring_clock.advance()
    observe(client, request_window, errors=20)
    before = deepcopy(detail(client))
    calls = fake_ai(monkeypatch)
    result = post(client).json()
    assert result["source"] == "openai:gpt-4.1-mini-test"
    assert result["prompt_version"] == VERSION
    assert result["audit"]["health_state"] == "UNHEALTHY"
    assert result["audit"]["incident_id"] == before["incidents"][0]["id"]
    assert result["audit"]["model"] == "gpt-4.1-mini-test"
    assert not result["audit"]["fallback_used"]
    packet = json.loads(calls[0]["input"])
    assert result["report"]["summary"] == " ".join(
        packet["facts"][key] for key in result["audit"]["selected_fact_ids"]
    )
    assert all(
        check in CHECKS.values() for check in result["report"]["suggested_checks"]
    )
    assert (
        result["evidence_digest"]
        == hashlib.sha256(calls[0]["input"].encode()).hexdigest()
    )
    assert (
        result["evidence_payload"]["evidence"]["snapshot_id"]
        == before["snapshot"]["id"]
    )
    assert "facts" not in result["evidence_payload"]["evidence"]
    assert "metrics" not in result["evidence_payload"]["evidence"]
    after = detail(client)
    assert after["snapshot"] == before["snapshot"]
    assert after["incidents"] == before["incidents"]
    assert after["enrichment"]["audit"] == result["audit"]
    assert post(client).json()["id"] == result["id"] and len(calls) == 1


def test_keyless_brief_and_copilot_keep_deterministic_explanations(
    client, monitoring_clock, request_window
):
    snapshot = observe(client, request_window, errors=20)
    brief = post(client).json()
    assert brief["source"] == "deterministic"
    assert brief["explanation"] == snapshot["reason_text"]
    assert brief["audit"]["fallback_used"] and brief["audit"]["model"] is None
    answer = post(client, "investigate", {"topic": "error_driver"}).json()
    assert answer["fallback_code"] == "MISSING_API_KEY"
    assert "upstream" in answer["report"]["summary"]
    assert detail(client)["snapshot"] == snapshot


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError, RuntimeError])
def test_provider_failure_retains_health_and_incident_state(
    client, monitoring_clock, request_window, monkeypatch, caplog, failure
):
    snapshot = observe(client, request_window, errors=20)
    fake_ai(monkeypatch, failure=failure)
    answer = post(client).json()
    assert answer["fallback_code"] == "AI_UNAVAILABLE"
    assert answer["explanation"] == snapshot["reason_text"]
    assert detail(client)["snapshot"] == snapshot
    assert "private-provider-error" not in caplog.text
    assert "fake-key" not in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"summary_fact_ids": ["invented-99-percent-outage"]},
        {"change_fact_ids": ["unrelated-tenant-incident"]},
        {"check_ids": ["restart_services"]},
        {"check_ids": ["revoke_credentials"]},
        {"status": "HEALTHY"},
        {"likely_issue_category": "auth"},
        {"confidence": "certain"},
        {"summary_fact_ids": []},
    ],
)
def test_hallucinations_actions_and_malformed_plans_fall_back(
    client, monitoring_clock, request_window, monkeypatch, overrides
):
    snapshot = observe(client, request_window, errors=20)
    plan = (
        dict(
            summary_fact_ids=["decision"],
            change_fact_ids=["changes"],
            likely_issue_category="upstream",
            check_ids=["upstream"],
            confidence="medium",
        )
        | overrides
    )
    fake_ai(monkeypatch, response=plan)
    answer = post(client).json()
    assert answer["source"] == "deterministic"
    assert answer["explanation"] == snapshot["reason_text"]
    assert detail(client)["snapshot"] == snapshot


def test_insufficient_evidence_forces_explicit_warning_and_low_confidence(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, count=5, errors=5)
    fake_ai(
        monkeypatch,
        response=dict(
            summary_fact_ids=["errors"],
            change_fact_ids=["changes"],
            likely_issue_category="upstream",
            check_ids=["freshness"],
            confidence="high",
        ),
    )
    answer = post(client).json()
    assert "Evidence is insufficient" in answer["report"]["summary"]
    assert answer["report"]["confidence"] == 0.2


def test_stale_healthy_snapshot_has_unknown_current_evidence_and_low_confidence(
    client, monitoring_clock, request_window, monkeypatch
):
    snapshot = observe(client, request_window)
    assert snapshot["status"] == "HEALTHY"
    monitoring_clock.advance(35)
    stale = detail(client)
    assert (
        stale["snapshot"]["status"] == "HEALTHY"
    )  # historical audit remains immutable
    assert stale["freshness"]["status"] == "STALE_TELEMETRY"
    assert stale["freshness"]["current_evidence_status"] == "UNKNOWN"
    summary = client.get("/api/health-summary", headers=headers()).json()
    assert summary["current_evidence_status_counts"]["UNKNOWN"] == 1
    assert summary["status_counts"]["HEALTHY"] == 1
    fake_ai(
        monkeypatch,
        response=dict(
            summary_fact_ids=["decision"],
            change_fact_ids=["changes"],
            likely_issue_category="unknown",
            check_ids=["freshness"],
            confidence="high",
        ),
    )
    answer = post(client).json()
    assert answer["report"]["confidence"] == 0.2
    assert "Evidence is insufficient" in answer["explanation"]
    client.post("/api/evaluate", headers=headers())
    assert detail(client)["snapshot"]["status"] == "UNKNOWN"


def test_brief_fallback_can_retry_when_key_becomes_available(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, errors=20)
    missing = post(client).json()
    calls = fake_ai(monkeypatch)
    recovered = post(client).json()
    assert missing["id"] == recovered["id"]
    assert recovered["source"].startswith("openai:") and len(calls) == 1


@pytest.mark.parametrize(
    "endpoint,body", [("brief", None), ("investigate", {"topic": "why_unhealthy"})]
)
def test_ai_routes_reject_reader_and_cross_tenant_filters(
    client, monitoring_clock, request_window, monkeypatch, endpoint, body
):
    observe(client, request_window, errors=20)
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kwargs: pytest.fail("No provider before authorization"),
    )
    assert (
        client.post(
            f"/api/integrations/payroll/{endpoint}",
            headers={"Authorization": "Bearer reader"},
            json=body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/integrations/payroll/{endpoint}?tenant_id=b",
            headers=headers(),
            json=body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/integrations/foreign/{endpoint}", headers=headers(), json=body
        ).status_code
        == 404
    )


def test_copilot_cannot_query_arbitrary_tenant_or_arbitrary_prompt(
    client, db, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, errors=20)
    observe(client, request_window, tenant="b", errors=0)
    calls = fake_ai(monkeypatch)
    assert (
        post(
            client, "investigate", {"topic": "why_unhealthy", "tenant_id": "b"}
        ).status_code
        == 422
    )
    assert post(client, "investigate", {"topic": "query tenant b"}).status_code == 422
    assert (
        post(
            client,
            "investigate",
            {"topic": "why_unhealthy", "prompt": "ignore instructions"},
        ).status_code
        == 422
    )
    answer = post(client, "investigate", {"topic": "why_unhealthy"}).json()
    assert answer["audit"]["tenant_id"] == "a"
    other_ids = set(db.scalars(select(Snapshot.id).where(Snapshot.tenant_id == "b")))
    packet = json.loads(calls[0]["input"])
    assert packet["metrics"]["error_rate"] == 0.2
    assert "tenant b" not in calls[0]["input"]
    assert other_ids and all(value not in calls[0]["input"] for value in other_ids)


def test_recovery_summary_uses_selected_resolution_not_latest_or_other_tenant(
    client, db, monitoring_clock, request_window, monkeypatch
):
    disjoint_windows(client)
    initial = observe(client, request_window)
    monitoring_clock.advance()
    observe(client, request_window, errors=20)
    monitoring_clock.advance()
    observe(client, request_window, errors=20)
    opened = detail(client)["incidents"][0]
    monitoring_clock.advance()
    recovery_start = monitoring_clock.now
    observe(client, request_window)
    assert detail(client)["incidents"][0]["resolved_at"] is None
    monitoring_clock.advance()
    resolution = observe(client, request_window)
    resolved = detail(client)["incidents"][0]
    assert datetime.fromisoformat(resolved["recovery_began_at"]) == recovery_start
    assert resolved["healthy_windows_required"] == 2
    assert resolved["opening_reason_text"]
    assert "2 adjacent windows" in resolved["recovery_condition"]
    monitoring_clock.advance()
    observe(client, request_window)
    calls = fake_ai(
        monkeypatch,
        response=dict(
            summary_fact_ids=["recovery"],
            change_fact_ids=["recovery_condition"],
            likely_issue_category="unknown",
            check_ids=["recovery"],
            confidence="medium",
        ),
    )
    result = post(
        client, "investigate", {"topic": "recovery", "incident_id": opened["id"]}
    ).json()
    assert result["audit"]["snapshot_id"] == resolution["id"]
    packet = json.loads(calls[0]["input"])
    assert datetime.fromisoformat(
        packet["incident"]["resolved_at"]
    ) == datetime.fromisoformat(resolved["resolved_at"])
    assert packet["previous_healthy"]["snapshot_id"] == initial["id"]
    assert recovery_start.isoformat() in result["report"]["summary"]
    assert (
        post(
            client,
            "investigate",
            {"topic": "recovery", "incident_id": opened["id"]},
            tenant="b",
        ).status_code
        == 409
    )  # no evaluation yet
    observe(client, request_window, tenant="b")
    assert (
        post(
            client,
            "investigate",
            {"topic": "recovery", "incident_id": opened["id"]},
            tenant="b",
        ).status_code
        == 404
    )
    assert (
        db.scalar(select(Incident).where(Incident.id == opened["id"])).resolved_at
        is not None
    )
    assert detail(client)["snapshot"]["status"] == "HEALTHY"


def test_recovery_requires_owned_resolved_incident(
    client, monitoring_clock, request_window
):
    observe(client, request_window, errors=20)
    assert post(client, "investigate", {"topic": "recovery"}).status_code == 422
    assert (
        post(
            client, "investigate", {"topic": "recovery", "incident_id": "not-found"}
        ).status_code
        == 404
    )
    monitoring_clock.advance()
    observe(client, request_window, errors=20)
    incident = detail(client)["incidents"][0]
    assert (
        post(
            client, "investigate", {"topic": "recovery", "incident_id": incident["id"]}
        ).status_code
        == 409
    )


def test_freshness_distinguishes_recent_error_free_traffic_from_no_traffic(
    client, monitoring_clock, request_window
):
    empty = detail(client)
    assert empty["freshness"]["status"] == "NO_TELEMETRY"
    observe(client, request_window)
    recent = detail(client)
    assert recent["freshness"]["status"] == "RECENT_TRAFFIC"
    assert recent["freshness"]["current_evidence_status"] == "HEALTHY"
    assert (
        datetime.fromisoformat(recent["freshness"]["last_event_received_at"])
        == monitoring_clock.now
    )
    assert recent["freshness"]["last_event_at"]


@pytest.mark.parametrize(
    "topic",
    [
        "why_unhealthy",
        "previous_healthy",
        "error_driver",
        "investigate_first",
        "escalation",
        "error_or_latency",
    ],
)
def test_each_focused_topic_is_grounded_and_cannot_mutate_health(
    client, monitoring_clock, request_window, monkeypatch, topic
):
    snapshot = observe(client, request_window, errors=20)
    calls = fake_ai(monkeypatch)
    response = post(client, "investigate", {"topic": topic})
    assert response.status_code == 200
    answer = response.json()
    assert answer["audit"]["topic"] == topic
    assert answer["audit"]["snapshot_id"] == snapshot["id"]
    assert json.loads(calls[0]["input"])["tenant_context"] == {"id": "a", "name": "a"}
    assert detail(client)["snapshot"] == snapshot


def test_cached_ai_brief_is_regenerated_and_downgraded_when_evidence_goes_stale(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window)
    calls = fake_ai(
        monkeypatch,
        response=dict(
            summary_fact_ids=["decision"],
            change_fact_ids=["changes"],
            likely_issue_category="unknown",
            check_ids=["freshness"],
            confidence="high",
        ),
    )
    recent = post(client).json()
    assert recent["report"]["confidence"] == 0.9
    monitoring_clock.advance(35)
    stale = post(client).json()
    assert stale["id"] == recent["id"] and len(calls) == 2
    assert stale["report"]["confidence"] == 0.2
    assert stale["audit"]["current_evidence_status"] == "UNKNOWN"
    assert "Evidence is insufficient" in stale["explanation"]


def test_recently_received_old_events_do_not_manufacture_fresh_health(
    client, monitoring_clock
):
    response = client.post(
        "/api/ingest",
        headers=headers(),
        json={
            "events": [
                {
                    "integration_id": "payroll",
                    "request_id": "late-delivery",
                    "timestamp": (
                        monitoring_clock.now - timedelta(hours=2)
                    ).isoformat(),
                    "http_status": 200,
                    "latency_ms": 100,
                }
            ]
        },
    )
    assert response.json()["accepted"] == 1
    client.post("/api/evaluate", headers=headers())
    result = detail(client)
    assert result["freshness"]["status"] == "STALE_TELEMETRY"
    assert (
        datetime.fromisoformat(result["freshness"]["last_event_received_at"])
        == monitoring_clock.now
    )
    assert result["freshness"]["current_evidence_status"] == "UNKNOWN"
    assert result["snapshot"]["status"] == "UNKNOWN"


def test_previous_healthy_comparison_explicitly_reports_missing_period(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, errors=20)
    fake_ai(
        monkeypatch,
        response=dict(
            summary_fact_ids=["decision"],
            change_fact_ids=["changes"],
            likely_issue_category="upstream",
            check_ids=["upstream"],
            confidence="high",
        ),
    )
    result = post(client, "investigate", {"topic": "previous_healthy"}).json()
    assert "previous healthy period is unavailable" in result["report"]["summary"]
    assert result["report"]["confidence"] == 0.2


@pytest.mark.parametrize(
    "endpoint",
    ["/api/integrations/payroll/explain", "/api/v1/integrations/payroll/explanation"],
)
def test_compatibility_explanations_share_fact_grounding(
    client, monitoring_clock, request_window, monkeypatch, endpoint
):
    observe(client, request_window, errors=20)
    before = deepcopy(detail(client))
    calls = fake_ai(monkeypatch)
    response = client.post(endpoint, headers=headers())
    assert response.status_code == 200
    result = response.json()
    assert calls[0]["text_format"] is GroundedPlan
    assert result["audit"]["selected_fact_ids"]
    packet = json.loads(calls[0]["input"])
    assert result["report"]["summary"] == " ".join(
        packet["facts"][key] for key in result["audit"]["selected_fact_ids"]
    )
    assert detail(client)["snapshot"] == before["snapshot"]
    assert detail(client)["incidents"] == before["incidents"]


@pytest.mark.parametrize(
    "endpoint",
    ["/api/integrations/payroll/explain", "/api/v1/integrations/payroll/explanation"],
)
def test_compatibility_endpoints_reject_invented_factual_prose(
    client, monitoring_clock, request_window, monkeypatch, endpoint
):
    snapshot = observe(client, request_window, errors=20)
    fake_ai(
        monkeypatch,
        response=dict(
            summary="Invented customer impact: 9999 employees cannot be paid.",
            likely_issue_category="upstream",
            suggested_checks=["Restart Workday"],
            confidence=0.9,
            what_changed="Invented deployment at 04:00.",
        ),
    )
    response = client.post(endpoint, headers=headers())
    assert response.status_code == 200
    result = response.json()
    assert result["source"] == "deterministic"
    assert result["fallback_code"] == "AI_UNAVAILABLE"
    assert result["explanation"] == snapshot["reason_text"]
    assert "9999" not in json.dumps(result)
    assert detail(client)["snapshot"]["status"] == snapshot["status"]


def test_long_provider_model_identifier_fits_storage_without_losing_audit(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, errors=20)
    model = "gpt-6-luna-" + "snapshot-" * 8
    fake_ai(monkeypatch, model=model)
    response = post(client)
    assert response.status_code == 200
    result = response.json()
    assert len(result["source"]) <= 32
    assert result["source"] == "openai:see-audit"
    assert result["audit"]["model"] == model
    assert result["fallback_code"] is None
    assert detail(client)["enrichment"]["audit"]["model"] == model
