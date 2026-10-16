"""Migration/backfill/concurrency integration checks for an isolated EMPTY PG DB."""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.migrations import MIGRATIONS, migrate
from app.db.session import get_engine
from app.health.service import bucket_for, refresh
from app.ingestion.credentials import authenticate_key, issue_key, revoke_key
from app.ingestion.service import ingest
from app.models.entities import (
    Enrichment,
    Incident,
    IntegrationConfig,
    MetricRollup,
    RequestEvent,
    Snapshot,
)


def check():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise ValueError("This check requires an isolated PostgreSQL DATABASE_URL")
    if inspect(engine).get_table_names():
        raise ValueError(
            "Use an EMPTY isolated PostgreSQL database for migration/backfill checks"
        )
    tenant = "ci-" + uuid4().hex
    at = bucket_for(datetime.now(timezone.utc))
    # Exercise actual upgrade preservation, not only CREATE TABLE on an empty DB.
    first = MIGRATIONS / "001_initial.sql"
    with engine.begin() as connection:
        connection.exec_driver_sql(first.read_text())
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations (version text PRIMARY KEY, digest text NOT NULL)"
        )
        connection.execute(
            text("INSERT INTO schema_migrations VALUES (:version,:digest)"),
            {
                "version": first.name,
                "digest": hashlib.sha256(first.read_bytes()).hexdigest(),
            },
        )
        connection.execute(
            text("INSERT INTO tenants(id,name) VALUES (:tenant,'CI legacy tenant')"),
            {"tenant": tenant},
        )
        connection.execute(
            text(
                "INSERT INTO integrations(tenant_id,id,name,category,owner,latency_target_ms,max_gap_minutes) VALUES (:tenant,'payroll','Payroll','Payroll','Ops',1234,30)"
            ),
            {"tenant": tenant},
        )
        connection.execute(
            text(
                "INSERT INTO request_logs(tenant_id,event_id,integration_id,occurred_at,status_code,latency_ms,timed_out,error_category) VALUES (:tenant,'legacy','payroll',:at,503,100,false,'upstream')"
            ),
            {"tenant": tenant, "at": at - timedelta(seconds=1)},
        )
        metrics = dict(
            request_count=1,
            error_count=1,
            error_rate=1,
            p95_ms=100,
            last_request_at=(at - timedelta(seconds=1)).isoformat(),
            daily_request_count=1,
            daily_error_rate=1,
            error_categories={"upstream": 1},
        )
        connection.execute(
            text(
                "INSERT INTO health_snapshots(id,tenant_id,integration_id,bucket,evaluated_at,status,score,evidence) VALUES ('legacy-snapshot',:tenant,'payroll',:bucket,:bucket,'unhealthy',0,CAST(:evidence AS JSON))"
            ),
            {
                "tenant": tenant,
                "bucket": at - timedelta(minutes=5),
                "evidence": json.dumps({"metrics": metrics}),
            },
        )
        connection.execute(
            text(
                "INSERT INTO incidents(id,tenant_id,integration_id,opening_snapshot_id,last_snapshot_id,opened_at,recovery_streak) VALUES ('legacy-incident',:tenant,'payroll','legacy-snapshot','legacy-snapshot',:at,0)"
            ),
            {"tenant": tenant, "at": at - timedelta(minutes=5)},
        )
        connection.execute(
            text(
                "INSERT INTO enrichments(id,snapshot_id,generated_at,source,explanation,evidence_digest) VALUES ('legacy-enrichment','legacy-snapshot',:at,'deterministic','legacy evidence','digest')"
            ),
            {"at": at},
        )
    migrate(engine)
    migrate(engine)
    try:
        with Session(engine) as db:
            assert db.get(
                RequestEvent, (tenant, "legacy")
            ).occurred_at.utcoffset() == timedelta(0)
            assert (
                db.get(IntegrationConfig, (tenant, "payroll")).latency_target_ms == 1234
            )
            assert db.get(RequestEvent, (tenant, "legacy")).source_type == "UNKNOWN"
            assert (
                db.get(RequestEvent, (tenant, "legacy")).raw_event["legacy_backfill"]
                is True
            )
            assert (
                db.get(Snapshot, "legacy-snapshot").metric_rollup_id
                == "legacy-snapshot"
            )
            assert db.get(MetricRollup, "legacy-snapshot").metrics["request_count"] == 1
            assert (
                db.scalar(
                    text(
                        "SELECT tenant_id FROM enrichments WHERE id='legacy-enrichment'"
                    )
                )
                == tenant
            )
            legacy_enrichment = db.get(Enrichment, "legacy-enrichment")
            assert legacy_enrichment.prompt_version == "legacy-v1"
            assert legacy_enrichment.report is None
            assert legacy_enrichment.evidence_payload is None
            assert legacy_enrichment.explanation == "legacy evidence"
            assert db.get(Incident, "legacy-incident").tenant_id == tenant
            assert db.get(Snapshot, "legacy-snapshot").status == "UNHEALTHY"
            assert db.get(Snapshot, "legacy-snapshot").reason_code == "LEGACY_SNAPSHOT"
            assert (
                db.get(IntegrationConfig, (tenant, "payroll")).unhealthy_bad_windows
                == 2
            )
        with Session(engine, expire_on_commit=False) as db:
            key, secret = issue_key(db, tenant, "CI exporter")
            assert key.digest != secret and len(key.digest) == 64
            assert authenticate_key(db, secret).tenant_id == tenant
            revoke_key(db, key.id)
            assert authenticate_key(db, secret) is None
        rows = [
            dict(
                event_id=str(n),
                integration_id="payroll",
                occurred_at=(at - timedelta(seconds=n + 1)).isoformat(),
                status_code=503,
                latency_ms=100,
            )
            for n in range(30)
        ]

        def load(_):
            with Session(engine) as db:
                return ingest(db, tenant, rows)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(load, range(2)))
        assert sum(x["accepted"] for x in results) == 30
        assert sum(x["duplicates"] for x in results) == 30

        def evaluate(_):
            with Session(engine) as db:
                return refresh(db, tenant, at)["created"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(evaluate, range(2))) == [0, 1]
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Incident)
                    .where(Incident.tenant_id == tenant)
                )
                == 1
            )
            assert db.get(RequestEvent, (tenant, "0")).source_type == "LIVE_API"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(RequestEvent)
                    .where(RequestEvent.tenant_id == tenant)
                )
                == 31
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(MetricRollup)
                    .where(MetricRollup.tenant_id == tenant)
                )
                == 2
            )
            enabled = set(
                db.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relrowsecurity AND relnamespace='public'::regnamespace"
                    )
                ).scalars()
            )
            assert {
                "tenants",
                "access_tokens",
                "ingestion_api_keys",
                "integrations",
                "integration_config",
                "request_events",
                "metric_rollups",
                "health_snapshots",
                "health_incidents",
                "enrichments",
                "schema_migrations",
            } <= enabled
        print(
            "PostgreSQL upgrade/backfill, UTC storage, RLS, concurrent deduplication and refresh passed"
        )
    finally:
        with engine.begin() as connection:
            for table in (
                "ingestion_api_keys",
                "enrichments",
                "health_incidents",
                "health_snapshots",
                "metric_rollups",
                "request_events",
                "integration_config",
                "integrations",
                "tenants",
            ):
                column = "id" if table == "tenants" else "tenant_id"
                connection.execute(
                    text(f"DELETE FROM {table} WHERE {column}=:tenant"),
                    {"tenant": tenant},
                )


if __name__ == "__main__":
    from app.db.migrations import run_command

    run_command(check)
