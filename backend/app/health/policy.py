"""Pure, deterministic classification and hysteresis. No persistence or AI imports."""

import hashlib
import json
from datetime import datetime, timedelta

from app.health.config import DEFAULT_POLICY, POLICY_VERSION, HealthPolicy
from app.metrics.calculation import utc


def fingerprint(config: HealthPolicy) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(version=POLICY_VERSION, **config.model_dump()), sort_keys=True
        ).encode()
    ).hexdigest()


def evaluate(
    metrics: dict,
    at: datetime,
    config: HealthPolicy = DEFAULT_POLICY,
    *,
    previous: dict | None = None,
    incident_open: bool = False,
    evaluated_at: datetime | None = None,
) -> dict:
    at = utc(at)
    signature = fingerprint(config)
    previous = previous or {}
    contiguous = bool(
        previous
        and previous.get("configuration_fingerprint") == signature
        and at - utc(datetime.fromisoformat(previous["bucket"]))
        == timedelta(minutes=config.refresh_minutes)
    )
    baseline = metrics.get("baseline", {})
    baseline_used = bool(
        config.baseline_enabled
        and baseline.get("request_count", 0) >= config.baseline_min_requests
        and baseline.get("error_rate") is not None
        and baseline["error_rate"] < config.error_warning
        and baseline.get("timeout_rate") is not None
        and baseline["timeout_rate"] < config.timeout_warning
        and baseline.get("p95_ms") is not None
        and 0
        < baseline["p95_ms"]
        < config.latency_target_ms * config.latency_warning_multiplier
    )
    baseline_reason = (
        "BASELINE_DISABLED"
        if not config.baseline_enabled
        else "BASELINE_INSUFFICIENT_REQUESTS"
        if baseline.get("request_count", 0) < config.baseline_min_requests
        else "BASELINE_AVAILABLE"
        if baseline_used
        else "BASELINE_NOT_HEALTHY"
    )
    count = metrics["request_count"]
    last = metrics.get("last_request_at")
    fresh = bool(
        last
        and timedelta(0)
        <= at - utc(datetime.fromisoformat(last))
        <= timedelta(minutes=config.max_gap_minutes)
    )
    sufficient = bool(
        fresh
        and count >= config.min_requests
        and all(
            metrics.get(key) is not None
            for key in ("error_rate", "timeout_rate", "p95_ms")
        )
    )
    confidence = min(count / config.min_requests, 1.0) if fresh else 0.0
    if fresh and count >= config.min_requests and not sufficient:
        confidence = 0.0
    signals = []
    if not fresh:
        observed, code = "UNKNOWN", "STALE_TELEMETRY" if last else "NO_TELEMETRY"
        texts = [
            f"No request telemetry within the configured {config.max_gap_minutes}-minute activity interval."
        ]
    elif count < config.min_requests:
        observed, code = "UNKNOWN", "INSUFFICIENT_REQUESTS"
        texts = [
            f"Only {count} requests in {config.evaluation_window_minutes} minutes; {config.min_requests} required for classification."
        ]
    elif not sufficient:
        observed, code = "UNKNOWN", "INCOMPLETE_METRICS"
        texts = ["Required error, timeout or latency evidence is missing."]
    else:
        for metric, warning, critical, prefix, label in (
            (
                metrics["error_rate"],
                config.error_warning,
                config.error_critical,
                "ERROR_RATE",
                "Error rate",
            ),
            (
                metrics["timeout_rate"],
                config.timeout_warning,
                config.timeout_critical,
                "TIMEOUT_RATE",
                "Timeout rate",
            ),
        ):
            if metric >= critical:
                signals.append(
                    (
                        2,
                        f"{prefix}_CRITICAL",
                        f"{label} {metric:.2%} meets the {critical:.2%} critical threshold.",
                    )
                )
            elif metric >= warning:
                signals.append(
                    (
                        1,
                        f"{prefix}_ELEVATED",
                        f"{label} {metric:.2%} meets the {warning:.2%} warning threshold.",
                    )
                )
        p95 = metrics["p95_ms"]
        comparators = [(config.latency_target_ms, "TARGET")]
        if baseline_used and p95 - baseline["p95_ms"] >= config.baseline_min_delta_ms:
            comparators.append((baseline["p95_ms"], "BASELINE"))
        for reference, label in comparators:
            ratio = p95 / reference
            if ratio >= config.latency_critical_multiplier:
                signals.append(
                    (
                        2,
                        f"LATENCY_{label}_CRITICAL",
                        f"P95 {p95:.1f} ms is {ratio:.2f}× {label.lower()} (critical at {config.latency_critical_multiplier:g}×).",
                    )
                )
            elif ratio >= config.latency_warning_multiplier:
                signals.append(
                    (
                        1,
                        f"LATENCY_{label}_ELEVATED",
                        f"P95 {p95:.1f} ms is {ratio:.2f}× {label.lower()} (warning at {config.latency_warning_multiplier:g}×).",
                    )
                )
        worst = max((x[0] for x in signals), default=0)
        observed = ("HEALTHY", "DEGRADED", "UNHEALTHY")[worst]
        code = next((x[1] for x in signals if x[0] == worst), "WITHIN_POLICY")
        texts = [x[2] for x in signals] or [
            "Request count and freshness are sufficient; error rate, timeout rate and P95 latency are within policy."
        ]

    bad = (
        (previous.get("bad_window_streak", 0) if contiguous else 0) + 1
        if observed in ("DEGRADED", "UNHEALTHY")
        else 0
    )
    degraded = (
        (previous.get("degraded_window_streak", 0) if contiguous else 0) + 1
        if observed == "DEGRADED"
        else 0
    )
    recovery_ok = bool(
        observed == "HEALTHY"
        and metrics["error_rate"] <= config.error_recovery
        and metrics["timeout_rate"] <= config.timeout_recovery
        and metrics["p95_ms"]
        <= config.latency_target_ms * config.latency_recovery_multiplier
        and (
            not baseline_used
            or metrics["p95_ms"] - baseline["p95_ms"] < config.baseline_min_delta_ms
            or metrics["p95_ms"]
            <= baseline["p95_ms"] * config.latency_recovery_multiplier
        )
    )
    healthy = (
        (previous.get("healthy_window_streak", 0) if contiguous else 0) + 1
        if recovery_ok
        else 0
    )
    old = previous.get("status", "UNKNOWN")
    held = (
        "UNHEALTHY"
        if incident_open or old == "UNHEALTHY"
        else "DEGRADED"
        if old == "DEGRADED"
        else None
    )
    status = observed
    if observed == "UNKNOWN":
        healthy = bad = degraded = 0
        confidence = min(confidence, 1.0) if fresh else 0.0
    elif held and observed == "HEALTHY":
        if healthy < config.healthy_recovery_windows:
            status = held
            code = "RECOVERY_PENDING" if recovery_ok else "RECOVERY_MARGIN_NOT_MET"
            texts.append(
                f"Holding {held}: {healthy}/{config.healthy_recovery_windows} adjacent windows meet the tighter recovery thresholds."
            )
    elif held == "UNHEALTHY":
        status = "UNHEALTHY"
        if observed == "DEGRADED":
            code = "UNHEALTHY_RECOVERY_REQUIRED"
        texts.append(
            "Confirmed unhealthy state remains active until sustained recovery."
        )
    elif degraded >= config.sustained_degraded_windows:
        status, code = "UNHEALTHY", "SUSTAINED_DEGRADATION"
        texts.append(
            f"Degradation persisted for {degraded} adjacent windows (limit {config.sustained_degraded_windows})."
        )
    elif observed == "UNHEALTHY" and bad < config.unhealthy_bad_windows:
        status, code = "DEGRADED", "UNHEALTHY_CONFIRMATION_PENDING"
        texts.append(
            f"Critical evidence observed; {bad}/{config.unhealthy_bad_windows} adjacent bad windows required before confirming unhealthy."
        )

    return dict(
        status=status,
        observed_status=observed,
        metrics=metrics,
        evidence_sufficient=sufficient,
        confidence=confidence,
        reason_code=code,
        reason_text=" ".join(texts),
        evaluated_at=utc(evaluated_at or at),
        score={"HEALTHY": 100, "DEGRADED": 60, "UNHEALTHY": 0, "UNKNOWN": None}[status],
        bad_window_streak=bad,
        degraded_window_streak=degraded,
        healthy_window_streak=healthy,
        evidence=dict(
            policy_version=POLICY_VERSION,
            configuration_fingerprint=signature,
            thresholds=config.model_dump(),
            metrics=metrics,
            window_start=(
                at - timedelta(minutes=config.evaluation_window_minutes)
            ).isoformat(),
            window_end=at.isoformat(),
            reasons=texts,
            signal_reason_codes=[x[1] for x in signals],
            baseline_used=baseline_used,
            baseline_sufficient=baseline_used,
            baseline_reason_code=baseline_reason,
            hysteresis=dict(
                previous_status=old,
                incident_was_open=incident_open,
                bad_window_streak=bad,
                degraded_window_streak=degraded,
                healthy_window_streak=healthy,
            ),
            continuity=contiguous,
            recovery_thresholds_met=recovery_ok,
        ),
    )
