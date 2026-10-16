"""Exercise the real CLI against temporary storage without developer env files."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.ingestion.credentials import authenticate_key, key_digest
from app.models.entities import Base, IngestionAPIKey, Tenant
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]


def invoke(arguments, environment):
    return subprocess.run(
        [sys.executable, "scripts/ingestion_keys.py", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def storage(tmp_path):
    url = "sqlite:///" + str(tmp_path / "ingestion-cli.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Tenant(id="brightline", name="Brightline"),
                Tenant(id="other", name="Other"),
            ]
        )
        db.commit()
    environment = {**os.environ, "APP_ENV": "test", "DATABASE_URL": url}
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("VERCEL", None)
    yield engine, environment
    engine.dispose()


@pytest.mark.parametrize(
    "arguments",
    [["--help"], ["create", "--help"], ["list", "--help"], ["revoke", "--help"]],
)
def test_help_works_without_database_configuration(arguments):
    environment = {**os.environ, "DATABASE_URL": ""}
    result = invoke(arguments, environment)
    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "DATABASE_URL is not configured" not in result.stderr


def test_create_list_rotate_and_revoke_preserve_hash_only_tenant_scope(storage):
    engine, environment = storage
    created = invoke(
        ["create", "brightline", "--name", "Customer exporter"], environment
    )
    assert created.returncode == 0, "CLI creation failed on temporary storage"
    first = json.loads(created.stdout)
    secret = first["secret"]
    assert created.stdout.count(secret) == 1
    assert secret not in created.stderr
    assert "cannot be retrieved" in created.stderr
    assert first["tenant_id"] == "brightline"
    with Session(engine) as db:
        key = authenticate_key(db, secret)
        assert key.id == first["id"]
        assert key.digest == key_digest(secret)
        assert secret not in str(
            {c.name: getattr(key, c.name) for c in key.__table__.columns}
        )

    other = invoke(["create", "other", "--name", "Other exporter"], environment)
    assert other.returncode == 0
    foreign = json.loads(other.stdout)
    listing = invoke(["list", "brightline"], environment)
    assert listing.returncode == 0
    assert [key["id"] for key in json.loads(listing.stdout)] == [first["id"]]
    assert foreign["id"] not in listing.stdout
    assert secret not in listing.stdout + listing.stderr
    assert key_digest(secret) not in listing.stdout + listing.stderr
    assert "secret" not in listing.stdout and "digest" not in listing.stdout

    # Documented rotation is deliberately three steps, with overlap for the exporter.
    replacement = invoke(
        ["create", "brightline", "--name", "Replacement exporter"], environment
    )
    assert replacement.returncode == 0
    second = json.loads(replacement.stdout)
    with Session(engine) as db:
        assert authenticate_key(db, secret) is not None
        assert authenticate_key(db, second["secret"]) is not None

    revoked = invoke(["revoke", first["id"]], environment)
    assert revoked.returncode == 0
    result = json.loads(revoked.stdout)
    assert result["revoked_at"] is not None
    assert secret not in revoked.stdout + revoked.stderr
    assert key_digest(secret) not in revoked.stdout + revoked.stderr
    repeated = invoke(["revoke", first["id"]], environment)
    assert repeated.returncode == 0
    assert json.loads(repeated.stdout)["revoked_at"] == result["revoked_at"]
    with Session(engine) as db:
        assert authenticate_key(db, secret) is None
        assert authenticate_key(db, second["secret"]).tenant_id == "brightline"
        assert authenticate_key(db, foreign["secret"]).tenant_id == "other"
    listed = json.loads(invoke(["list", "brightline"], environment).stdout)
    assert len(listed) == 2
    assert (
        next(key for key in listed if key["id"] == first["id"])["revoked_at"]
        is not None
    )


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["create", "missing", "--name", "Exporter"], "Tenant not found"),
        (["list", "missing"], "Tenant not found"),
        (["revoke", "missing-public-id"], "Ingestion key not found"),
        (["create", "brightline", "--name", ""], "1 to 100 characters"),
        (["create", "brightline", "--name", "x" * 101], "1 to 100 characters"),
    ],
)
def test_invalid_operations_fail_without_mutation_or_secret_output(
    storage, arguments, message
):
    engine, environment = storage
    result = invoke(arguments, environment)
    assert result.returncode != 0
    assert result.stdout == ""
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(IngestionAPIKey)) == 0


def test_failed_persistence_never_discloses_generated_secret(storage):
    engine, environment = storage
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER deny_key_insert BEFORE INSERT ON ingestion_api_keys "
            "BEGIN SELECT RAISE(ABORT, 'PRIVATE_STORAGE_FAILURE'); END"
        )
    result = invoke(["create", "brightline", "--name", "Exporter"], environment)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Database operation failed" in result.stderr
    assert "PRIVATE_STORAGE_FAILURE" not in result.stderr
    assert "bl_ingest_" not in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_configuration_fails_clearly_without_reading_environment_files():
    result = invoke(["list", "brightline"], {**os.environ, "DATABASE_URL": ""})
    assert result.returncode != 0
    assert result.stdout == ""
    assert "DATABASE_URL is not configured" in result.stderr
    assert "Traceback" not in result.stderr
