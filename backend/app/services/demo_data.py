"""Small, current-time assessment fixtures through real ingestion and health policy.

No production generator dependencies, timestamp edits or historical decision rewrites.
The tenant row lock spans generation/ingestion/evaluation for concurrent visitors.
"""

import hashlib
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.health.service import bucket_for, refresh
from app.ingestion.service import ingest
from app.metrics.calculation import utc
from app.models.entities import Integration, RequestEvent, Snapshot, Tenant
from app.services.errors import ServiceError

MAX_INTEGRATIONS = 12
EVENTS_PER_INTEGRATION = 96
MAX_DEMO_IMPORTS = 3000

# Fixed assessment fixtures only; these never participate in health classification.
DEMO_INTEGRATIONS = (
    ("workday-payroll", "Workday Payroll", "payroll", "Payroll operations", 1200),
    ("adp-payroll", "ADP Payroll", "payroll", "Payroll operations", 1000),
    ("docusign", "DocuSign", "e_signature", "People operations", 1500),
    ("greenhouse-ats", "Greenhouse ATS", "ats", "Talent operations", 1000),
    ("okta-directory", "Okta Directory Sync", "directory_sync", "IT operations", 800),
    (
        "slack-notifications",
        "Slack Notifications",
        "notifications",
        "People operations",
        800,
    ),
    (
        "twilio-notifications",
        "Twilio Notifications",
        "notifications",
        "People operations",
        1000,
    ),
    ("adp-recovery", "ADP Payroll (Recovery)", "payroll", "Payroll operations", 1000),
)


def require_demo(settings):
    if not settings.demo_mode or not settings.demo_tenant_slug:
        raise ServiceError(
            403,
            "demo_required",
            "This operation requires the configured demo workspace",
        )
    return settings.demo_tenant_slug


def demo_import_query(tenant_id):
    return select(RequestEvent).where(
        RequestEvent.tenant_id == tenant_id,
        RequestEvent.source_type == "FILE_IMPORT",
        RequestEvent.raw_event["demo_import_batch_id"].as_string().is_not(None),
    )


def clear_demo_imports(db, settings):
    tenant_id = require_demo(settings)
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    ids = demo_import_query(tenant_id).with_only_columns(RequestEvent.event_id)
    result = db.execute(
        delete(RequestEvent).where(
            RequestEvent.tenant_id == tenant_id, RequestEvent.event_id.in_(ids)
        )
    )
    db.commit()
    return result.rowcount


def refresh_demo_data(db, settings, *, now=None, force=False, populate=False):
    tenant_id = require_demo(settings)
    now = utc(now or datetime.now(timezone.utc))
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        raise ServiceError(
            503, "demo_unavailable", "Configured demo workspace does not exist"
        )
    integrations = list(
        db.scalars(
            select(Integration)
            .where(Integration.tenant_id == tenant_id)
            .order_by(Integration.id)
            .limit(MAX_INTEGRATIONS + 1)
        )
    )
    if populate:
        present = {integration.id for integration in integrations}
        missing = [spec for spec in DEMO_INTEGRATIONS if spec[0] not in present]
        if len(integrations) + len(missing) > MAX_INTEGRATIONS:
            raise ServiceError(
                409,
                "demo_capacity",
                "Demo scenario catalog exceeds the 12-integration limit",
            )
        for identity, name, category, owner, target in missing:
            integration = Integration(
                tenant_id=tenant_id,
                id=identity,
                name=name,
                category=category,
                owner=owner,
                latency_target_ms=target,
            )
            db.add(integration)
            integrations.append(integration)
        db.flush()
    if len(integrations) > MAX_INTEGRATIONS:
        raise ServiceError(
            409,
            "demo_capacity",
            "Automatic demo refresh supports at most 12 integrations",
        )
    bucket = bucket_for(now)
    events = []
    earliest = bucket
    for integration in integrations:
        latest = db.scalar(
            select(RequestEvent)
            .where(
                RequestEvent.tenant_id == tenant_id,
                RequestEvent.integration_id == integration.id,
            )
            .order_by(RequestEvent.occurred_at.desc())
            .limit(1)
        )
        snapshot = db.scalar(
            select(Snapshot)
            .where(
                Snapshot.tenant_id == tenant_id,
                Snapshot.integration_id == integration.id,
            )
            .order_by(Snapshot.bucket.desc())
            .limit(1)
        )
        # Imported/live evidence and deliberately stale scenarios must remain observable.
        scenario = latest.raw_event.get("scenario", "") if latest else ""
        if latest and (
            latest.source_type not in {"DEMO", "UNKNOWN"}
            or scenario in {"stale_telemetry", "stale-telemetry"}
        ):
            continue
        # Refill a synthetic feed at its policy cadence, before its rolling
        # sample drains. This does not change the real telemetry freshness rule.
        stale = latest is None or now - utc(latest.occurred_at) > timedelta(
            minutes=min(
                integration.config.max_gap_minutes, integration.config.refresh_minutes
            )
        )
        overdue = snapshot is None or now - utc(snapshot.bucket) > timedelta(
            minutes=integration.config.refresh_minutes * 2
        )
        if not force and not stale and not overdue:
            continue
        # Stable IDs provide a second idempotency boundary, including explicit reloads.
        prefix = (
            "demo-v1-"
            + hashlib.sha256(
                f"{tenant_id}:{integration.id}:{bucket.isoformat()}".encode()
            ).hexdigest()[:24]
        )
        if db.get(RequestEvent, (tenant_id, prefix + "-0")):
            continue
        rng = random.Random(prefix)
        sparse = integration.id == "twilio-notifications" or scenario == "low_traffic"
        count = 1 if sparse else EVENTS_PER_INTEGRATION
        for index in range(count):
            age = 60 if sparse else (count - index) * 1800 / count
            status = 200
            latency = integration.latency_target_ms * rng.uniform(0.25, 0.5)
            if (
                integration.id
                in {
                    "slack-notifications",
                    "greenhouse-ats",
                    "workday-sustained",
                    "okta-directory",
                }
                and age < 1080
            ):
                if (
                    integration.id not in {"workday-sustained", "okta-directory"}
                    or index % 2 == 0
                ):
                    status = 401 if integration.id == "slack-notifications" else 503
            if integration.id == "adp-recovery" and age > 1200:
                status = 503
            if integration.id == "adp-payroll" and index == count - 1:
                status = 500
            if integration.id == "docusign" and age < 180:
                latency = integration.latency_target_ms * 2
            at = bucket - timedelta(seconds=age)
            earliest = min(earliest, at)
            events.append(
                dict(
                    timestamp=at.isoformat(),
                    request_id=prefix + f"-{index}",
                    integration_id=integration.id,
                    http_status=status,
                    latency_ms=round(latency, 2),
                    scenario="low_traffic" if sparse else "hosted_baseline",
                    error_code="AUTH_EXPIRED"
                    if status == 401
                    else "UPSTREAM"
                    if status >= 400
                    else None,
                )
            )
    accepted = 0
    for start in range(0, len(events), 1000):
        result = ingest(
            db,
            tenant_id,
            events[start : start + 1000],
            now=now,
            source_type="DEMO",
            strict_authorization=True,
            commit=False,
            bulk=True,
        )
        accepted += result["accepted"]
    # Replay only missing current-time buckets; refresh() refuses to rewind/overwrite.
    point = bucket_for(earliest) + timedelta(minutes=5)
    evaluated = 0
    while point <= bucket:
        evaluated += refresh(db, tenant_id, now=point, commit=False)["created"]
        point += timedelta(minutes=5)
    if not events:
        evaluated += refresh(db, tenant_id, now=now, commit=False)["created"]
    db.commit()
    return {"accepted": accepted, "evaluated": evaluated, "bucket": bucket.isoformat()}
