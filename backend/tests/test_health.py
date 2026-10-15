from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.health.policy import evaluate
from app.metrics.calculation import calculate

AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def metrics(n=100, errors=0, p95=500, last=AT - timedelta(seconds=1)):
    return dict(
        request_count=n,
        error_count=errors,
        error_rate=errors / n if n else None,
        p95_ms=p95,
        last_request_at=last.isoformat() if last else None,
        daily_request_count=n,
        daily_error_rate=0,
        error_categories={},
    )


@pytest.mark.parametrize(
    "errors,p95,status",
    [
        (0, 500, "healthy"),
        (1, 500, "degraded"),
        (5, 500, "unhealthy"),
        (0, 1500, "degraded"),
        (0, 3000, "unhealthy"),
        (5, 20, "unhealthy"),
        (0, 1499, "healthy"),
        (4, 1000, "degraded"),
    ],
)
def test_thresholds(errors, p95, status):
    assert evaluate(metrics(errors=errors, p95=p95), AT, 1000, 30)["status"] == status


@pytest.mark.parametrize(
    "m,status",
    [
        (metrics(n=0, last=None), "unknown"),
        (metrics(n=19), "unknown"),
        (metrics(n=20), "healthy"),
        (metrics(n=5, errors=5), "unhealthy"),
        (metrics(n=10, errors=4), "unknown"),
        (metrics(last=AT - timedelta(minutes=31)), "unknown"),
        (metrics(last=AT - timedelta(minutes=30)), "healthy"),
    ],
)
def test_confidence(m, status):
    assert evaluate(m, AT, 1000, 30)["status"] == status


def log(at, status=200, latency=10, timeout=False):
    return SimpleNamespace(
        occurred_at=at,
        status_code=status,
        latency_ms=latency,
        timed_out=timeout,
        error_category="timeout" if timeout else "none",
    )


def test_event_time_window_and_timeouts():
    rows = [
        log(AT - timedelta(minutes=15)),
        log(AT - timedelta(seconds=1), latency=1000, timeout=True),
        log(AT),
        log(AT + timedelta(seconds=1)),
        log(AT - timedelta(minutes=16), status=500),
    ]
    m = calculate(rows, AT)
    assert m["request_count"] == 2
    assert m["daily_request_count"] == 3
    assert m["error_rate"] == 0.5 and m["p95_ms"] == 1000
    assert m["error_categories"] == {"timeout": 1}


def test_policy_pure_and_auditable():
    m = metrics()
    assert evaluate(m, AT, 1000, 30) == evaluate(m, AT, 1000, 30)
    result = evaluate(m, AT, 1000, 30)
    assert (
        result["evidence"]["policy_version"]
        and result["evidence"]["thresholds"]
        and result["evidence"]["reasons"]
    )
