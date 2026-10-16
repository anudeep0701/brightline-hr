"""Trusted administration of tenant-scoped, ingestion-only credentials.

DATABASE_URL comes from the existing process configuration, never an env file.
Rotate by creating a replacement, updating the exporter, then revoking the old ID.
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.migrations import run_command
from app.db.session import get_engine
from app.ingestion.credentials import issue_key, revoke_key
from app.models.entities import IngestionAPIKey, Tenant


def metadata(key):
    """Explicit allowlist: never serialize the stored credential digest."""
    return dict(
        id=key.id,
        tenant_id=key.tenant_id,
        name=key.name,
        created_at=key.created_at.isoformat(),
        revoked_at=key.revoked_at.isoformat() if key.revoked_at else None,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create", help="Issue a key for an existing tenant; display its secret once"
    )
    create.add_argument("tenant", help="Existing tenant ID")
    create.add_argument(
        "--name", required=True, help="Exporter label (1–100 characters)"
    )
    listing = commands.add_parser(
        "list", help="List one tenant's safe key metadata, including revoked keys"
    )
    listing.add_argument("tenant", help="Existing tenant ID")
    revoke = commands.add_parser(
        "revoke", help="Revoke a public key ID; repeated revocation is harmless"
    )
    revoke.add_argument(
        "key_id", help="Public key ID from create/list; never the secret"
    )
    args = parser.parse_args(argv)

    with Session(get_engine(), expire_on_commit=False) as db:
        if args.command == "create":
            key, secret = issue_key(db, args.tenant, args.name)
            # issue_key commits before returning. Never disclose an unpersisted key.
            print(json.dumps({**metadata(key), "secret": secret}, indent=2))
            print(
                "Save the entire secret privately now; it cannot be retrieved later. "
                "Only its hash is stored. Use the public ID for revocation.",
                file=sys.stderr,
            )
        elif args.command == "list":
            if db.get(Tenant, args.tenant) is None:
                raise ValueError("Tenant not found; provision the tenant first")
            keys = db.scalars(
                select(IngestionAPIKey)
                .where(IngestionAPIKey.tenant_id == args.tenant)
                .order_by(IngestionAPIKey.created_at, IngestionAPIKey.id)
            )
            print(json.dumps([metadata(key) for key in keys], indent=2))
        else:
            key = revoke_key(db, args.key_id)
            print(json.dumps(metadata(key), indent=2))


if __name__ == "__main__":
    run_command(main)
