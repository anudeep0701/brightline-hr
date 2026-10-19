"""Public API contracts. Application services own queries and health decisions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import Principal, ingestion_principal, operator, principal
from app.config import get_settings
from app.db.session import get_db
from app.schemas.api import (
    ErrorOut,
    HealthSummaryOut,
    HistoryQuery,
    IncidentHistoryOut,
    IncidentQuery,
    IntegrationFilters,
    IntegrationListOut,
    IntegrationListQuery,
    MetricsHistoryOut,
    ProbeOut,
    TimeRange,
    WorkspaceIncidentsOut,
    WorkspaceOut,
)
from app.schemas.contracts import DetailOut, EnrichmentOut, RefreshOut
from app.schemas.enrichment import InvestigationOut, InvestigationRequest
from app.schemas.ingestion import IngestFailure, IngestResult, RequestBatch
from app.services import operations

ERRORS = {status: {"model": ErrorOut} for status in (401, 403, 404, 409, 422, 500, 503)}
router = APIRouter(responses=ERRORS)
Db = Annotated[Session, Depends(get_db)]
Reader = Annotated[Principal, Depends(principal)]
Operator = Annotated[Principal, Depends(operator)]
TenantFilter = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=64,
        description="Must match the authenticated tenant; never grants cross-tenant access.",
    ),
]


@router.get(
    "/healthz",
    response_model=ProbeOut,
    tags=["Probes"],
    summary="Check process liveness",
)
def healthz():
    """Public liveness check. Does not contact storage or OpenAI."""
    return {"status": "ok"}


@router.get(
    "/readyz",
    response_model=ProbeOut,
    tags=["Probes"],
    summary="Check database and schema readiness",
)
def readyz(db: Db):
    """Public, read-only database/table/column check. Returns 503 if storage is unavailable or migrations are missing. No credentials or provider checks."""
    return operations.readiness(db)


@router.get(
    "/api/health-summary",
    response_model=HealthSummaryOut,
    tags=["Health"],
    summary="Summarize integration health",
)
def health_summary(
    filters: Annotated[IntegrationFilters, Query()], user: Reader, db: Db
):
    """Count latest decisions per integration, or latest within the supplied time range. Unevaluated integrations count as UNKNOWN. Filters apply before counting; open incidents are currently unresolved incidents overlapping the range."""
    return operations.health_summary(db, user.tenant_id, filters)


@router.get(
    "/api/integrations",
    response_model=IntegrationListOut,
    tags=["Integrations"],
    summary="List integrations and latest evidence",
)
def integrations(
    filters: Annotated[IntegrationListQuery, Query()], user: Reader, db: Db
):
    """Paginated, stable integration-ID order. Health states are uppercase; integration type matches category case-insensitively. total is measured after filtering and before pagination."""
    return operations.list_integrations(db, user.tenant_id, filters)


@router.get(
    "/api/integrations/{integration_id}",
    response_model=DetailOut,
    tags=["Integrations"],
    summary="Inspect one integration",
)
def integration_detail(
    integration_id: str, filters: Annotated[TimeRange, Query()], user: Reader, db: Db
):
    """Current snapshot plus bounded history (288), sanitized logs (50) and incidents (20). Time filters restrict history collections; the current snapshot remains current. Without time bounds, snapshot history defaults to 24 hours."""
    return operations.detail(db, user.tenant_id, integration_id, filters)


@router.get(
    "/api/integrations/{integration_id}/metrics",
    response_model=MetricsHistoryOut,
    tags=["Integrations"],
    summary="Read calculated metric history",
)
def metrics(
    integration_id: str, filters: Annotated[HistoryQuery, Query()], user: Reader, db: Db
):
    """Persisted rollups, newest first. [start_time, end_time) filters window_end. Returns an empty collection before the first evaluation; never computes metrics on a read."""
    return operations.history_page(db, user.tenant_id, integration_id, filters)


@router.get(
    "/api/integrations/{integration_id}/incidents",
    response_model=IncidentHistoryOut,
    tags=["Incidents"],
    summary="Read incident history",
)
def incidents(
    integration_id: str,
    filters: Annotated[IncidentQuery, Query()],
    user: Reader,
    db: Db,
):
    """Newest first; time bounds match incident activity overlap. Optional state is OPEN or RESOLVED. All timestamps require a timezone and are returned in UTC."""
    return operations.history_page(
        db, user.tenant_id, integration_id, filters, incidents=True
    )


@router.get(
    "/api/incidents",
    response_model=WorkspaceIncidentsOut,
    tags=["Incidents"],
    summary="Read authorized workspace incidents",
)
def workspace_incidents(
    filters: Annotated[IncidentQuery, Query()], user: Reader, db: Db
):
    """Read-only paginated incident activity; active first, then resolved. Tenant scope comes from workspace authorization."""
    return operations.workspace_incidents(db, user.tenant_id, filters)


@router.post(
    "/api/ingest",
    response_model=IngestResult,
    tags=["Ingestion"],
    summary="Ingest an authenticated external event batch",
    responses={
        403: {"model": ErrorOut | IngestFailure},
        422: {"model": ErrorOut | IngestFailure},
    },
)
def ingest(
    batch: RequestBatch,
    user: Annotated[Principal, Depends(ingestion_principal)],
    db: Db,
    tenant_id: TenantFilter = None,
):
    """Accept 1–1000 events using a tenant-scoped ingestion key. Invalid records are rejected individually; entirely invalid external batches return 422. Any unauthorized tenant/integration in an external batch returns 403 before writes. Retries are idempotent by tenant/request ID. Existing workspace operators and local SQLite demo clients remain supported."""
    return operations.ingest_batch(
        db,
        operations.scope(user.tenant_id, tenant_id),
        batch,
        strict_authorization=user.role == "ingestion",
    )


@router.post(
    "/api/evaluate",
    response_model=RefreshOut,
    tags=["Health"],
    summary="Evaluate the current health window",
)
def evaluate(user: Operator, db: Db, tenant_id: TenantFilter = None):
    """Evaluate all integrations in the authenticated tenant at server time, respecting each configured cadence. Repeated requests are idempotent within a bucket. No historical-time override or AI call."""
    return operations.evaluate(db, operations.scope(user.tenant_id, tenant_id))


@router.post(
    "/api/integrations/{integration_id}/explain",
    response_model=EnrichmentOut,
    tags=["Assistance"],
    summary="Explain persisted evidence",
)
def explain(
    integration_id: str, user: Operator, db: Db, tenant_id: TenantFilter = None
):
    """Optional structured OpenAI enrichment of the latest snapshot. Missing credentials or provider failure return deterministic reason_text. Requires a prior evaluation; never changes health or incident state."""
    return operations.explanation(
        db, operations.scope(user.tenant_id, tenant_id), integration_id, get_settings()
    )


@router.get(
    "/api/workspace",
    response_model=WorkspaceOut,
    tags=["Integrations"],
    summary="Read authorized tenant options",
)
def workspace(request: Request, user: Reader, db: Db, tenant_id: TenantFilter = None):
    """Workspace identity/role and authorized tenants. Only credential-free local demo mode lists all synthetic tenants; tokens and production remain confined to one tenant."""
    operations.scope(user.tenant_id, tenant_id)
    settings = get_settings()
    return operations.workspace(
        db,
        user.tenant_id,
        user.role,
        settings.app_env,
        settings.app_env == "demo"
        and not user.demo
        and db.get_bind().dialect.name == "sqlite"
        and not request.headers.get("authorization"),
    )


@router.post(
    "/api/integrations/{integration_id}/brief",
    response_model=EnrichmentOut,
    tags=["Assistance"],
    summary="Generate a grounded AI incident brief",
)
def incident_brief(
    integration_id: str, user: Operator, db: Db, tenant_id: TenantFilter = None
):
    """AI prioritizes allowlisted telemetry facts/checks; deterministic fallback on missing/invalid AI. No health or incident mutations."""
    return operations.incident_brief(
        db, operations.scope(user.tenant_id, tenant_id), integration_id, get_settings()
    )


@router.post(
    "/api/integrations/{integration_id}/investigate",
    response_model=InvestigationOut,
    tags=["Assistance"],
    summary="Ask a focused question about this integration",
)
def investigate(
    integration_id: str,
    body: InvestigationRequest,
    user: Operator,
    db: Db,
    tenant_id: TenantFilter = None,
):
    """Fixed investigation topics only, no arbitrary chat or tools. Recovery requires a tenant-owned resolved incident. Answers expose audit metadata without storing conversations."""
    return operations.investigate(
        db,
        operations.scope(user.tenant_id, tenant_id),
        integration_id,
        body,
        get_settings(),
    )
