"""Replay the official 60-record fixture through normal ingestion and health services.

Local temporary SQLite only. Original timestamps are assumed UTC. Rebase is
explicit and preserves offsets/outcomes; no source file or stored row is edited.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.health.config import DEFAULT_POLICY
from app.health.service import bucket_for, refresh
from app.ingestion.service import ingest
from app.models.entities import Integration, Snapshot, Tenant
from sqlalchemy import select
from sqlalchemy.orm import Session

SOURCE = Path(__file__).resolve().parents[1] / "data/provided/integration_logs.json"
PROVIDERS = {
    "Slack Notifications": ("starter-slack", "notifications", 500),
    "ADP Payroll Sync": ("starter-adp", "payroll", 1000),
    "DocuSign Envelope API": ("starter-docusign", "e_signature", 1000),
    "Workday Directory Sync": ("starter-workday", "directory", 500),
    "Greenhouse ATS Sync": ("starter-greenhouse", "ats", 1000),
}
# Sparse official fixture: twelve observations/provider/hour, not a production SLA.
SAMPLE_POLICY = dict(
    evaluation_window_minutes=60,
    min_requests=5,
    error_warning=0.10,
    error_critical=0.30,
    timeout_warning=0.10,
    timeout_critical=0.30,
)


def normalize(path=SOURCE, *, rebase_at=None):
    content = Path(path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    rows = json.loads(content)["logs"]
    if not rows:
        raise ValueError("Official fixture has no observations")
    times = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    times = [
        t.replace(tzinfo=timezone.utc)
        if t.tzinfo is None
        else t.astimezone(timezone.utc)
        for t in times
    ]
    source_end = max(times) + timedelta(minutes=5)
    end = bucket_for(rebase_at) if rebase_at else source_end
    shift = end - source_end
    events = []
    for index, (row, at) in enumerate(zip(rows, times, strict=True)):
        if row["integration"] not in PROVIDERS or row["status"] not in {
            "success",
            "error",
            "timeout",
        }:
            raise ValueError("Unsupported official provider/status")
        timed_out = row["status"] == "timeout"
        status = 504 if timed_out else row["status_code"]
        if not timed_out and (
            type(status) is not int
            or (row["status"] == "success" and not 200 <= status < 400)
            or (row["status"] == "error" and not 400 <= status <= 599)
        ):
            raise ValueError("Official status and HTTP code disagree")
        events.append(
            dict(
                timestamp=(at + shift).isoformat(),
                request_id=str(uuid5(NAMESPACE_URL, f"official:{digest}:{index}")),
                integration_id=PROVIDERS[row["integration"]][0],
                http_status=status,
                latency_ms=row["latency_ms"],
                timed_out=timed_out,
            )
        )
    return events, end, source_end, digest


def replay(engine, *, path=SOURCE, rebase_at=None):
    events, end, source_end, digest = normalize(path, rebase_at=rebase_at)
    with Session(engine) as db:
        if db.get(Tenant, "brightline"):
            raise ValueError("Replay requires an empty disposable Brightline workspace")
        db.add(Tenant(id="brightline", name="Brightline HR (Official sample replay)"))
        db.flush()
        for name, (identity, category, target) in PROVIDERS.items():
            integration = Integration(
                tenant_id="brightline",
                id=identity,
                name=name,
                category=category,
                owner="Platform Ops",
                latency_target_ms=target,
                max_gap_minutes=30,
            )
            for field, value in SAMPLE_POLICY.items():
                setattr(integration.config, field, value)
            db.add(integration)
        db.commit()
        result = ingest(
            db,
            "brightline",
            events,
            allow_historical=True,
            now=end,
            source_type="DEMO",
        )
        if result["accepted"] != len(events) or result["rejected"]:
            raise ValueError("Official input failed normal ingestion")
        # Two adjacent final observations respect the unchanged confirmation policy.
        # Earlier empty/partial history is not manufactured for this one-hour sample.
        for at in (end - timedelta(minutes=5), end):
            refresh(db, "brightline", at)
        snapshots = db.scalars(
            select(Snapshot)
            .where(Snapshot.bucket == end)
            .order_by(Snapshot.integration_id)
        ).all()
        return dict(
            source_sha256=digest,
            source_end_utc=source_end.isoformat(),
            evaluated_at=end.isoformat(),
            rebased=rebase_at is not None,
            profile=dict(DEFAULT_POLICY.model_dump(), **SAMPLE_POLICY),
            accepted=result["accepted"],
            integrations=[
                dict(
                    integration_id=s.integration_id,
                    status=s.status,
                    reason=s.reason_text,
                    request_count=s.evidence["metrics"]["request_count"],
                    error_rate=s.evidence["metrics"]["error_rate"],
                    timeout_rate=s.evidence["metrics"]["timeout_rate"],
                    p95_ms=s.evidence["metrics"]["p95_ms"],
                )
                for s in snapshots
            ],
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebase-to-now",
        action="store_true",
        help="Explicit demo-only timestamp offset preserving all supplied outcomes",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the normal FastAPI UI backend on loopback; use with --rebase-to-now for fresh evidence",
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if os.getenv("VERCEL") or not 1 <= args.port <= 65535:
        parser.error("Local replay only; port must be between 1 and 65535")
    with TemporaryDirectory(prefix="brightline-official-replay-") as directory:
        os.environ.update(
            APP_ENV="demo",
            DATABASE_URL="sqlite:///" + str(Path(directory) / "official.db"),
            DEMO_MODE="false",
        )
        os.environ.pop("OPENAI_API_KEY", None)
        from app.config import get_settings
        from app.db.migrations import initialize_database
        from app.db.session import get_engine

        get_settings.cache_clear()
        engine = get_engine()
        try:
            initialize_database(engine)
            result = replay(
                engine,
                rebase_at=datetime.now(timezone.utc) if args.rebase_to_now else None,
            )
            print(json.dumps(result, indent=2), flush=True)
            if args.serve:
                import uvicorn

                uvicorn.run(
                    "app.main:app",
                    host="127.0.0.1",
                    port=args.port,
                    log_level="warning",
                )
        finally:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
