"""Tenant-scoped operational reads and orchestration; no FastAPI dependency."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.ai.incident_assistance import brief, generate
from app.health.config import DEFAULT_POLICY, HealthPolicy
from app.health.service import refresh
from app.incidents.context import incident_context
from app.metrics.calculation import utc
from app.models.entities import (
    Base,
    Enrichment,
    Incident,
    Integration,
    MetricRollup,
    RequestLog,
    Snapshot,
    Tenant,
)
from app.schemas.api import IntegrationFilters, TimeRange
from app.schemas.serialization import serialize, serialize_log
from app.services.errors import ServiceError
from app.services.freshness import freshness, latest_telemetry
from app.services.impact import operational_impact


def scope(tenant_id, requested=None):
    if requested is not None and requested != tenant_id:
        raise ServiceError(
            403, "tenant_forbidden", "Tenant filter must match the authenticated tenant"
        )
    return tenant_id


def require_tenant(db, tenant_id):
    item = db.get(Tenant, tenant_id)
    if item is None:
        raise ServiceError(
            503,
            "tenant_unavailable",
            "Provision the authenticated tenant before using the API",
        )
    return item


def integration_or_404(db, tenant_id, integration_id):
    item = db.get(Integration, (tenant_id, integration_id))
    if item is None:
        raise ServiceError(404, "integration_not_found", "Integration not found")
    return item


def in_range(statement, column, filters):
    if filters.start_time:
        statement = statement.where(column >= filters.start_time)
    if filters.end_time:
        statement = statement.where(column < filters.end_time)
    return statement


def latest_snapshot(db, tenant_id, integration_id):
    return db.scalar(
        select(Snapshot)
        .where(
            Snapshot.tenant_id == tenant_id,
            Snapshot.integration_id == integration_id,
        )
        .order_by(Snapshot.bucket.desc())
        .limit(1)
    )


def integration_items(db, tenant_id, filters=None):
    filters = filters or IntegrationFilters()
    scope(tenant_id, filters.tenant_id)
    require_tenant(db, tenant_id)
    statement = select(Integration).where(Integration.tenant_id == tenant_id)
    if filters.integration_type:
        statement = statement.where(
            func.lower(Integration.category) == filters.integration_type.lower()
        )
    integrations = db.scalars(
        statement.options(selectinload(Integration.config)).order_by(Integration.id)
    ).all()
    # Rank snapshots in SQL instead of querying once per integration or loading all history.
    snapshots = in_range(
        select(
            Snapshot.id.label("id"),
            func.row_number()
            .over(
                partition_by=Snapshot.integration_id,
                order_by=Snapshot.bucket.desc(),
            )
            .label("rank"),
        ).where(Snapshot.tenant_id == tenant_id),
        Snapshot.bucket,
        filters,
    ).subquery()
    recent = list(
        db.scalars(
            select(Snapshot)
            .join(
                snapshots,
                snapshots.c.id == Snapshot.id,
            )
            .where(snapshots.c.rank <= 2)
            .order_by(Snapshot.bucket.desc())
        )
    )
    latest = {}
    previous = {}
    for snapshot in recent:
        if snapshot.integration_id in latest:
            previous[snapshot.integration_id] = snapshot
        else:
            latest[snapshot.integration_id] = snapshot
    now = datetime.now(timezone.utc)
    telemetry = latest_telemetry(db, tenant_id)
    items = []
    for integration in integrations:
        snapshot = latest.get(integration.id)
        status = snapshot.status if snapshot else "UNKNOWN"
        if filters.health_status and filters.health_status != status:
            continue
        items.append(
            dict(
                freshness=freshness(
                    integration, snapshot, telemetry.get(integration.id), now
                ),
                integration=serialize(integration),
                snapshot=serialize(snapshot),
                previous_snapshot=serialize(previous.get(integration.id)),
                stale=snapshot is None
                or now - utc(snapshot.bucket)
                > timedelta(minutes=integration.config.refresh_minutes * 2),
            )
        )
    return items


def list_integrations(db, tenant_id, query):
    items = integration_items(db, tenant_id, query)
    return dict(
        tenant_id=tenant_id,
        total=len(items),
        limit=query.limit,
        offset=query.offset,
        items=items[query.offset : query.offset + query.limit],
    )


def incident_statement(tenant_id, integration_ids, filters):
    statement = select(Incident).where(
        Incident.tenant_id == tenant_id,
        Incident.integration_id.in_(integration_ids),
    )
    # Activity overlap, rather than only incidents that opened inside the range.
    if filters.start_time:
        statement = statement.where(
            or_(
                Incident.resolved_at.is_(None),
                Incident.resolved_at > filters.start_time,
            )
        )
    if filters.end_time:
        statement = statement.where(Incident.opened_at < filters.end_time)
    return statement


def health_summary(db, tenant_id, filters):
    items = integration_items(db, tenant_id, filters)
    counts = dict.fromkeys(("HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"), 0)
    evaluated = []
    current_counts = dict.fromkeys(counts, 0)
    for item in items:
        snapshot = item["snapshot"]
        counts[snapshot["status"] if snapshot else "UNKNOWN"] += 1
        current_counts[item["freshness"]["current_evidence_status"]] += 1
        if snapshot:
            evaluated.append(snapshot["evaluated_at"])
    incidents = incident_statement(
        tenant_id, [x["integration"]["id"] for x in items], filters
    ).where(Incident.resolved_at.is_(None))
    return dict(
        tenant_id=tenant_id,
        generated_at=datetime.now(timezone.utc),
        total_integrations=len(items),
        status_counts=counts,
        current_evidence_status_counts=current_counts,
        stale_integrations=sum(x["stale"] for x in items),
        open_incidents=db.scalar(
            select(func.count()).select_from(incidents.subquery())
        ),
        latest_evaluated_at=max(evaluated) if evaluated else None,
    )


def dashboard(db, tenant_id, settings):
    tenant = require_tenant(db, tenant_id)
    items = integration_items(db, tenant_id)
    now = datetime.now(timezone.utc)
    return dict(
        tenant=tenant.name,
        mode=settings.app_env,
        server_time=now,
        operational_impact=operational_impact(db, tenant_id, items, now),
        refresh_seconds=DEFAULT_POLICY.refresh_minutes * 60,
        integrations=items,
        incidents=[
            serialize(x)
            for x in db.scalars(
                select(Incident)
                .where(
                    Incident.tenant_id == tenant_id,
                    Incident.resolved_at.is_(None),
                )
                .order_by(Incident.opened_at.desc(), Incident.id)
            )
        ],
    )


def detail(db, tenant_id, integration_id, filters=None):
    filters = filters or TimeRange()
    scope(tenant_id, filters.tenant_id)
    item = integration_or_404(db, tenant_id, integration_id)
    history_filters = filters
    if filters.start_time is None and filters.end_time is None:
        history_filters = filters.model_copy(
            update={"start_time": datetime.now(timezone.utc) - timedelta(hours=24)}
        )
    history = (
        in_range(
            select(Snapshot).where(
                Snapshot.tenant_id == tenant_id,
                Snapshot.integration_id == item.id,
            ),
            Snapshot.bucket,
            history_filters,
        )
        .order_by(Snapshot.bucket.desc())
        .limit(288)
    )
    logs = (
        in_range(
            select(RequestLog).where(
                RequestLog.tenant_id == tenant_id,
                RequestLog.integration_id == item.id,
            ),
            RequestLog.occurred_at,
            filters,
        )
        .order_by(RequestLog.occurred_at.desc(), RequestLog.event_id)
        .limit(50)
    )
    incidents = (
        incident_statement(tenant_id, [item.id], filters)
        .order_by(Incident.opened_at.desc(), Incident.id)
        .limit(20)
    )
    # Latest remains the current decision; filters restrict the history collections only.
    current = latest_snapshot(db, tenant_id, item.id)
    cached = (
        db.scalar(
            select(Enrichment).where(
                Enrichment.tenant_id == tenant_id, Enrichment.snapshot_id == current.id
            )
        )
        if current
        else None
    )
    return dict(
        freshness=freshness(
            item, current, latest_telemetry(db, tenant_id, item.id).get(item.id)
        ),
        enrichment=serialize(cached),
        integration=serialize(item),
        snapshot=serialize(current),
        history=[serialize(x) for x in db.scalars(history)],
        logs=[serialize_log(x) for x in db.scalars(logs)],
        incidents=[serialize_incident(db, x) for x in db.scalars(incidents)],
    )


def history_page(db, tenant_id, integration_id, query, *, incidents=False):
    scope(tenant_id, query.tenant_id)
    integration_or_404(db, tenant_id, integration_id)
    if incidents:
        statement = incident_statement(tenant_id, [integration_id], query)
        if query.state == "OPEN":
            statement = statement.where(Incident.resolved_at.is_(None))
        elif query.state == "RESOLVED":
            statement = statement.where(Incident.resolved_at.is_not(None))
        ordering = (Incident.opened_at.desc(), Incident.id)
    else:
        statement = in_range(
            select(MetricRollup).where(
                MetricRollup.tenant_id == tenant_id,
                MetricRollup.integration_id == integration_id,
            ),
            MetricRollup.window_end,
            query,
        )
        ordering = (MetricRollup.window_end.desc(), MetricRollup.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    return dict(
        tenant_id=tenant_id,
        integration_id=integration_id,
        total=total,
        limit=query.limit,
        offset=query.offset,
        items=[
            serialize_incident(db, x) if incidents else serialize(x)
            for x in db.scalars(
                statement.order_by(*ordering).offset(query.offset).limit(query.limit)
            )
        ],
    )


def workspace_incidents(db, tenant_id, query):
    scope(tenant_id, query.tenant_id)
    require_tenant(db, tenant_id)
    ids = select(Integration.id).where(Integration.tenant_id == tenant_id)
    statement = incident_statement(tenant_id, ids, query)
    if query.state == "OPEN":
        statement = statement.where(Incident.resolved_at.is_(None))
    elif query.state == "RESOLVED":
        statement = statement.where(Incident.resolved_at.is_not(None))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    return dict(
        tenant_id=tenant_id,
        total=total,
        limit=query.limit,
        offset=query.offset,
        items=[
            serialize_incident(db, item)
            for item in db.scalars(
                statement.order_by(
                    Incident.resolved_at.is_not(None),
                    Incident.opened_at.desc(),
                    Incident.id,
                )
                .offset(query.offset)
                .limit(query.limit)
            )
        ],
    )


def explanation(db, tenant_id, integration_id, settings):
    integration_or_404(db, tenant_id, integration_id)
    snapshot = latest_snapshot(db, tenant_id, integration_id)
    if snapshot is None:
        raise ServiceError(
            409, "snapshot_required", "Evaluate health before requesting explanation"
        )
    result = serialize(brief(db, snapshot, settings))
    # Preserve the compatibility contract for already-insufficient decisions.
    # Stored briefs retain their full freshness warning and audit metadata.
    if result["source"] == "deterministic" and snapshot.status == "UNKNOWN":
        result["explanation"] = snapshot.reason_text
        result["report"] = {**result["report"], "summary": snapshot.reason_text}
    return result


def replace_config(db, tenant_id, integration_id, policy):
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    integration = integration_or_404(db, tenant_id, integration_id)
    for key, value in policy.model_dump().items():
        setattr(integration.config, key, value)
    db.commit()
    return policy


def evaluate(db, tenant_id):
    require_tenant(db, tenant_id)
    return refresh(db, tenant_id)


def refresh_all(db):
    tenants = db.scalars(select(Tenant.id).order_by(Tenant.id).limit(101)).all()
    if len(tenants) > 100:
        raise ServiceError(
            503,
            "scheduler_capacity",
            "MVP tenant capacity exceeded; partition scheduler before expanding",
        )
    return {"results": [refresh(db, tenant_id) for tenant_id in tenants]}


def readiness(db):
    db.execute(select(1)).scalar_one()
    # Verify every required table and column is accessible, including migrations.
    for table in Base.metadata.sorted_tables:
        db.execute(select(table).limit(0)).close()
    return {"status": "ready"}


def ingest_batch(db, tenant_id, batch, *, strict_authorization=False):
    from app.ingestion.service import ingest

    require_tenant(db, tenant_id)
    return ingest(db, tenant_id, batch, strict_authorization=strict_authorization)


def read_config(db, tenant_id, integration_id):
    return HealthPolicy.model_validate(
        integration_or_404(db, tenant_id, integration_id).config
    )


def workspace(db, tenant_id, role, mode, can_switch_tenants):
    current = require_tenant(db, tenant_id)
    tenants = (
        db.scalars(select(Tenant).order_by(Tenant.name, Tenant.id)).all()
        if can_switch_tenants
        else [current]
    )
    return dict(
        tenant_id=tenant_id,
        tenant_name=current.name,
        role=role,
        mode=mode,
        can_switch_tenants=can_switch_tenants,
        tenants=[dict(id=tenant.id, name=tenant.name) for tenant in tenants],
    )


def serialize_incident(db, incident):
    return {**serialize(incident), **incident_context(db, incident)}


def incident_brief(db, tenant_id, integration_id, settings):
    integration_or_404(db, tenant_id, integration_id)
    snapshot = latest_snapshot(db, tenant_id, integration_id)
    if snapshot is None:
        raise ServiceError(
            409, "snapshot_required", "Evaluate health before requesting a brief"
        )
    return serialize(brief(db, snapshot, settings))


def investigate(db, tenant_id, integration_id, request, settings):
    integration_or_404(db, tenant_id, integration_id)
    snapshot = latest_snapshot(db, tenant_id, integration_id)
    if snapshot is None:
        raise ServiceError(
            409, "snapshot_required", "Evaluate health before investigation"
        )
    incident = None
    if request.topic == "recovery":
        if not request.incident_id:
            raise ServiceError(
                422,
                "incident_required",
                "Select a resolved incident for recovery analysis",
            )
        incident = db.scalar(
            select(Incident).where(
                Incident.id == request.incident_id,
                Incident.tenant_id == tenant_id,
                Incident.integration_id == integration_id,
            )
        )
        if incident is None:
            raise ServiceError(404, "incident_not_found", "Incident not found")
        if incident.resolved_at is None:
            raise ServiceError(
                409,
                "incident_not_resolved",
                "Recovery analysis requires a resolved incident",
            )
        snapshot = db.scalar(
            select(Snapshot).where(
                Snapshot.id == incident.last_snapshot_id,
                Snapshot.tenant_id == tenant_id,
                Snapshot.integration_id == integration_id,
            )
        )
        if snapshot is None:
            raise ServiceError(
                409, "snapshot_required", "Resolution evidence is unavailable"
            )
    elif request.incident_id:
        raise ServiceError(
            422,
            "unexpected_incident",
            "Incident selection is supported only for recovery analysis",
        )
    result, _ = generate(db, snapshot, settings, request.topic, incident)
    return result
