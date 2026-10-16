"""Shared deterministic request outcome semantics for ingestion and analytics."""


def is_timeout(status_code: int, timed_out: bool) -> bool:
    return timed_out or status_code in (408, 504)


def error_category(status_code: int, timed_out: bool) -> str:
    if is_timeout(status_code, timed_out):
        return "timeout"
    if status_code in (401, 403):
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if status_code >= 500:
        return "upstream"
    if status_code >= 400:
        return "validation"
    return "none"
