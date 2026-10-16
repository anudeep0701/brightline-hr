"""Trusted server-side tenant/token provisioning; reads secrets from hidden input."""

import argparse
import getpass
import hashlib
import secrets
import sys
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.migrations import run_command
from app.db.session import get_engine
from app.health.config import DEFAULT_POLICY
from app.ingestion.credentials import KEY_PREFIX
from app.models.entities import AccessToken, Integration, Tenant


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--generate-token",
        action="store_true",
        help="Generate a secure token and display it once after persistence succeeds",
    )
    parser.add_argument("tenant")
    parser.add_argument("name")
    parser.add_argument("--role", choices=["reader", "operator"], default="operator")
    parser.add_argument("--integration", help="Optional integration ID")
    parser.add_argument(
        "--latency-target-ms", type=int, default=DEFAULT_POLICY.latency_target_ms
    )
    parser.add_argument(
        "--max-gap-minutes", type=int, default=DEFAULT_POLICY.max_gap_minutes
    )
    args = parser.parse_args(argv)
    if args.latency_target_ms <= 0 or args.max_gap_minutes <= 0:
        parser.error("Targets must be positive")
    secret = (
        secrets.token_urlsafe(32)
        if args.generate_token
        else getpass.getpass(
            "Paste a randomly generated workspace bearer token (32+ characters): "
        )
    )
    if secret.startswith(KEY_PREFIX):
        raise SystemExit(
            "Ingestion keys cannot be provisioned as workspace credentials"
        )
    if len(secret) < 32:
        raise SystemExit("Token must contain at least 32 characters")
    with Session(get_engine()) as db:
        if not db.get(Tenant, args.tenant):
            db.add(Tenant(id=args.tenant, name=args.name))
            db.flush()
        digest = hashlib.sha256(secret.encode()).hexdigest()
        if db.get(AccessToken, digest):
            raise SystemExit("Token is already assigned; generate a unique token")
        db.add(AccessToken(digest=digest, tenant_id=args.tenant, role=args.role))
        if args.integration and not db.get(
            Integration, (args.tenant, args.integration)
        ):
            db.add(
                Integration(
                    tenant_id=args.tenant,
                    id=args.integration,
                    name=args.integration,
                    category="Custom",
                    owner="Operations",
                    latency_target_ms=args.latency_target_ms,
                    max_gap_minutes=args.max_gap_minutes,
                )
            )
        db.commit()
    print("Provisioned tenant access. Only a SHA-256 digest was stored.")

    if args.generate_token:
        print(f"Workspace: {args.tenant} · Role: {args.role}")
        print(
            "Save this token privately, then paste it into Workspace access → Workspace bearer token → Connect. It cannot be retrieved later:"
        )
        print(secret)


if __name__ == "__main__":
    run_command(main)
