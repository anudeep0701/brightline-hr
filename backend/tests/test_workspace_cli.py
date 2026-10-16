"""Trusted provisioning uses isolated synthetic databases; no developer env files."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from app.models.entities import AccessToken, Base, Integration, Tenant
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_generated_workspace_token_is_once_displayed_and_hash_only(tmp_path):
    root = Path(__file__).resolve().parents[2]
    url = "sqlite:///" + str(tmp_path / "workspace-test.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="brightline", name="Existing demo"))
        db.flush()
        db.add(
            Integration(
                tenant_id="brightline",
                id="payroll",
                name="Payroll",
                category="Payroll",
                owner="Ops",
            )
        )
        db.commit()
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    env.pop("OPENAI_API_KEY", None)
    env.pop("VERCEL", None)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/admin.py",
            "brightline",
            "Ignored replacement name",
            "--generate-token",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, "Workspace CLI failed on an isolated test database"
    token = result.stdout.strip().splitlines()[-1]
    assert len(token) >= 32 and not token.startswith("bl_ingest_")
    with Session(engine) as db:
        rows = db.scalars(select(AccessToken)).all()
        assert len(rows) == 1
        assert rows[0].digest == hashlib.sha256(token.encode()).hexdigest()
        assert rows[0].digest != token
        assert rows[0].tenant_id == "brightline" and rows[0].role == "operator"
        assert db.get(Tenant, "brightline").name == "Existing demo"
        assert db.get(Integration, ("brightline", "payroll")) is not None
    engine.dispose()
