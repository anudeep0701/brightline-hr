from datetime import datetime, timedelta, timezone

import polars as pl

from app.health.config import DEFAULT_POLICY, HealthPolicy
from app.metrics.categories import error_category, is_timeout


def utc(value: datetime):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def aggregate(frame: pl.DataFrame, top_limit: int) -> dict:
    count = frame.height
    errors = int(frame["failed"].sum()) if count else 0
    timeouts = int(frame["timeout"].sum()) if count else 0
    categories = (
        frame.filter(pl.col("failed")).group_by("category").len().to_dicts()
        if count
        else []
    )
    categories.sort(key=lambda x: (-x["len"], x["category"]))
    metrics = dict(
        request_count=count,
        success_count=count - errors,
        error_count=errors,
        timeout_count=timeouts,
        error_rate=errors / count if count else None,
        timeout_rate=timeouts / count if count else None,
        error_categories={x["category"]: x["len"] for x in categories},
        top_error_categories=[
            dict(
                category=x["category"],
                count=x["len"],
                fraction_of_errors=x["len"] / errors,
            )
            for x in categories[:top_limit]
        ],
    )
    for key, quantile in (("p50_ms", 0.5), ("p95_ms", 0.95), ("p99_ms", 0.99)):
        metrics[key] = (
            float(frame["latency_ms"].quantile(quantile, interpolation="nearest"))
            if count
            else None
        )
    return metrics


def calculate(logs, at: datetime, config: HealthPolicy = DEFAULT_POLICY):
    """Current [T-window,T); baseline ends BEFORE the current window, without overlap."""
    at = utc(at)
    start = at - timedelta(minutes=config.evaluation_window_minutes)
    baseline_start = start - timedelta(minutes=config.baseline_lookback_minutes)
    daily_start = at - timedelta(days=1)
    rows = [
        dict(
            occurred_at=utc(x.occurred_at),
            latency_ms=x.latency_ms,
            failed=is_timeout(x.status_code, x.timed_out) or x.status_code >= 400,
            timeout=is_timeout(x.status_code, x.timed_out),
            category=error_category(x.status_code, x.timed_out),
        )
        for x in logs
        if min(baseline_start, daily_start) <= utc(x.occurred_at) < at
    ]
    frame = (
        pl.DataFrame(rows)
        if rows
        else pl.DataFrame(
            schema={
                "occurred_at": pl.Datetime("us", "UTC"),
                "latency_ms": pl.Float64,
                "failed": pl.Boolean,
                "timeout": pl.Boolean,
                "category": pl.String,
            }
        )
    )
    recent = frame.filter(pl.col("occurred_at") >= start)
    historical = frame.filter(
        (pl.col("occurred_at") >= baseline_start) & (pl.col("occurred_at") < start)
    )
    daily = frame.filter(pl.col("occurred_at") >= daily_start)
    metrics = aggregate(recent, config.top_error_limit)
    baseline = aggregate(historical, config.top_error_limit)
    baseline.update(
        window_start=baseline_start.isoformat(), window_end=start.isoformat()
    )
    metrics.update(
        last_request_at=max(x["occurred_at"] for x in rows).isoformat()
        if rows
        else None,
        daily_request_count=daily.height,
        daily_error_rate=float(daily["failed"].mean()) if daily.height else None,
        baseline=baseline,
    )
    return metrics
