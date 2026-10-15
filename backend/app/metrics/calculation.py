from datetime import datetime, timedelta, timezone

import polars as pl


def utc(value: datetime):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def calculate(logs, at: datetime):
    """Event-time windows are [at-window, at); future events never affect evidence."""
    rows = [
        dict(
            occurred_at=utc(x.occurred_at),
            latency_ms=x.latency_ms,
            failed=x.timed_out or x.status_code >= 400,
            category=x.error_category,
        )
        for x in logs
        if at - timedelta(hours=24) <= utc(x.occurred_at) < at
    ]
    if not rows:
        return dict(
            request_count=0,
            error_count=0,
            error_rate=None,
            p95_ms=None,
            last_request_at=None,
            daily_request_count=0,
            daily_error_rate=None,
            error_categories={},
        )
    frame = pl.DataFrame(rows)
    recent = frame.filter(pl.col("occurred_at") >= at - timedelta(minutes=15))
    count = recent.height
    errors = int(recent["failed"].sum()) if count else 0
    categories = recent.filter(pl.col("failed")).group_by("category").len().to_dicts()
    return dict(
        request_count=count,
        error_count=errors,
        error_rate=errors / count if count else None,
        p95_ms=float(recent["latency_ms"].quantile(0.95, interpolation="nearest"))
        if count
        else None,
        last_request_at=max(x["occurred_at"] for x in rows).isoformat(),
        daily_request_count=frame.height,
        daily_error_rate=float(frame["failed"].mean()),
        error_categories={x["category"]: x["len"] for x in categories},
    )
