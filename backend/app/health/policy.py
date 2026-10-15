from datetime import datetime, timedelta

from app.metrics.calculation import utc

POLICY_VERSION = "2026-10-v1"
THRESHOLDS = dict(
    min_requests=20,
    error_warning=0.01,
    error_critical=0.05,
    latency_warning_multiplier=1.5,
    latency_critical_multiplier=3,
    burst_min_errors=5,
    burst_error_rate=0.5,
)


def evaluate(metrics: dict, at: datetime, latency_target_ms: int, max_gap_minutes: int):
    thresholds = dict(
        THRESHOLDS, latency_target_ms=latency_target_ms, max_gap_minutes=max_gap_minutes
    )
    evidence = dict(
        policy_version=POLICY_VERSION,
        thresholds=thresholds,
        metrics=metrics,
        window_start=(at - timedelta(minutes=15)).isoformat(),
        window_end=at.isoformat(),
    )
    last = metrics["last_request_at"]
    age = (
        (at - utc(datetime.fromisoformat(last))).total_seconds() / 60 if last else None
    )
    if age is None or age > max_gap_minutes:
        return dict(
            status="unknown",
            score=None,
            evidence=dict(
                evidence,
                reasons=[
                    "No fresh request telemetry within expected activity interval."
                ],
            ),
        )
    count, errors, rate = (
        metrics["request_count"],
        metrics["error_count"],
        metrics["error_rate"],
    )
    if count < THRESHOLDS["min_requests"]:
        if (
            errors >= THRESHOLDS["burst_min_errors"]
            and rate >= THRESHOLDS["burst_error_rate"]
        ):
            return dict(
                status="unhealthy",
                score=0,
                evidence=dict(
                    evidence,
                    reasons=[
                        f"Failure burst: at least {THRESHOLDS['burst_min_errors']} failures and {THRESHOLDS['burst_error_rate']:.0%} error rate despite low volume."
                    ],
                ),
            )
        return dict(
            status="unknown",
            score=None,
            evidence=dict(
                evidence,
                reasons=[
                    f"Insufficient sample: {count} requests; at least {THRESHOLDS['min_requests']} required."
                ],
            ),
        )
    severity, reasons = 0, []
    if rate >= THRESHOLDS["error_critical"]:
        severity = 2
        reasons.append(
            f"Error rate {rate:.1%} meets or exceeds {THRESHOLDS['error_critical']:.0%} critical threshold."
        )
    elif rate >= THRESHOLDS["error_warning"]:
        severity = 1
        reasons.append(
            f"Error rate {rate:.1%} meets or exceeds {THRESHOLDS['error_warning']:.0%} warning threshold."
        )
    ratio = metrics["p95_ms"] / latency_target_ms
    if ratio >= THRESHOLDS["latency_critical_multiplier"]:
        severity = 2
        reasons.append(
            f"P95 latency is {ratio:.2f}× target (critical at {THRESHOLDS['latency_critical_multiplier']:g}×)."
        )
    elif ratio >= THRESHOLDS["latency_warning_multiplier"]:
        severity = max(severity, 1)
        reasons.append(
            f"P95 latency is {ratio:.2f}× target (warning at {THRESHOLDS['latency_warning_multiplier']:g}×)."
        )
    if not reasons:
        reasons = [
            "Error rate and P95 latency are within policy; sample and freshness checks passed."
        ]
    # Severity bands avoid hiding critical errors behind a weighted latency average.
    return dict(
        status=["healthy", "degraded", "unhealthy"][severity],
        score=[100, 60, 0][severity],
        evidence=dict(evidence, reasons=reasons),
    )
