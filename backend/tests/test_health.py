from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.health.config import DEFAULT_POLICY, HealthPolicy
from app.health.policy import evaluate
from app.metrics.calculation import calculate
from pydantic import ValidationError

AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def metrics(
    n=100, errors=0, p95=500, last=AT - timedelta(seconds=1), timeouts=0, **extra
):
    return dict(
        request_count=n,
        success_count=n - errors,
        error_count=errors,
        error_rate=errors / n if n else None,
        timeout_count=timeouts,
        timeout_rate=timeouts / n if n else None,
        p50_ms=p95,
        p95_ms=p95,
        p99_ms=p95,
        last_request_at=last.isoformat() if last else None,
        daily_request_count=n,
        daily_error_rate=errors / n if n else None,
        error_categories={},
        top_error_categories=[],
        **extra,
    )


def context(result, at=AT):
    return dict(
        bucket=at.isoformat(),
        configuration_fingerprint=result["evidence"]["configuration_fingerprint"],
        **{
            k: result[k]
            for k in (
                "status",
                "bad_window_streak",
                "degraded_window_streak",
                "healthy_window_streak",
            )
        },
    )


def observe(m, config=DEFAULT_POLICY):
    return evaluate(m, AT, config)


@pytest.mark.parametrize(
    "errors,p95,observed,status",
    [
        (0, 500, "HEALTHY", "HEALTHY"),
        (1, 500, "DEGRADED", "DEGRADED"),
        (5, 500, "UNHEALTHY", "DEGRADED"),
        (0, 1500, "DEGRADED", "DEGRADED"),
        (0, 3000, "UNHEALTHY", "DEGRADED"),
        (5, 20, "UNHEALTHY", "DEGRADED"),
        (0, 1499, "HEALTHY", "HEALTHY"),
        (4, 1000, "DEGRADED", "DEGRADED"),
    ],
)
def test_inclusive_signals_and_initial_confirmation(errors, p95, observed, status):
    result = observe(metrics(errors=errors, p95=p95))
    assert result["observed_status"] == observed and result["status"] == status


@pytest.mark.parametrize(
    "m,code",
    [
        (metrics(n=0, last=None), "NO_TELEMETRY"),
        (metrics(n=19), "INSUFFICIENT_REQUESTS"),
        (metrics(n=5, errors=5), "INSUFFICIENT_REQUESTS"),
        (metrics(last=AT - timedelta(minutes=31)), "STALE_TELEMETRY"),
    ],
)
def test_unknown_without_sufficient_evidence(m, code):
    result = observe(m)
    assert result["status"] == "UNKNOWN" and not result["evidence_sufficient"]
    assert result["reason_code"] == code


def test_minimum_and_freshness_boundaries():
    result = observe(metrics(n=20, last=AT - timedelta(minutes=30)))
    assert result["status"] == "HEALTHY" and result["evidence_sufficient"]
    assert result["confidence"] == 1


def test_consecutive_bad_windows_and_recovery():
    first = observe(metrics(errors=10))
    second = evaluate(
        metrics(errors=10), AT + timedelta(minutes=5), previous=context(first)
    )
    assert first["reason_code"] == "UNHEALTHY_CONFIRMATION_PENDING"
    assert second["status"] == "UNHEALTHY" and second["bad_window_streak"] == 2
    pending = evaluate(
        metrics(last=AT + timedelta(minutes=9)),
        AT + timedelta(minutes=10),
        previous=context(second, AT + timedelta(minutes=5)),
        incident_open=True,
    )
    assert (
        pending["status"] == "UNHEALTHY"
        and pending["reason_code"] == "RECOVERY_PENDING"
    )
    recovered = evaluate(
        metrics(last=AT + timedelta(minutes=14)),
        AT + timedelta(minutes=15),
        previous=context(pending, AT + timedelta(minutes=10)),
        incident_open=True,
    )
    assert recovered["status"] == "HEALTHY" and recovered["healthy_window_streak"] == 2


def test_sustained_moderate_degradation_escalates():
    previous = None
    for i in range(3):
        at = AT + timedelta(minutes=i * 5)
        result = evaluate(
            metrics(errors=2, last=at - timedelta(seconds=1)), at, previous=previous
        )
        previous = context(result, at)
    assert (
        result["status"] == "UNHEALTHY"
        and result["reason_code"] == "SUSTAINED_DEGRADATION"
    )


def test_recovery_margin_prevents_boundary_flapping():
    first = observe(metrics(errors=2))
    held = evaluate(
        metrics(n=1000, errors=7), AT + timedelta(minutes=5), previous=context(first)
    )
    assert held["observed_status"] == "HEALTHY" and held["status"] == "DEGRADED"
    assert (
        held["reason_code"] == "RECOVERY_MARGIN_NOT_MET"
        and held["healthy_window_streak"] == 0
    )


def test_unknown_gap_and_configuration_change_reset_streaks():
    first = observe(metrics(errors=10))
    gap = evaluate(
        metrics(errors=10), AT + timedelta(minutes=10), previous=context(first)
    )
    assert gap["status"] == "DEGRADED" and gap["bad_window_streak"] == 1
    changed = HealthPolicy(error_critical=0.08)
    result = evaluate(
        metrics(errors=10), AT + timedelta(minutes=5), changed, previous=context(first)
    )
    assert result["status"] == "DEGRADED" and not result["evidence"]["continuity"]
    unknown = evaluate(
        metrics(n=0, last=None),
        AT + timedelta(minutes=5),
        previous=context(first),
        incident_open=True,
    )
    assert unknown["status"] == "UNKNOWN" and unknown["bad_window_streak"] == 0


def test_timeout_is_independent_and_worst_signal_wins():
    result = observe(
        metrics(errors=1, timeouts=1),
        HealthPolicy(timeout_warning=0.005, timeout_critical=0.01, timeout_recovery=0),
    )
    assert (
        result["observed_status"] == "UNHEALTHY"
        and "TIMEOUT_RATE_CRITICAL" in result["evidence"]["signal_reason_codes"]
    )
    # Very fast responses do not cancel the error signal.
    assert observe(metrics(errors=50, p95=1))["observed_status"] == "UNHEALTHY"


def test_baseline_change_detected_and_bad_baseline_not_trusted():
    base = dict(request_count=200, error_rate=0, timeout_rate=0, p95_ms=200)
    result = observe(metrics(p95=650, baseline=base))
    assert result["observed_status"] == "UNHEALTHY"
    assert result["evidence"]["baseline_used"]
    assert "LATENCY_BASELINE_CRITICAL" in result["evidence"]["signal_reason_codes"]
    for bad in (
        dict(base, request_count=99),
        dict(base, error_rate=0.1),
        dict(base, p95_ms=2000),
    ):
        result = observe(metrics(p95=650, baseline=bad))
        assert result["status"] == "HEALTHY" and not result["evidence"]["baseline_used"]


def test_small_baseline_delta_does_not_trigger_noise():
    base = dict(request_count=200, error_rate=0, timeout_rate=0, p95_ms=10)
    assert observe(metrics(p95=90, baseline=base))["status"] == "HEALTHY"


@pytest.mark.parametrize(
    "options",
    [
        {"error_warning": 0.1, "error_critical": 0.05},
        {"error_recovery": 0.01},
        {"timeout_recovery": 0.1},
        {"latency_recovery_multiplier": 2},
        {"refresh_minutes": 7},
        {"evaluation_window_minutes": 5, "refresh_minutes": 10},
        {"unhealthy_bad_windows": 1},
        {"healthy_recovery_windows": 1},
        {"min_requests": 0},
        {"baseline_lookback_minutes": 2000},
    ],
)
def test_configuration_validation(options):
    with pytest.raises(ValidationError):
        HealthPolicy(**options)


def log(at, status=200, latency=10, timeout=False):
    return SimpleNamespace(
        occurred_at=at,
        status_code=status,
        latency_ms=latency,
        timed_out=timeout,
        error_category="none",
    )


def test_metrics_counts_quantiles_timeouts_top_categories_and_windows():
    rows = [
        log(AT - timedelta(minutes=15), status=401, latency=10),
        log(AT - timedelta(seconds=1), status=504, latency=1000),
        log(AT - timedelta(seconds=2), status=429, latency=50),
        log(AT - timedelta(seconds=3), latency=100),
        log(AT),
        log(AT + timedelta(seconds=1)),
        log(AT - timedelta(minutes=16), status=500),
    ]
    m = calculate(rows, AT)
    assert m["request_count"] == 4 and m["success_count"] == 1 and m["error_count"] == 3
    assert m["error_rate"] == 0.75 and m["timeout_rate"] == 0.25
    assert (m["p50_ms"], m["p95_ms"], m["p99_ms"]) == (100, 1000, 1000)
    assert [x["category"] for x in m["top_error_categories"]] == [
        "auth",
        "rate_limit",
        "timeout",
    ]
    assert m["daily_request_count"] == 5 and m["baseline"]["request_count"] == 1
    assert m["baseline"]["p95_ms"] == 10


def test_configurable_window_and_empty_metrics():
    rows = [log(AT - timedelta(minutes=20)), log(AT - timedelta(minutes=10))]
    m = calculate(rows, AT, HealthPolicy(evaluation_window_minutes=30))
    assert m["request_count"] == 2 and m["baseline"]["request_count"] == 0
    empty = calculate([], AT)
    assert empty["request_count"] == empty["success_count"] == empty["error_count"] == 0
    assert empty["error_rate"] is empty["timeout_rate"] is empty["p99_ms"] is None


def test_pure_deterministic_auditable_result():
    m = metrics()
    before = deepcopy(m)
    result = observe(m)
    assert result == observe(m) and m == before
    assert {
        "status",
        "metrics",
        "confidence",
        "evidence_sufficient",
        "reason_code",
        "reason_text",
        "evaluated_at",
    } <= result.keys()
    assert result["evidence"]["thresholds"] == DEFAULT_POLICY.model_dump()


def test_incomplete_metrics_are_unknown_with_zero_sufficiency_score():
    m = metrics()
    m["timeout_rate"] = None
    result = observe(m)
    assert result["status"] == "UNKNOWN" and result["confidence"] == 0
    assert result["reason_code"] == "INCOMPLETE_METRICS"


def test_disabled_baseline_and_custom_error_thresholds():
    m = metrics(
        errors=10,
        p95=650,
        baseline=dict(request_count=200, error_rate=0, timeout_rate=0, p95_ms=200),
    )
    policy = HealthPolicy(baseline_enabled=False, error_warning=0.2, error_critical=0.3)
    result = observe(m, policy)
    assert (
        result["status"] == "HEALTHY"
        and result["evidence"]["baseline_reason_code"] == "BASELINE_DISABLED"
    )


def test_nonnumeric_configuration_is_rejected():
    with pytest.raises(ValidationError):
        HealthPolicy(min_requests=True)
    with pytest.raises(ValidationError):
        HealthPolicy(refresh_minutes="5")
