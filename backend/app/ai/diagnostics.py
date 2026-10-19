"""Allowlisted provider diagnostics; never serialize exception messages or bodies."""

import hashlib
import logging
import re
from time import monotonic

from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class ResponseFailure(ValueError):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def failure_category(error):
    if isinstance(error, (APITimeoutError, TimeoutError)):
        return "TIMEOUT"
    if isinstance(error, (APIConnectionError, ConnectionError)):
        return "CONNECTION_ERROR"
    if isinstance(error, APIStatusError):
        # Only map known SDK codes; never echo arbitrary provider text.
        known = {
            "insufficient_quota": "QUOTA_EXHAUSTED",
            "invalid_api_key": "AUTHENTICATION_ERROR",
            "model_not_found": "MODEL_ACCESS_ERROR",
            "rate_limit_exceeded": "RATE_LIMITED",
            "unsupported_parameter": "INVALID_REQUEST",
            "invalid_json_schema": "INVALID_SCHEMA",
        }
        code = error.code if isinstance(error.code, str) else None
        return known.get(code) or {
            400: "INVALID_REQUEST",
            401: "AUTHENTICATION_ERROR",
            403: "PERMISSION_DENIED",
            404: "MODEL_ACCESS_ERROR",
            429: "RATE_LIMITED",
        }.get(error.status_code, "PROVIDER_ERROR")
    if isinstance(error, ResponseFailure):
        return (
            error.category
            if error.category in {"REFUSAL", "INCOMPLETE_RESPONSE"}
            else "INVALID_RESPONSE"
        )
    if isinstance(error, (ValidationError, ValueError)):
        return "INVALID_RESPONSE"
    return "UNEXPECTED_ERROR"


def response_failure(response):
    if any(
        getattr(content, "type", None) == "refusal"
        for item in getattr(response, "output", []) or []
        for content in getattr(item, "content", []) or []
    ):
        return ResponseFailure("REFUSAL")
    if getattr(response, "status", "completed") != "completed":
        return ResponseFailure("INCOMPLETE_RESPONSE")
    return ResponseFailure("INVALID_RESPONSE")


def log_result(
    model,
    started,
    category=None,
    *,
    request_id=None,
    tenant_id=None,
    integration_id=None,
    incident_id=None,
    provider_request_id=None,
):
    duration = round((monotonic() - started) * 1000)
    logger.log(
        logging.WARNING if category else logging.INFO,
        "AI request model=%s category=%s duration_ms=%s fallback_used=%s",
        model,
        category or "SUCCESS",
        duration,
        category is not None,
    )
    if request_id:

        def ref(value):
            return (
                hashlib.sha256(str(value).encode()).hexdigest()[:12] if value else None
            )

        safe_provider = (
            provider_request_id
            if isinstance(provider_request_id, str)
            and re.fullmatch(r"req[_-][A-Za-z0-9_-]{1,120}", provider_request_id)
            else None
        )
        logger.log(
            logging.WARNING if category else logging.INFO,
            "AI context request_id=%s tenant_ref=%s integration_ref=%s incident_ref=%s provider_request_id=%s",
            request_id,
            ref(tenant_id),
            ref(integration_id),
            ref(incident_id),
            safe_provider,
        )
    return duration
