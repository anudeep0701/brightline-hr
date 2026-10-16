"""High-entropy, tenant-scoped ingestion credentials. Plaintext is never persisted."""

import hashlib
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.entities import IngestionAPIKey, Tenant

KEY_PREFIX = "bl_ingest_"
KEY_PATTERN = re.compile(r"bl_ingest_[A-Za-z0-9_-]{43}")


def key_digest(secret: str) -> str:
    # Domain separation keeps these hashes distinct from workspace token hashes.
    return hashlib.sha256(
        b"brightline-ingestion-v1\0" + secret.encode("utf-8")
    ).hexdigest()


def authenticate_key(session, secret: str):
    if not KEY_PATTERN.fullmatch(secret):
        return None
    return session.scalar(
        select(IngestionAPIKey).where(
            IngestionAPIKey.digest == key_digest(secret),
            IngestionAPIKey.revoked_at.is_(None),
        )
    )


def issue_key(session, tenant_id: str, name: str):
    if not name.strip() or len(name) > 100:
        raise ValueError("Key name must contain 1 to 100 characters")
    if session.get(Tenant, tenant_id) is None:
        raise ValueError(
            "Tenant not found; provision the tenant before issuing ingestion credentials"
        )
    secret = KEY_PREFIX + secrets.token_urlsafe(32)
    key = IngestionAPIKey(
        tenant_id=tenant_id, name=name.strip(), digest=key_digest(secret)
    )
    session.add(key)
    session.commit()
    return key, secret


def revoke_key(session, key_id: str):
    key = session.get(IngestionAPIKey, key_id)
    if key is None:
        raise ValueError("Ingestion key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return key
