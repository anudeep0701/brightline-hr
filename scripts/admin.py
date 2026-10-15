"""Trusted server-side tenant/token provisioning; reads secrets from hidden input."""

import argparse
import getpass
import hashlib
import sys
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.session import get_engine
from app.models.entities import AccessToken, Integration, Tenant

parser = argparse.ArgumentParser()
parser.add_argument("tenant")
parser.add_argument("name")
parser.add_argument("--role", choices=["reader", "operator"], default="operator")
parser.add_argument("--integration", help="Optional integration ID")
parser.add_argument("--latency-target-ms", type=int, default=1000)
parser.add_argument("--max-gap-minutes", type=int, default=30)
args = parser.parse_args()
if args.latency_target_ms <= 0 or args.max_gap_minutes <= 0:
    parser.error("Targets must be positive")
secret = getpass.getpass(
    "Paste a randomly generated workspace bearer token (32+ characters): "
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
    if args.integration and not db.get(Integration, (args.tenant, args.integration)):
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
