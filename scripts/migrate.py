"""Apply immutable numbered PostgreSQL migrations; record digest and serialize deploys."""

import hashlib
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.session import get_engine


def migrate():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise SystemExit("Migrations require PostgreSQL; seed.py handles local SQLite")
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(784221)"))
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, digest text NOT NULL)"
        )
        for path in sorted(
            (Path(__file__).resolve().parents[1] / "backend/migrations").glob("*.sql")
        ):
            sql = path.read_text()
            digest = hashlib.sha256(sql.encode()).hexdigest()
            previous = connection.execute(
                text("SELECT digest FROM schema_migrations WHERE version=:v"),
                {"v": path.name},
            ).scalar()
            if previous:
                if previous != digest:
                    raise RuntimeError(f"Applied migration changed: {path.name}")
                continue
            connection.exec_driver_sql(sql)
            connection.execute(
                text("INSERT INTO schema_migrations(version,digest) VALUES (:v,:d)"),
                {"v": path.name, "d": digest},
            )
            print(f"Applied {path.name}")


if __name__ == "__main__":
    migrate()
