"""Business acceptance tests through HTTP, validation, storage, policy and incidents.

Only time and the optional AI boundary are faked. Metrics and health evaluation run
against the real database-backed services. Request windows use a fixed NumPy seed.
"""

from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.config import get_settings
from app.models.entities import MetricRollup, RequestEvent, Snapshot
from app.schemas.enrichment import EnrichmentReport
from sqlalchemy import func, select


def headers(tenant="a"):
    return {"Authorization": f"Bearer {tenant}"}


def ingest(client, events, tenant="a"):
    response = client.post(
        "/api/ingest", headers=headers(tenant), json={"events": events}
    )
    assert response.status_code == 200, response.text
    return response.json()


def evaluate(client, tenant="a"):
    response = client.post("/api/evaluate", headers=headers(tenant))
    assert response.status_code == 200, response.text
    return response.json()


def detail(client, tenant="a"):
    response = client.get("/api/integrations/payroll", headers=headers(tenant))
    assert response.status_code == 200, response.text
    return response.json()


def observe(client, request_window, *, tenant="a", **traffic):
    events = request_window(tenant=tenant, **traffic)
    result = ingest(client, events, tenant)
    assert (
        result["accepted"] == len(events)
        and result["rejected"] == result["duplicates"] == 0
    )
    assert evaluate(client, tenant)["created"] == 1
    return detail(client, tenant)["snapshot"]


def disjoint_windows(client):
    """Isolate hysteresis from the separate 15-minute rolling washout behavior."""
    url = "/api/v1/integrations/payroll/config"
    policy = client.get(url, headers=headers()).json()
    response = client.put(
        url, headers=headers(), json=dict(policy, evaluation_window_minutes=5)
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "count,errors,status,reason",
    [
        pytest.param(100, 0, "HEALTHY", "WITHIN_POLICY", id="healthy-requests"),
        pytest.param(100, 2, "DEGRADED", "ERROR_RATE_ELEVATED", id="moderate-errors"),
        pytest.param(
            5, 5, "UNKNOWN", "INSUFFICIENT_REQUESTS", id="low-traffic-even-if-all-fail"
        ),
    ],
)
def test_ingested_traffic_produces_explainable_health(
    client, db, monitoring_clock, request_window, count, errors, status, reason
):
    snapshot = observe(client, request_window, count=count, errors=errors)
    assert snapshot["status"] == status and snapshot["reason_code"] == reason
    assert snapshot["metrics"]["request_count"] == count
    assert snapshot["metrics"]["error_count"] == errors
    assert snapshot["metrics"]["error_rate"] == pytest.approx(errors / count)
    assert snapshot["evidence_sufficient"] is (count >= 20)
    assert snapshot["reason_text"]
    assert snapshot["evaluated_at"] == monitoring_clock.now.isoformat().replace(
        "+00:00", "Z"
    )
    summary = client.get("/api/health-summary", headers=headers()).json()
    assert summary["status_counts"][status] == 1 and summary["open_incidents"] == 0
    history = client.get("/api/integrations/payroll/metrics", headers=headers()).json()
    assert history["items"][0]["metrics"]["error_count"] == errors
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == count


@pytest.mark.parametrize(
    "errors,latency,signal",
    [
        pytest.param(
            20, 250, "ERROR_RATE_CRITICAL", id="sustained-errors-with-fast-responses"
        ),
        pytest.param(
            0, 4000, "LATENCY_TARGET_CRITICAL", id="latency-outage-with-no-errors"
        ),
    ],
)
def test_two_bad_windows_confirm_one_incident_without_double_counting(
    client, db, monitoring_clock, request_window, errors, latency, signal
):
    first = observe(client, request_window, errors=errors, latency_ms=latency)
    assert first["status"] == "DEGRADED" and first["observed_status"] == "UNHEALTHY"
    assert first["reason_code"] == "UNHEALTHY_CONFIRMATION_PENDING"
    assert detail(client)["incidents"] == []
    # Repeating a bucket is not a second observation and cannot confirm an incident.
    assert evaluate(client)["created"] == 0
    assert detail(client)["snapshot"]["bad_window_streak"] == 1
    monitoring_clock.advance()
    confirmed = observe(client, request_window, errors=errors, latency_ms=latency)
    assert confirmed["status"] == "UNHEALTHY" and confirmed["bad_window_streak"] == 2
    assert signal in confirmed["evidence"]["signal_reason_codes"]
    assert confirmed["metrics"]["error_rate"] == pytest.approx(errors / 100)
    incident = detail(client)["incidents"][0]
    assert (
        incident["opening_snapshot_id"] == confirmed["id"]
        and incident["resolved_at"] is None
    )
    assert evaluate(client)["created"] == 0
    assert detail(client)["incidents"] == [incident]
    assert db.scalar(select(func.count()).select_from(Snapshot)) == 2
    assert db.scalar(select(func.count()).select_from(MetricRollup)) == 2


def test_brief_error_and_latency_spike_is_visible_without_persistent_incident(
    client, db, monitoring_clock, request_window
):
    states = [observe(client, request_window)["status"]]
    monitoring_clock.advance()
    spike = request_window(errors=1)
    failed = next(row for row in spike if row["http_status"] == 503)
    failed["latency_ms"] = 6000
    assert ingest(client, spike)["accepted"] == 100
    evaluate(client)
    current = detail(client)
    states.append(current["snapshot"]["status"])
    assert current["snapshot"]["metrics"]["error_count"] == 1
    assert current["snapshot"]["metrics"]["p99_ms"] == 250
    # The outlier is retained in raw request metadata, even though P95 and policy stay healthy.
    stored_spike = db.get(RequestEvent, ("a", failed["request_id"]))
    assert stored_spike.status_code == 503 and stored_spike.latency_ms == 6000
    for _ in range(3):
        monitoring_clock.advance()
        states.append(observe(client, request_window)["status"])
    assert states == ["HEALTHY"] * 5
    assert detail(client)["snapshot"]["metrics"]["error_count"] == 0
    assert detail(client)["incidents"] == []


def test_borderline_window_resets_recovery_and_two_clean_windows_resolve_once(
    client, monitoring_clock, request_window
):
    disjoint_windows(client)
    observe(client, request_window, errors=20)
    monitoring_clock.advance()
    observe(client, request_window, errors=20)
    opened = detail(client)["incidents"][0]
    # A single good observation must not resolve the confirmed incident.
    monitoring_clock.advance()
    first_clean = observe(client, request_window)
    assert (
        first_clean["status"] == "UNHEALTHY"
        and first_clean["healthy_window_streak"] == 1
    )
    assert first_clean["reason_code"] == "RECOVERY_PENDING"
    assert evaluate(client)["created"] == 0
    assert detail(client)["incidents"][0]["recovery_streak"] == 1
    # 0.7% is below warning (1%) but above the stricter recovery margin (0.5%).
    monitoring_clock.advance()
    borderline = observe(client, request_window, count=1000, errors=7)
    assert (
        borderline["observed_status"] == "HEALTHY"
        and borderline["status"] == "UNHEALTHY"
    )
    assert borderline["reason_code"] == "RECOVERY_MARGIN_NOT_MET"
    assert borderline["healthy_window_streak"] == 0
    assert detail(client)["incidents"][0]["resolved_at"] is None
    for expected in ("UNHEALTHY", "HEALTHY"):
        monitoring_clock.advance()
        assert observe(client, request_window)["status"] == expected
    resolved = detail(client)["incidents"]
    assert len(resolved) == 1 and resolved[0]["id"] == opened["id"]
    assert resolved[0]["resolved_at"] == monitoring_clock.now.isoformat().replace(
        "+00:00", "Z"
    )
    assert (
        client.get("/api/health-summary", headers=headers()).json()["open_incidents"]
        == 0
    )
    assert evaluate(client)["created"] == 0
    assert detail(client)["incidents"] == resolved


def test_malformed_records_and_conflicting_retries_cannot_corrupt_metrics(
    client, db, monitoring_clock, request_window
):
    good = request_window(count=20)
    conflicting = dict(good[0], http_status=503, latency_ms=6000)
    malformed = dict(good[0], request_id="bad", latency_ms="PRIVATE_INVALID_VALUE")
    foreign = dict(good[0], request_id="foreign", tenant_id="b")
    future = dict(
        good[0],
        request_id="future",
        timestamp=(monitoring_clock.now + timedelta(seconds=1)).isoformat(),
    )
    unknown = dict(good[0], request_id="unknown", integration_id="does-not-exist")
    batch = [good[0], malformed, *good[1:], conflicting, foreign, future, unknown]
    first = ingest(client, batch)
    assert (first["accepted"], first["rejected"], first["duplicates"]) == (20, 4, 1)
    assert "PRIVATE_INVALID_VALUE" not in str(first)
    second = ingest(client, batch)
    assert (second["accepted"], second["rejected"], second["duplicates"]) == (0, 4, 21)
    assert db.scalar(select(func.count()).select_from(RequestEvent)) == 20
    original = db.get(RequestEvent, ("a", good[0]["request_id"]))
    assert original.status_code == 200 and original.latency_ms == 250
    evaluate(client)
    snapshot = detail(client)["snapshot"]
    assert snapshot["status"] == "HEALTHY" and snapshot["metrics"]["error_count"] == 0
    assert (
        snapshot["metrics"]["request_count"] == 20
        and snapshot["metrics"]["p95_ms"] == 250
    )


def test_ai_outage_does_not_block_monitoring_or_incident_recovery(
    client, monitoring_clock, request_window, monkeypatch
):
    disjoint_windows(client)
    calls = []

    def offline(**kwargs):
        calls.append(True)
        raise TimeoutError("provider unavailable")

    monkeypatch.setattr(get_settings(), "openai_api_key", "fake-test-key")
    monkeypatch.setattr("app.ai.enrichment.OpenAI", offline)
    for _ in range(2):
        observe(client, request_window, errors=30)
        monitoring_clock.advance()
    before = detail(client)
    fallback = client.post("/api/integrations/payroll/explain", headers=headers())
    assert fallback.status_code == 200 and fallback.json()["source"] == "deterministic"
    assert fallback.json()["explanation"] == before["snapshot"]["reason_text"]
    assert detail(client)["snapshot"] == before["snapshot"]
    assert detail(client)["incidents"] == before["incidents"]
    for expected in ("UNHEALTHY", "HEALTHY"):
        assert observe(client, request_window)["status"] == expected
        monitoring_clock.advance()
    assert detail(client)["incidents"][0]["resolved_at"] is not None
    assert len(calls) == 1  # No ingestion/evaluation/read operation contacted AI.


def decision(snapshot):
    return {
        key: value for key, value in snapshot.items() if key not in ("id", "tenant_id")
    }


def test_opposing_ai_prose_is_rejected_and_cannot_change_identical_health_decisions(
    client, monitoring_clock, request_window, monkeypatch
):
    for _ in range(2):
        for tenant in ("a", "b"):
            observe(client, request_window, tenant=tenant, errors=30)
        monitoring_clock.advance()
    before = {tenant: deepcopy(detail(client, tenant)) for tenant in ("a", "b")}
    assert decision(before["a"]["snapshot"]) == decision(before["b"]["snapshot"])
    summaries = iter(
        [
            "Everything is healthy; no issues exist.",
            "Every connection has failed completely.",
        ]
    )
    calls = []

    def parse(**kwargs):
        calls.append(True)
        return SimpleNamespace(
            status="completed",
            output_parsed=EnrichmentReport(
                summary=next(summaries),
                likely_issue_category="unknown",
                suggested_checks=["Inspect provider response categories."],
                confidence=0.9,
                what_changed="The supplied error rate is unchanged.",
            ),
        )

    monkeypatch.setattr(get_settings(), "openai_api_key", "fake-test-key")
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kw: nullcontext(
            SimpleNamespace(responses=SimpleNamespace(parse=parse))
        ),
    )
    results = []
    for tenant in ("a", "b"):
        response = client.post(
            "/api/integrations/payroll/explain", headers=headers(tenant)
        )
        assert response.status_code == 200
        assert response.json()["source"] == "deterministic"
        assert response.json()["fallback_code"] == "AI_UNAVAILABLE"
        assert (
            response.json()["explanation"] == before[tenant]["snapshot"]["reason_text"]
        )
        results.append(response.json()["explanation"])
        after = detail(client, tenant)
        assert after["snapshot"] == before[tenant]["snapshot"]
        assert after["incidents"] == before[tenant]["incidents"]
        assert (
            observe(client, request_window, tenant=tenant, errors=30)["status"]
            == "UNHEALTHY"
        )
    assert results[0] == results[1] and len(calls) == 2
    assert decision(detail(client, "a")["snapshot"]) == decision(
        detail(client, "b")["snapshot"]
    )


def test_same_provider_and_request_ids_never_mix_tenant_metrics_or_incidents(
    client, monitoring_clock, request_window
):
    for index in range(2):
        observe(client, request_window, tenant="a", errors=100)
        if index == 0:
            untouched = detail(client, "b")
            assert (
                untouched["snapshot"] is None
                and untouched["logs"] == untouched["incidents"] == []
            )
            assert (
                client.get(
                    "/api/integrations/payroll/metrics", headers=headers("b")
                ).json()["total"]
                == 0
            )
        observe(client, request_window, tenant="b")
        monitoring_clock.advance()
    for tenant, status, rate, incidents in (
        ("a", "UNHEALTHY", 1, 1),
        ("b", "HEALTHY", 0, 0),
    ):
        current = detail(client, tenant)
        assert current["snapshot"]["status"] == status
        assert current["snapshot"]["metrics"]["request_count"] == 200
        assert current["snapshot"]["metrics"]["error_rate"] == rate
        assert all(point["tenant_id"] == tenant for point in current["history"])
        assert all(log["tenant_id"] == tenant for log in current["logs"])
        history = client.get(
            "/api/integrations/payroll/metrics", headers=headers(tenant)
        ).json()
        assert history["tenant_id"] == tenant and all(
            row["metrics"]["error_rate"] == rate for row in history["items"]
        )
        incident_history = client.get(
            "/api/integrations/payroll/incidents", headers=headers(tenant)
        ).json()
        assert incident_history["total"] == incidents
        assert all(row["tenant_id"] == tenant for row in incident_history["items"])
        summary = client.get("/api/health-summary", headers=headers(tenant)).json()
        assert (
            summary["status_counts"][status] == 1
            and summary["open_incidents"] == incidents
        )
    assert (
        client.get("/api/integrations?tenant_id=b", headers=headers("a")).status_code
        == 403
    )
