"""Real SDK parsing over offline HTTP, plus secret-safe failure classification."""

import json

import httpx
import pytest
from app.ai.diagnostics import failure_category
from app.config import get_settings
from openai import APIStatusError, APITimeoutError, OpenAI
from tests.test_incident_assistance import post
from tests.test_monitoring_workflows import detail, observe


@pytest.mark.parametrize(
    "status,code,category",
    [
        (401, "invalid_api_key", "AUTHENTICATION_ERROR"),
        (403, None, "PERMISSION_DENIED"),
        (404, "model_not_found", "MODEL_ACCESS_ERROR"),
        (429, "insufficient_quota", "QUOTA_EXHAUSTED"),
        (429, "rate_limit_exceeded", "RATE_LIMITED"),
        (400, "invalid_json_schema", "INVALID_SCHEMA"),
        (400, "unsupported_parameter", "INVALID_REQUEST"),
        (503, "private-untrusted-code", "PROVIDER_ERROR"),
    ],
)
def test_sdk_errors_map_only_known_safe_categories(status, code, category):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    error = APIStatusError(
        "private-provider-message",
        response=httpx.Response(status, request=request),
        body={"code": code},
    )
    assert failure_category(error) == category


def test_sdk_timeout_and_unexpected_errors_do_not_expose_messages():
    assert (
        failure_category(
            APITimeoutError(
                request=httpx.Request("POST", "https://api.openai.com/v1/responses")
            )
        )
        == "TIMEOUT"
    )
    assert failure_category(RuntimeError("private")) == "UNEXPECTED_ERROR"


def sdk_transport(monkeypatch, handler):
    monkeypatch.setattr(get_settings(), "openai_api_key", "offline-sdk-test-key")
    monkeypatch.setattr(
        "app.ai.enrichment.OpenAI",
        lambda **kwargs: OpenAI(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )


def test_real_sdk_structured_plan_and_safe_success_audit(
    client, request_window, monitoring_clock, monkeypatch, caplog
):
    observe(client, request_window, errors=20)
    before = detail(client)

    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["reasoning"] == {"effort": "none"}
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        assert body["store"] is False
        packet = json.loads(body["input"])
        assert packet["tenant_context"]["id"] == "a"
        assert packet["integration_context"]["name"] == "Payroll"
        plan = dict(
            summary_fact_ids=["decision"],
            change_fact_ids=["changes"],
            likely_issue_category="upstream",
            check_ids=["upstream"],
            confidence="medium",
        )
        return httpx.Response(
            200,
            json={
                "id": "resp_offline",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-6-luna",
                "output": [
                    {
                        "id": "msg_offline",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(plan),
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    sdk_transport(monkeypatch, handler)
    caplog.set_level("INFO", logger="app.ai.diagnostics")
    result = post(client).json()
    assert result["source"] == "openai:gpt-6-luna"
    assert result["audit"]["failure_category"] is None
    assert result["audit"]["requested_model"] == "gpt-6-luna"
    assert result["audit"]["duration_ms"] >= 0
    assert "category=SUCCESS" in caplog.text
    assert "offline-sdk-test-key" not in caplog.text
    assert detail(client)["snapshot"] == before["snapshot"]
    assert detail(client)["incidents"] == before["incidents"]


@pytest.mark.parametrize(
    "kind,category",
    [
        ("quota", "QUOTA_EXHAUSTED"),
        ("refusal", "REFUSAL"),
        ("incomplete", "INCOMPLETE_RESPONSE"),
        ("malformed", "INVALID_RESPONSE"),
    ],
)
def test_actual_sdk_failure_is_audited_without_provider_body(
    client, request_window, monitoring_clock, monkeypatch, caplog, kind, category
):
    observe(client, request_window, errors=20)
    before = detail(client)

    def handler(request):
        if kind == "quota":
            return httpx.Response(
                429,
                json={
                    "error": {
                        "message": "private-provider-secret",
                        "code": "insufficient_quota",
                        "type": "insufficient_quota",
                    }
                },
            )
        response = {
            "id": "resp_offline",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "gpt-6-luna",
            "output": [],
        }
        if kind == "incomplete":
            response["status"] = "incomplete"
        else:
            content = (
                {"type": "refusal", "refusal": "private-provider-secret"}
                if kind == "refusal"
                else {
                    "type": "output_text",
                    "text": "invalid-json-private-provider-secret",
                    "annotations": [],
                }
            )
            response["output"] = [
                {
                    "id": "msg_offline",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [content],
                }
            ]
        return httpx.Response(200, json=response)

    sdk_transport(monkeypatch, handler)
    answer = post(client, "investigate", {"topic": "why_unhealthy"}).json()
    assert answer["fallback_code"] == "AI_UNAVAILABLE"
    assert answer["audit"]["failure_category"] == category
    assert answer["audit"]["duration_ms"] >= 0
    assert "private-provider-secret" not in caplog.text
    assert "offline-sdk-test-key" not in caplog.text
    assert category in caplog.text
    assert detail(client)["snapshot"] == before["snapshot"]
