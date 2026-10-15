import hashlib
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.models.entities import AccessToken

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    tenant_id: str
    role: str


def principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    if credentials is None and get_settings().app_env == "demo":
        return Principal("brightline", "operator")
    if credentials is None:
        raise HTTPException(401, "Bearer token required")
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    token = db.get(AccessToken, digest)
    if token is None:
        raise HTTPException(401, "Invalid bearer token")
    return Principal(token.tenant_id, token.role)


def operator(user: Principal = Depends(principal)):
    if user.role != "operator":
        raise HTTPException(403, "Operator role required")
    return user
