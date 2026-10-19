"""Product semantics and read-only incident navigation, not exact generated prose."""

from types import SimpleNamespace

import pytest
from app.ai.answer_design import driver, first_check, intent, pct
from app.models.entities import Integration
from app.schemas.assistant import AssistantQuestion
from tests.test_demo_access import connect
from tests.test_demo_access import demo as demo
from tests.test_monitoring_workflows import detail, disjoint_windows, headers, observe
from tests.test_operations_assistant import ask, fake_provider
from tests.test_operations_assistant import budgets as budgets


def traffic(client, request_window, integration, errors=0, latency=250, count=100):
    events = request_window(errors=errors, latency_ms=latency, count=count)
    for record in events:
        record["integration_id"] = integration
        record["request_id"] = integration + ":" + record["request_id"]
    result = client.post("/api/ingest", headers=headers(), json={"events": events})
    assert result.status_code == 200 and result.json()["accepted"] == count


def test_attention_rank_is_bounded_excludes_healthy_and_separates_evidence(
    client, db, monitoring_clock, request_window, monkeypatch
):
    for index in range(5):
        db.add(
            Integration(
                tenant_id="a",
                id=f"outage-{index}",
                name=f"Failure {index}",
                category="API",
                owner="Ops",
            )
        )
    db.add(
        Integration(
            tenant_id="a",
            id="healthy",
            name="Healthy Connection",
            category="API",
            owner="Ops",
        )
    )
    db.add(
        Integration(
            tenant_id="a",
            id="sparse",
            name="Sparse Connection",
            category="API",
            owner="Ops",
        )
    )
    db.commit()
    for _ in range(2):
        for index in range(5):
            traffic(client, request_window, f"outage-{index}", errors=90)
        traffic(client, request_window, "healthy")
        traffic(client, request_window, "sparse", count=2)
        assert client.post("/api/evaluate", headers=headers()).status_code == 200
        monitoring_clock.advance()
    fake_provider(monkeypatch)
    result = ask(client).json()
    assert result["availability"] == "LIVE"
    assert result["intent"] == "attention"
    assert len(result["priorities"]) == 3
    assert all(item["status"] == "UNHEALTHY" for item in result["priorities"])
    assert len(result["evidence"]) <= 4 and len(result["recommended_checks"]) <= 3
    assert "Healthy Connection" not in str(
        [
            result["answer"],
            result["priorities"],
            result["evidence"],
            result["additional_evidence"],
        ]
    )
    assert "evidence" in result["summary"] and "low-volume" in result["summary"]
    assert '{"HEALTHY"' not in result["answer"]
    assert all(item["next_check"] for item in result["priorities"])


@pytest.mark.parametrize(
    "code,metrics,streak,expected",
    [
        (
            "LATENCY_BASELINE_CRITICAL",
            {"error_rate": 0, "p95_ms": 4200, "baseline": {"p95_ms": 1000}},
            0,
            "latency",
        ),
        ("RECOVERY_PENDING", {"error_rate": 0, "p95_ms": 400}, 1, "1 of 2"),
        ("UNHEALTHY_RECOVERY_REQUIRED", {"error_rate": 0.02, "p95_ms": 400}, 0, "2%"),
        ("RECOVERY_MARGIN_NOT_MET", {"error_rate": 0, "p95_ms": 1400}, 0, "latency"),
    ],
)
def test_actual_health_driver_remains_explicit(code, metrics, streak, expected):
    snapshot = SimpleNamespace(
        status="UNHEALTHY",
        reason_code=code,
        bad_window_streak=3,
        degraded_window_streak=3,
        healthy_window_streak=streak,
        evidence={
            "metrics": metrics,
            "thresholds": {
                "healthy_recovery_windows": 2,
                "error_recovery": 0.005,
                "latency_target_ms": 1000,
                "latency_recovery_multiplier": 1.25,
            },
            "signal_reason_codes": ["LATENCY_BASELINE_CRITICAL"],
        },
    )
    explanation = driver(snapshot, {"current_evidence_status": "UNHEALTHY"})
    assert expected in explanation
    assert "Unhealthy" in explanation
    assert "0% → 0%" not in explanation
    assert first_check(snapshot, {"current_evidence_status": "UNHEALTHY"})


def test_changes_percentages_and_advanced_evidence(
    client, monitoring_clock, request_window, monkeypatch
):
    disjoint_windows(client)
    observe(client, request_window, errors=89)
    monitoring_clock.advance()
    observe(client, request_window, errors=100)
    fake_provider(monkeypatch)
    changed = ask(
        client,
        "What changed in the last hour?",
        scope="integration",
        integration_id="payroll",
    ).json()
    assert "89%" in changed["answer"] and "100%" in changed["answer"]
    assert (
        "fractions" not in changed["answer"] and "Overlapping" not in changed["answer"]
    )
    assert changed["intent"] == "changes"
    assert pct(0.89) == "89%"
    full = ask(
        client,
        "Show me the full evidence",
        scope="integration",
        integration_id="payroll",
    ).json()
    assert full["intent"] == "detail"
    assert full["additional_evidence"] and full["methodology"]
    assert len(full["evidence"]) <= 4
    assert len(full["additional_evidence"]) > len(changed["evidence"])


def test_stale_unknown_is_not_presented_as_healthy(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window)
    monitoring_clock.advance(minutes=45)
    fake_provider(monkeypatch)
    result = ask(client, "Which integrations have stale telemetry?").json()
    assert result["intent"] == "freshness"
    assert "Unknown" in result["answer"] and "stale" in result["answer"]
    assert result["confidence"] == "low"


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What needs attention?", "attention"),
        ("What should Ops investigate first?", "investigate"),
        ("Summarize this incident for escalation.", "escalation"),
        ("Has this recovered?", "recovery"),
        ("How was this calculated?", "detail"),
    ],
)
def test_question_shapes_are_intent_specific(question, expected):
    assert intent(AssistantQuestion(question=question)) == expected


def test_workspace_incident_collection_is_scoped_paged_and_reusable(
    client, db, monitoring_clock, request_window
):
    observe(client, request_window, tenant="a", errors=20)
    observe(client, request_window, tenant="b", errors=20)
    monitoring_clock.advance()
    observe(client, request_window, tenant="a", errors=20)
    observe(client, request_window, tenant="b", errors=20)
    assert client.get("/api/incidents").status_code == 401
    assert (
        client.get("/api/incidents?tenant_id=b", headers=headers()).status_code == 403
    )
    result = client.get("/api/incidents?limit=1", headers=headers()).json()
    assert result["total"] == 1 and len(result["items"]) == 1
    assert all(row["tenant_id"] == "a" for row in result["items"])
    original = detail(client)["incidents"][0]
    assert result["items"][0]["id"] == original["id"]
    assert result["items"][0]["recovery_condition"] == original["recovery_condition"]
    for _ in range(6):
        monitoring_clock.advance()
        observe(client, request_window)
    result = client.get("/api/incidents?state=RESOLVED", headers=headers("reader"))
    assert result.status_code == 200 and result.json()["total"] == 1
    assert result.json()["items"][0]["resolved_at"]
    assert (
        client.get("/api/incidents?state=OPEN", headers=headers()).json()["total"] == 0
    )
    assert client.get("/api/incidents?limit=501", headers=headers()).status_code == 422


def test_demo_incident_collection_cannot_cross_workspace(demo):
    connect(demo)
    assert demo.get("/api/incidents").status_code == 200
    assert demo.get("/api/incidents?tenant_id=b").status_code == 403


def test_current_driver_controls_first_check_even_when_other_signals_exist():
    from app.ai.incident_assistance import CHECKS

    snapshot = SimpleNamespace(
        reason_code="ERROR_RATE_CRITICAL",
        evidence={
            "signal_reason_codes": ["ERROR_RATE_CRITICAL", "LATENCY_TARGET_CRITICAL"],
            "metrics": {
                "top_error_categories": [
                    {"category": "upstream", "count": 90},
                    {"category": "auth", "count": 1},
                ]
            },
        },
    )
    assert (
        first_check(snapshot, {"current_evidence_status": "UNHEALTHY"})
        == CHECKS["upstream"]
    )
    snapshot.reason_code = "LATENCY_TARGET_CRITICAL"
    assert (
        first_check(snapshot, {"current_evidence_status": "UNHEALTHY"})
        == CHECKS["latency"]
    )


def test_priority_uses_observed_failure_and_measurements_not_alphabetical_order():
    from app.ai.answer_design import compose
    from app.schemas.assistant import EvidenceReference

    refs = [
        EvidenceReference(
            id="summary", label="Current operational priorities", value="3 unhealthy"
        )
    ]
    for key, error, observed in [
        ("a", 0, "HEALTHY"),
        ("z", 1, "UNHEALTHY"),
        ("b", 0.2, "UNHEALTHY"),
    ]:
        refs.append(
            EvidenceReference(
                id=key,
                label="Health decision",
                value=f"{key}: Unhealthy",
                integration_id=key,
                integration_name=key,
                health_status="UNHEALTHY",
                observed_status=observed,
                error_rate=error,
                active_incident=True,
            )
        )
    groups = {ref.id: "priority" if ref.id == "summary" else "decision" for ref in refs}
    result = compose(
        AssistantQuestion(question="What needs attention?"), refs, groups, [], []
    )
    assert [item.integration_id for item in result["priorities"]] == ["z", "b", "a"]


def test_unhealthy_history_is_not_labeled_an_eligible_baseline(
    client, monitoring_clock, request_window, monkeypatch
):

    observe(client, request_window, latency_ms=4000)
    monitoring_clock.advance()
    observe(client, request_window, latency_ms=4000)
    fake_provider(monkeypatch)
    result = ask(
        client,
        "Why is this integration unhealthy?",
        scope="integration",
        integration_id="payroll",
    ).json()
    latency_fact = next(
        ref
        for ref in result["evidence"] + result["additional_evidence"]
        if ref["label"] == "Latency and baseline"
    )
    assert "healthy baseline unavailable" in latency_fact["value"]
    assert "latency" in result["answer"] and "4 s" in result["answer"]
