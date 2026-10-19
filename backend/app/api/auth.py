import hashlib
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.demo import COOKIE_NAME, authorize_demo
from app.config import get_settings
from app.db.session import get_db
from app.ingestion.credentials import KEY_PREFIX, authenticate_key
from app.models.entities import AccessToken

bearer = HTTPBearer(
    auto_error=False,
    scheme_name="WorkspaceBearer",
    description="Opaque tenant-scoped workspace token; not an OpenAI API key. Readers inspect; operators may mutate.",
)


@dataclass
class Principal:
    tenant_id: str
    role: str
    demo: bool = False


def principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    if credentials is None and "authorization" not in request.headers:
        settings = get_settings()
        if settings.demo_mode and request.cookies.get(COOKIE_NAME):
            return Principal(
                authorize_demo(request, db, settings), "operator", demo=True
            )
    if (
        credentials is None
        and not get_settings().demo_mode
        and get_settings().app_env == "demo"
        and db.get_bind().dialect.name == "sqlite"
        and "authorization" not in request.headers
    ):
        # Only credential-free local demo mode can select other synthetic tenants.
        selected = request.query_params.get("tenant_id")
        return Principal(selected or "brightline", "operator")
    if credentials is None:
        raise HTTPException(
            401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
        )
    if credentials.credentials.startswith(KEY_PREFIX):
        key = authenticate_key(db, credentials.credentials)
        if key is None:
            raise HTTPException(
                401,
                "Invalid ingestion credential",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            403, "Ingestion credentials may only submit events to /api/ingest"
        )
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    token = db.get(AccessToken, digest)
    if token is None:
        raise HTTPException(
            401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    return Principal(token.tenant_id, token.role)


def operator(user: Principal = Depends(principal)):
    if user.role != "operator":
        raise HTTPException(403, "Operator role required")
    return user


ingestion_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="IngestionBearer",
    description="Tenant-scoped ingestion API key. Grants only POST /api/ingest. Existing workspace operator tokens are also accepted for compatibility.",
)


def ingestion_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(ingestion_bearer),
    db: Session = Depends(get_db),
):
    if credentials is None:
        if (
            not get_settings().demo_mode
            and get_settings().app_env == "demo"
            and db.get_bind().dialect.name == "sqlite"
            and "authorization" not in request.headers
        ):
            return principal(request, credentials=None, db=db)
        raise HTTPException(
            401, "Ingestion credential required", headers={"WWW-Authenticate": "Bearer"}
        )
    if credentials.credentials.startswith(KEY_PREFIX):
        key = authenticate_key(db, credentials.credentials)
        if key is None:
            raise HTTPException(
                401,
                "Invalid ingestion credential",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return Principal(key.tenant_id, "ingestion")
    return operator(principal(request, credentials=credentials, db=db))
