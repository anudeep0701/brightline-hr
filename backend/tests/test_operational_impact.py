"""Fixed-clock business outcomes through the existing ingestion and incident lifecycle."""

from datetime import timedelta

import pytest
from app.models.entities import Incident, Integration
from tests.test_monitoring_workflows import (
    disjoint_windows,
    evaluate,
    headers,
    ingest,
    observe,
)


def dashboard(client, tenant="a"):
    response = client.get("/api/v1/dashboard", headers=headers(tenant))
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_evidence_is_unknown_and_has_no_invented_outcomes(
    client, monitoring_clock
):
    impact = dashboard(client)["operational_impact"]
    assert impact["integrations_requiring_attention"] == 1
    assert impact["unknown_integrations"] == impact["stale_or_absent_integrations"] == 1
    assert impact["healthy_percentage"] == 0
    assert impact["incidents_detected"] == impact["recovered_incidents"] == 0
    assert impact["mean_confirmed_incident_duration_seconds"] is None


def test_healthy_percentage_never_counts_stale_healthy_evidence(
    client, monitoring_clock, request_window
):
    observe(client, request_window)
    assert dashboard(client)["operational_impact"]["healthy_percentage"] == 100
    monitoring_clock.advance(31)
    impact = dashboard(client)["operational_impact"]
    assert impact["healthy_percentage"] == 0
    assert impact["unknown_integrations"] == 1
    assert impact["stale_or_absent_integrations"] == 1


def test_no_integrations_has_null_percentage(client, db, monitoring_clock):
    from app.models.entities import Tenant

    db.add(Tenant(id="empty", name="Empty pilot"))
    db.commit()
    from app.config import Settings
    from app.services.operations import dashboard as read_dashboard

    impact = read_dashboard(db, "empty", Settings())["operational_impact"]
    assert impact["healthy_percentage"] is None
    assert impact["integrations_requiring_attention"] == 0


def test_confirmed_incident_recovery_and_replay_are_measured_once(
    client, monitoring_clock, request_window
):
    disjoint_windows(client)
    observe(client, request_window, errors=20)
    monitoring_clock.advance()
    observe(client, request_window, errors=20)
    monitoring_clock.advance()
    observe(client, request_window)
    monitoring_clock.advance()
    observe(client, request_window)
    monitoring_clock.advance(1)
    before = dashboard(client)["operational_impact"]
    assert before["incidents_detected"] == before["recovered_incidents"] == 1
    assert before["mean_confirmed_incident_duration_seconds"] == 600
    evaluate(client)  # Same bucket is idempotent; no new incident or recovery.
    assert dashboard(client)["operational_impact"] == before
    assert dashboard(client, "b")["operational_impact"]["incidents_detected"] == 0


def test_24h_boundaries_and_unclipped_duration_are_tenant_scoped(
    client, db, monitoring_clock, request_window
):
    snapshot = observe(client, request_window)
    end = monitoring_clock.now
    start = end - timedelta(hours=24)
    periods = [
        (start - timedelta(hours=2), start + timedelta(hours=1)),
        (start, start + timedelta(minutes=30)),
        (end - timedelta(minutes=20), end - timedelta(minutes=10)),
        (end, end + timedelta(minutes=10)),
        (start - timedelta(hours=3), start),
        (start - timedelta(hours=4), start - timedelta(seconds=1)),
        (end - timedelta(minutes=5), None),
    ]
    for opened, resolved in periods:
        db.add(
            Incident(
                tenant_id="a",
                integration_id="payroll",
                opened_at=opened,
                resolved_at=resolved,
                opening_snapshot_id=snapshot["id"],
                last_snapshot_id=snapshot["id"],
            )
        )
    db.commit()
    impact = dashboard(client)["operational_impact"]
    assert impact["incidents_detected"] == 3
    assert impact["recovered_incidents"] == 4
    assert impact["mean_confirmed_incident_duration_seconds"] == 6000
    assert dashboard(client, "b")["operational_impact"]["recovered_incidents"] == 0


@pytest.mark.parametrize(
    "errors,expected", [(0, "HEALTHY"), (2, "DEGRADED"), (20, "UNHEALTHY")]
)
def test_future_providers_share_normalized_policy_and_reason_semantics(
    client, db, monitoring_clock, request_window, errors, expected
):
    providers = {
        name.lower().replace(" ", "-"): name
        for name in ["Salesforce", "ServiceNow", "SAP", "Microsoft Graph", "Stripe"]
    }
    for provider in providers:
        db.add(
            Integration(
                tenant_id="a",
                id=provider,
                name=providers[provider],
                category="Custom",
                owner="Ops",
                latency_target_ms=1000,
                max_gap_minutes=30,
            )
        )
    db.commit()
    for _ in range(2):
        batch = [
            dict(event, integration_id=provider)
            for provider in providers
            for event in request_window(errors=errors, label=provider)
        ]
        assert ingest(client, batch)["accepted"] == 500
        evaluate(client)
        monitoring_clock.advance()
    rows = [
        row
        for row in dashboard(client)["integrations"]
        if row["integration"]["id"] in providers
    ]
    assert {row["snapshot"]["status"] for row in rows} == {expected}
    assert len({row["snapshot"]["reason_code"] for row in rows}) == 1
    url = "/api/v1/integrations/stripe/config"
    policy = client.get(url, headers=headers()).json()
    assert (
        client.put(
            url, headers=headers(), json=dict(policy, min_requests=1000)
        ).status_code
        == 200
    )
    evaluate(client)
    stripe = next(
        row
        for row in dashboard(client)["integrations"]
        if row["integration"]["id"] == "stripe"
    )
    assert stripe["snapshot"]["status"] == "UNKNOWN"
    assert stripe["snapshot"]["reason_code"] == "INSUFFICIENT_REQUESTS"
