"""Explicit public assessment access, separate from workspace and exporter keys.

Stateless HMAC sessions work across serverless instances. They grant a small
capability set for one configured tenant, never general workspace credentials.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.models.entities import Tenant
from app.schemas.demo import DemoCapabilities, DemoRefresh, DemoSession
from app.services.demo_data import refresh_demo_data

COOKIE_NAME = "__Host-brightline_demo"
SESSION_SECONDS = 3600
SIGNING_CONTEXT = b"brightline-demo-session-v1:"
router = APIRouter(tags=["Demo workspace"])


def demo_tenant(db, settings):
    if not settings.demo_mode:
        raise HTTPException(404, "Demo workspace is not enabled")
    tenant = db.get(Tenant, settings.demo_tenant_slug)
    if tenant is None:
        raise HTTPException(
            503,
            "Demo workspace is unavailable. Ask the deployment owner to check demo setup.",
        )
    return tenant


def same_origin(request, settings):
    """Custom header forces preflight; production grants no cross-origin demo writes."""
    if request.headers.get("x-demo-request") != "1":
        raise HTTPException(403, "Demo requests require the same-origin application")
    origin = request.headers.get("origin")
    # TLS may terminate at Vercel before ASGI. Compare the browser origin's host
    # with Host, not an untrusted forwarded header or the internal HTTP scheme.
    try:
        parsed = urlsplit(origin or "")
    except ValueError:
        raise HTTPException(403, "Invalid demo request origin") from None
    matches_host = (
        parsed.netloc == request.url.netloc
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )
    local_origin = settings.app_env != "production" and origin in settings.cors_origins
    if (origin and not matches_host and not local_origin) or request.headers.get(
        "sec-fetch-site"
    ) == "cross-site":
        raise HTTPException(403, "Cross-site demo requests are not allowed")
    schemes = {"https"} if settings.app_env == "production" else {"http", "https"}
    if origin and parsed.scheme not in schemes:
        raise HTTPException(403, "Invalid demo request origin")


def sign_session(tenant_id, settings):
    now = int(time.time())
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "tenant": tenant_id,
                "iat": now,
                "exp": now + SESSION_SECONDS,
                "nonce": secrets.token_urlsafe(16),
            },
            separators=(",", ":"),
        ).encode()
    ).rstrip(b"=")
    signature = hmac.new(
        settings.demo_session_secret.encode(), SIGNING_CONTEXT + payload, hashlib.sha256
    ).hexdigest()
    return payload.decode() + "." + signature, now + SESSION_SECONDS


def authorize_demo(request, db, settings):
    if not settings.demo_mode:
        raise HTTPException(401, "Workspace authentication required")
    value = request.cookies.get(COOKIE_NAME, "")
    try:
        if len(value) > 2048:
            raise ValueError
        payload, signature = value.split(".")
        expected = hmac.new(
            settings.demo_session_secret.encode(),
            SIGNING_CONTEXT + payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        now = int(time.time())
        if (
            type(data["iat"]) is not int
            or type(data["exp"]) is not int
            or not data["iat"] <= now < data["exp"]
            or data["exp"] - data["iat"] != SESSION_SECONDS
            or data["tenant"] != settings.demo_tenant_slug
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(
            401, "Demo session expired or invalid. Reopen the demo workspace."
        ) from None
    tenant = demo_tenant(db, settings)
    if request.query_params.get("tenant_id", tenant.id) != tenant.id:
        raise HTTPException(403, "Demo access is limited to its configured workspace")
    path = request.url.path
    reads = (
        path
        in {
            "/api/workspace",
            "/api/v1/dashboard",
            "/api/health-summary",
            "/api/integrations",
            "/api/data-sources",
        }
        or re.fullmatch(r"/api/integrations/[^/]+(?:/(?:metrics|incidents))?", path)
        or re.fullmatch(r"/api/v1/integrations/[^/]+(?:/config)?", path)
    )
    writes = (
        path in {"/api/evaluate", "/api/v1/refresh", "/api/demo/refresh"}
        or (
            settings.demo_allow_file_import
            and path in {"/api/imports/preview", "/api/imports/commit"}
        )
        or re.fullmatch(r"/api/integrations/[^/]+/(?:brief|explain|investigate)", path)
        or re.fullmatch(r"/api/v1/integrations/[^/]+/explanation", path)
    )
    if request.method == "GET" and reads:
        return tenant.id
    if request.method == "POST" and writes:
        same_origin(request, settings)
        return tenant.id
    raise HTTPException(
        403,
        "This action requires a workspace credential; demo access is limited to observation, evaluation and advisory assistance",
    )


@router.get(
    "/api/demo/session",
    response_model=DemoCapabilities,
    response_model_exclude_defaults=True,
)
def demo_configuration(response: Response):
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    return {
        "demo_mode": settings.demo_mode,
        "demo_allow_file_import": settings.demo_mode
        and settings.demo_allow_file_import,
    }


@router.post("/api/demo/session", response_model=DemoSession)
def create_demo_session(
    request: Request, response: Response, db: Session = Depends(get_db)
):
    settings = get_settings()
    tenant = demo_tenant(db, settings)
    same_origin(request, settings)
    refresh_demo_data(db, settings)
    # No tenant selector, workspace token, credentials table write or secret in JSON.
    cookie, expires_at = sign_session(tenant.id, settings)
    response.set_cookie(
        COOKIE_NAME,
        cookie,
        max_age=SESSION_SECONDS,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "demo_mode": True,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "expires_at": expires_at,
    }


@router.post("/api/demo/refresh", response_model=DemoRefresh)
def refresh_demo(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    authorize_demo(request, db, settings)
    return refresh_demo_data(db, settings, force=True)
