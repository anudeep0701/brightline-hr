import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api.onboarding import router as onboarding_router
from app.api.public import router as public_router
from app.api.routes import router
from app.config import get_settings
from app.ingestion.errors import IngestionBatchError
from app.services.errors import ServiceError

settings = get_settings()
app = FastAPI(
    title="Brightline HR Integration Health API",
    version="0.3.0",
    description="""Tenant-scoped operational health for payroll, e-signature, ATS,
    directory and notification integrations. Deterministic health decisions with
    auditable evidence and optional AI assistance. Supply an opaque workspace bearer
    token using Authorize. External exporters use an ingestion-only key on /api/ingest.
    Readers can inspect; operators can ingest, evaluate and
    explain. Health states are uppercase, rates are fractions and latency is in ms.
    Time bounds use timezone-aware ISO-8601 and half-open [start_time, end_time) ranges.
    Local demo mode alone permits credential-free access to the seeded demo tenant.
    """,
    openapi_tags=[
        {"name": "Probes", "description": "Public liveness and storage readiness."},
        {
            "name": "Health",
            "description": "Deterministic health summaries and evaluation.",
        },
        {
            "name": "Integrations",
            "description": "Tenant-scoped integration evidence and metric history.",
        },
        {
            "name": "Incidents",
            "description": "Confirmed incidents and recovery history.",
        },
        {
            "name": "Ingestion",
            "description": "Partial batch acceptance and database-enforced idempotency.",
        },
        {
            "name": "Assistance",
            "description": "Optional enrichment; never a health decision source.",
        },
        {
            "name": "Compatibility",
            "description": "Existing /api/v1 frontend contracts.",
        },
        {"name": "Scheduler", "description": "CRON_SECRET-protected refresh."},
    ],
)
# Same-origin production needs no CORS grants. Local two-port development retains
# its exact localhost origin; optional explicit production origins remain validated.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Confirm-Import",
            "X-Preview-Digest",
        ],
        allow_credentials=False,
    )
app.include_router(public_router)
app.include_router(router)
app.include_router(onboarding_router)


@app.exception_handler(ServiceError)
def service_error(request: Request, exc: ServiceError):
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.message, "code": exc.code}
    )


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException):
    codes = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict"}
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "detail": str(exc.detail),
            "code": codes.get(exc.status_code, "request_failed"),
        },
    )


@app.exception_handler(SQLAlchemyError)
def database_error(request: Request, exc: SQLAlchemyError):
    logging.getLogger(__name__).error("Database operation failed")
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Storage unavailable; verify connectivity and database migrations",
            "code": "storage_unavailable",
        },
    )


@app.exception_handler(RequestValidationError)
def invalid_request(request: Request, exc: RequestValidationError):
    # Never echo raw payloads, query values or validation exception strings.
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid request. Check query parameters, timezone-aware timestamps, JSON structure and batch size (1–1000).",
            "code": "invalid_request",
        },
    )


@app.exception_handler(Exception)
def unexpected_error(request: Request, exc: Exception):
    logging.getLogger(__name__).error("Unexpected application error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "internal_error"},
    )


@app.exception_handler(IngestionBatchError)
def ingestion_batch_error(request: Request, exc: IngestionBatchError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            **exc.result.model_dump(mode="json"),
            "detail": exc.detail,
            "code": exc.code,
        },
    )
