"""Model selection is backend configuration and cannot change health decisions."""

from types import SimpleNamespace

import pytest
from app.ai.enrichment import explain, model_options
from app.config import Settings, get_settings
from pydantic import ValidationError
from tests.test_enrichment import mock_client, report, snapshot_at
from tests.test_incident_assistance import fake_ai, post
from tests.test_monitoring_workflows import detail, observe


@pytest.mark.parametrize("value", [None, "", "gpt-6-luna"])
def test_default_luna_from_process_environment(monkeypatch, value):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    if value is not None:
        monkeypatch.setenv("OPENAI_MODEL", value)
    assert Settings().openai_model == "gpt-6-luna"
    assert model_options(Settings()) == {
        "model": "gpt-6-luna",
        "reasoning": {"effort": "none"},
    }


def test_override_and_invalid_model_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "provider-model-test")
    settings = Settings()
    assert model_options(settings) == {"model": "provider-model-test"}
    with pytest.raises(ValidationError) as error:
        Settings(openai_model="invalid model private-input")
    assert "private-input" not in str(error.value)


def test_legacy_path_uses_override_and_refreshes_cache(
    db, monkeypatch, monitoring_clock
):
    snapshot = snapshot_at(db, monitoring_clock.now)
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=report())

    mock_client(monkeypatch, parse)
    settings = Settings(openai_api_key="fake-test-key", openai_model="gpt-6-luna")
    first = explain(db, snapshot, settings)
    assert first.source == "openai:gpt-6-luna"
    assert calls[0]["reasoning"] == {"effort": "none"}
    settings.openai_model = "provider-model-test"
    second = explain(db, snapshot, settings)
    assert second.id == first.id
    assert second.source == "openai:provider-model-test"
    assert calls[1]["model"] == "provider-model-test"
    assert "reasoning" not in calls[1]
    assert explain(db, snapshot, settings).id == first.id
    assert len(calls) == 2
    assert snapshot.status == "UNKNOWN"


def test_brief_and_copilot_use_model_override_without_changing_health(
    client, monitoring_clock, request_window, monkeypatch
):
    observe(client, request_window, errors=20)
    before = detail(client)
    calls = fake_ai(monkeypatch)
    monkeypatch.setattr(get_settings(), "openai_model", "gpt-6-luna")
    first = post(client).json()
    assert calls[0]["model"] == "gpt-6-luna"
    assert calls[0]["reasoning"] == {"effort": "none"}
    assert first["evidence_payload"]["requested_model"] == "gpt-6-luna"
    monkeypatch.setattr(get_settings(), "openai_model", "provider-model-test")
    second = post(client).json()
    assert second["id"] == first["id"]
    assert calls[1]["model"] == "provider-model-test"
    assert "reasoning" not in calls[1]
    post(client)
    assert len(calls) == 2
    answer = post(client, "investigate", {"topic": "error_driver"})
    assert answer.status_code == 200
    assert calls[2]["model"] == "provider-model-test"
    after = detail(client)
    assert after["snapshot"] == before["snapshot"]
    assert after["incidents"] == before["incidents"]
