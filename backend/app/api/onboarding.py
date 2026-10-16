"""Authenticated raw-file transport; validation/persistence live in ingestion services."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.api.auth import Principal, operator, principal
from app.db.session import get_db
from app.ingestion.uploads import commit_upload, preview_upload, read_upload
from app.schemas.ingestion import IngestResult, UploadPreview
from app.schemas.onboarding import DataSourcesOut
from app.services import operations
from app.services.data_sources import data_sources

router = APIRouter(tags=["Data onboarding"])
Db = Annotated[Session, Depends(get_db)]
Operator = Annotated[Principal, Depends(operator)]
Reader = Annotated[Principal, Depends(principal)]

BODY = {
    "requestBody": {
        "required": True,
        "content": {
            mime: {"schema": {"type": "string", "format": "binary"}}
            for mime in ("text/csv", "application/json", "application/x-ndjson")
        },
    }
}


@router.post("/api/imports/preview", response_model=UploadPreview, openapi_extra=BODY)
async def preview(
    request: Request,
    user: Operator,
    db: Db,
    format: str = Query(...),
    tenant_id: str | None = None,
):
    """Validate up to 1,000 records / 2 MiB without writes. Only workspace operators, never ingestion keys. Tenant mismatch/unknown integrations block confirmation."""
    tenant = operations.scope(user.tenant_id, tenant_id)
    operations.require_tenant(db, tenant)
    data = await read_upload(
        request.stream(), format, request.headers.get("content-type", "")
    )
    return preview_upload(db, tenant, data, format)


@router.post("/api/imports/commit", response_model=IngestResult, openapi_extra=BODY)
async def commit(
    request: Request,
    user: Operator,
    db: Db,
    format: str = Query(...),
    tenant_id: str | None = None,
    x_confirm_import: str | None = Header(default=None),
    x_preview_digest: str | None = Header(default=None),
):
    """Resubmit the previewed file with X-Confirm-Import: true and X-Preview-Digest. Revalidates scope/duplicates at commit. Historical records allowed; completed health windows are never rewritten."""
    tenant = operations.scope(user.tenant_id, tenant_id)
    operations.require_tenant(db, tenant)
    data = await read_upload(
        request.stream(), format, request.headers.get("content-type", "")
    )
    return commit_upload(db, tenant, data, format, x_confirm_import, x_preview_digest)


@router.get("/api/data-sources", response_model=DataSourcesOut)
def sources(user: Reader, db: Db, tenant_id: str | None = None):
    tenant = operations.scope(user.tenant_id, tenant_id)
    return data_sources(db, tenant, operations.integration_items(db, tenant))
