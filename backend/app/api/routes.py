"""Compatibility routes for the existing frontend and scheduler."""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import Principal, operator, principal
from app.api.public import ERRORS
from app.config import get_settings
from app.db.session import get_db
from app.health.config import HealthPolicy
from app.schemas.api import CronOut
from app.schemas.contracts import (
    DashboardOut,
    DetailOut,
    EnrichmentOut,
    LogBatch,
    RefreshOut,
)
from app.schemas.ingestion import IngestResult, RequestBatch
from app.services import operations

router = APIRouter(tags=["Compatibility"], responses=ERRORS)


@router.get("/api/v1/dashboard", response_model=DashboardOut)
def dashboard(user: Principal = Depends(principal), db: Session = Depends(get_db)):
    return operations.dashboard(db, user.tenant_id, get_settings())


@router.get("/api/v1/integrations/{integration_id}", response_model=DetailOut)
def detail(
    integration_id: str,
    user: Principal = Depends(principal),
    db: Session = Depends(get_db),
):
    return operations.detail(db, user.tenant_id, integration_id)


@router.get("/api/v1/integrations/{integration_id}/config", response_model=HealthPolicy)
def read_config(
    integration_id: str,
    user: Principal = Depends(principal),
    db: Session = Depends(get_db),
):
    return operations.read_config(db, user.tenant_id, integration_id)


@router.put("/api/v1/integrations/{integration_id}/config", response_model=HealthPolicy)
def replace_config(
    integration_id: str,
    policy: HealthPolicy,
    user: Principal = Depends(operator),
    db: Session = Depends(get_db),
):
    return operations.replace_config(db, user.tenant_id, integration_id, policy)


@router.post("/api/v1/logs", response_model=IngestResult)
def logs(
    batch: LogBatch, user: Principal = Depends(operator), db: Session = Depends(get_db)
):
    return operations.ingest_batch(db, user.tenant_id, batch)


@router.post("/api/v1/request-events", response_model=IngestResult)
def request_events(
    batch: RequestBatch,
    user: Principal = Depends(operator),
    db: Session = Depends(get_db),
):
    return operations.ingest_batch(db, user.tenant_id, batch)


@router.post("/api/v1/refresh", response_model=RefreshOut)
def refresh_route(user: Principal = Depends(operator), db: Session = Depends(get_db)):
    return operations.evaluate(db, user.tenant_id)


@router.post(
    "/api/v1/integrations/{integration_id}/explanation", response_model=EnrichmentOut
)
def explanation(
    integration_id: str,
    user: Principal = Depends(operator),
    db: Session = Depends(get_db),
):
    return operations.explanation(db, user.tenant_id, integration_id, get_settings())


@router.get("/api/cron/refresh", response_model=CronOut, tags=["Scheduler"])
def cron(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
):
    secret = get_settings().cron_secret
    if not secret or not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(401, "Invalid cron authorization")
    return operations.refresh_all(db)
