import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.enrichment import explain
from app.api.auth import Principal, operator, principal
from app.config import get_settings
from app.db.session import get_db
from app.health.service import refresh
from app.ingestion.service import ingest
from app.metrics.calculation import utc
from app.models.entities import Incident, Integration, RequestLog, Snapshot, Tenant
from app.schemas.contracts import (
    DashboardOut,
    DetailOut,
    EnrichmentOut,
    IngestOut,
    LogBatch,
    RefreshOut,
)

router = APIRouter()


def serialize(model):
    if model is None:
        return None
    return {
        column.name: (utc(value).isoformat() if isinstance(value, datetime) else value)
        for column in model.__table__.columns
        if (value := getattr(model, column.name)) is not None
    }


def integration_or_404(db, tenant_id, integration_id):
    item = db.get(Integration, (tenant_id, integration_id))
    if item is None:
        raise HTTPException(404, "Integration not found")
    return item


def latest_snapshot(db, tenant_id, integration_id):
    return db.scalar(
        select(Snapshot)
        .where(
            Snapshot.tenant_id == tenant_id, Snapshot.integration_id == integration_id
        )
        .order_by(Snapshot.bucket.desc())
        .limit(1)
    )


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/api/v1/dashboard", response_model=DashboardOut)
def dashboard(user: Principal = Depends(principal), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(503, "Initialize database and seed a tenant first")
    items = []
    now = datetime.now(timezone.utc)
    for item in db.scalars(
        select(Integration).where(Integration.tenant_id == user.tenant_id)
    ):
        snapshot = latest_snapshot(db, user.tenant_id, item.id)
        items.append(
            dict(
                integration=serialize(item),
                snapshot=serialize(snapshot),
                stale=snapshot is None
                or now - utc(snapshot.bucket) > timedelta(minutes=10),
            )
        )
    incidents = db.scalars(
        select(Incident)
        .where(Incident.tenant_id == user.tenant_id, Incident.resolved_at.is_(None))
        .order_by(Incident.opened_at.desc())
    ).all()
    return dict(
        tenant=tenant.name,
        mode=get_settings().app_env,
        server_time=now.isoformat(),
        refresh_seconds=300,
        integrations=items,
        incidents=[serialize(x) for x in incidents],
    )


@router.get("/api/v1/integrations/{integration_id}", response_model=DetailOut)
def detail(
    integration_id: str,
    user: Principal = Depends(principal),
    db: Session = Depends(get_db),
):
    item = integration_or_404(db, user.tenant_id, integration_id)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    history = db.scalars(
        select(Snapshot)
        .where(
            Snapshot.tenant_id == user.tenant_id,
            Snapshot.integration_id == item.id,
            Snapshot.bucket >= since,
        )
        .order_by(Snapshot.bucket.desc())
        .limit(288)
    ).all()
    logs = db.scalars(
        select(RequestLog)
        .where(
            RequestLog.tenant_id == user.tenant_id, RequestLog.integration_id == item.id
        )
        .order_by(RequestLog.occurred_at.desc())
        .limit(50)
    ).all()
    incidents = db.scalars(
        select(Incident)
        .where(Incident.tenant_id == user.tenant_id, Incident.integration_id == item.id)
        .order_by(Incident.opened_at.desc())
        .limit(20)
    ).all()
    return dict(
        integration=serialize(item),
        snapshot=serialize(latest_snapshot(db, user.tenant_id, item.id)),
        history=[serialize(x) for x in history],
        logs=[serialize(x) for x in logs],
        incidents=[serialize(x) for x in incidents],
    )


@router.post("/api/v1/logs", response_model=IngestOut)
def logs(
    batch: LogBatch, user: Principal = Depends(operator), db: Session = Depends(get_db)
):
    return ingest(db, user.tenant_id, batch)


@router.post("/api/v1/refresh", response_model=RefreshOut)
def refresh_route(user: Principal = Depends(operator), db: Session = Depends(get_db)):
    return refresh(db, user.tenant_id)


@router.post(
    "/api/v1/integrations/{integration_id}/explanation", response_model=EnrichmentOut
)
def explanation(
    integration_id: str,
    user: Principal = Depends(operator),
    db: Session = Depends(get_db),
):
    integration_or_404(db, user.tenant_id, integration_id)
    snapshot = latest_snapshot(db, user.tenant_id, integration_id)
    if snapshot is None:
        raise HTTPException(409, "Evaluate health before requesting explanation")
    return serialize(explain(db, snapshot, get_settings()))


@router.get("/api/cron/refresh")
def cron(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
):
    secret = get_settings().cron_secret
    if not secret or not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(401, "Invalid cron authorization")
    tenants = db.scalars(select(Tenant.id).order_by(Tenant.id).limit(101)).all()
    if len(tenants) > 100:
        raise HTTPException(
            503, "MVP tenant capacity exceeded; partition scheduler before expanding"
        )
    return {"results": [refresh(db, tenant_id) for tenant_id in tenants]}
