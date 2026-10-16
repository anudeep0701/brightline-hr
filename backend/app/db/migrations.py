"""Transactional, digest-checked PostgreSQL migrations and explicit local init."""

import hashlib
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.session import get_engine
from app.models.entities import Base

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def migrate(engine=None):
    engine = engine or get_engine()
    if engine.dialect.name != "postgresql":
        raise ValueError(
            "PostgreSQL migrations require a PostgreSQL DATABASE_URL; use init_db.py for local demo SQLite"
        )
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(784221)"))
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, digest text NOT NULL)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY"
        )
        connection.exec_driver_sql("REVOKE ALL ON schema_migrations FROM PUBLIC")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode()).hexdigest()
            previous = connection.execute(
                text("SELECT digest FROM schema_migrations WHERE version=:v"),
                {"v": path.name},
            ).scalar()
            if previous:
                if previous != digest:
                    raise ValueError(
                        f"Applied migration changed: {path.name}; restore it and add a new numbered migration"
                    )
                continue
            connection.exec_driver_sql(sql)
            connection.execute(
                text("INSERT INTO schema_migrations(version,digest) VALUES (:v,:d)"),
                {"v": path.name, "d": digest},
            )
            print(f"Applied {path.name}")


def initialize_database(engine=None):
    engine = engine or get_engine()
    if engine.dialect.name == "postgresql":
        return migrate(engine)
    if engine.dialect.name != "sqlite" or get_settings().app_env not in (
        "demo",
        "test",
    ):
        raise ValueError(
            "SQLite initialization is restricted to explicitly configured demo/test databases"
        )
    if {"request_logs", "incidents"} & set(inspect(engine).get_table_names()):
        raise ValueError(
            "Legacy SQLite demo schema detected. Select a fresh local SQLite file; PostgreSQL migrations preserve existing production data."
        )
    existing = set(inspect(engine).get_table_names())
    for name in ("integration_config", "health_snapshots", "enrichments"):
        if name in existing:
            expected = set(Base.metadata.tables[name].columns.keys())
            actual = {x["name"] for x in inspect(engine).get_columns(name)}
            if not expected <= actual:
                raise ValueError(
                    "Older SQLite demo schema detected. Select a fresh local SQLite file; apply numbered migrations for PostgreSQL."
                )
    # Explicit init only: preserve existing demo data while adding provenance.
    if "request_events" in existing and "source_type" not in {
        column["name"] for column in inspect(engine).get_columns("request_events")
    }:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE request_events ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN' "
                "CHECK (source_type IN ('LIVE_API','FILE_IMPORT','DEMO','UNKNOWN'))"
            )
    Base.metadata.create_all(engine)


def run_command(operation):
    try:
        operation()
    except ValueError as exc:
        # Settings hide_input_in_errors prevents connection strings leaking here.
        raise SystemExit(str(exc)) from None
    except SQLAlchemyError:
        raise SystemExit(
            "Database operation failed. Verify DATABASE_URL, connectivity, permissions and migration state; no credentials have been printed."
        ) from None
