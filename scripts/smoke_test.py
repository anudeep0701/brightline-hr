"""Local-only HTTP smoke test. Uses temporary SQLite unless --local-postgres is explicit.

Never reads environment files, uses hosted databases or calls OpenAI. --serve keeps
its isolated API/data alive for manual frontend verification after the checks.
"""

import argparse
import errno
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-postgres", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--tenants", type=int, default=2)
    args = parser.parse_args()
    if args.tenants < 2:
        parser.error("At least two tenants are required for isolation checks")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if args.local_postgres:
        from sqlalchemy.engine import make_url

        configured = os.environ.get("DATABASE_URL", "")
        if not configured:
            parser.error("--local-postgres requires an explicit local DATABASE_URL")
        try:
            url = make_url(configured)
        except SQLAlchemyError:
            parser.error("DATABASE_URL is invalid; no connection attempted")
        if (
            url.get_backend_name() != "postgresql"
            or url.host not in ("127.0.0.1", "localhost", "::1")
            or not (url.database or "").startswith("brightline_smoke")
            or url.query
        ):
            parser.error(
                "Use an explicit loopback PostgreSQL DATABASE_URL with a dedicated brightline_smoke* database and no connection query overrides"
            )

    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                parser.error("Requested API port is in use; choose --port")
            parser.error(
                "Cannot bind a loopback port; allow local networking for this command"
            )
    with TemporaryDirectory(prefix="brightline-smoke-") as directory:
        if not args.local_postgres:
            os.environ["DATABASE_URL"] = "sqlite:///" + str(
                Path(directory) / "smoke.db"
            )
        os.environ["APP_ENV"] = "demo"
        os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("VERCEL", None)
        sys.path.insert(0, str(ROOT / "backend"))
        sys.path.insert(0, str(ROOT / "scripts"))
        from app.db.session import get_engine
        from app.health.service import bucket_for
        from app.ingestion.credentials import issue_key, revoke_key
        from app.models.entities import AccessToken, Incident, Integration, Snapshot
        from seed import seed
        from sqlalchemy import inspect, select
        from sqlalchemy.orm import Session

        engine = get_engine()
        if inspect(engine).get_table_names():
            parser.error(
                "Smoke test requires a fresh empty database; no existing data changed"
            )
        started = time.perf_counter()
        seed(duration_minutes=args.duration, tenants=args.tenants, random_seed=42)
        print(
            f"Generation, ingestion and historical evaluation: {time.perf_counter() - started:.2f}s",
            flush=True,
        )
        tokens, keys = {}, {}
        tenants = ["brightline", "tenant-002"]
        with Session(engine, expire_on_commit=False) as db:
            for tenant in tenants:
                token = secrets.token_urlsafe(32)
                tokens[tenant] = token
                db.add(
                    AccessToken(
                        digest=hashlib.sha256(token.encode()).hexdigest(),
                        tenant_id=tenant,
                        role="operator",
                    )
                )
                db.add(
                    Integration(
                        tenant_id=tenant,
                        id="moderate-errors",
                        name="Moderate errors",
                        category="payroll",
                        owner="Operations",
                    )
                )
                db.add(
                    Integration(
                        tenant_id=tenant,
                        id="no-traffic",
                        name="No traffic",
                        category="payroll",
                        owner="Operations",
                    )
                )
                db.commit()
                key, secret = issue_key(db, tenant, "Local smoke exporter")
                keys[tenant] = (key.id, secret)
            db.add(
                Integration(
                    tenant_id="tenant-002",
                    id="private-integration",
                    name="Tenant B only",
                    category="payroll",
                    owner="Operations",
                )
            )
            db.commit()
        base = f"http://127.0.0.1:{args.port}"
        process = None
        log = (Path(directory) / "backend.log").open("w+")

        def request(path, method="GET", body=None, credential=None, headers=None):
            headers = dict(headers or {})
            if credential:
                headers["Authorization"] = "Bearer " + credential
            payload = None if body is None else json.dumps(body).encode()
            if payload is not None:
                headers["Content-Type"] = "application/json"
            try:
                response = urlopen(
                    Request(base + path, data=payload, headers=headers, method=method),
                    timeout=30,
                )
            except HTTPError as error:
                response = error
            raw = response.read()
            try:
                data = json.loads(raw)
            except ValueError:
                data = raw.decode()
            return response.status, data, response.headers

        def launch():
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                    "--log-level",
                    "warning",
                ],
                cwd=ROOT / "backend",
                env=os.environ.copy(),
                stdout=log,
                stderr=log,
            )
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError(
                        "Backend startup failed; no log contents printed to avoid accidental disclosure"
                    )
                try:
                    if request("/readyz")[0] == 200:
                        return child
                except (URLError, TimeoutError):
                    pass
                time.sleep(0.1)
            child.terminate()
            child.wait(timeout=10)
            raise RuntimeError("Backend did not become ready")

        def stop():
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)

        try:
            process = launch()
            for path in ("/healthz", "/readyz", "/docs", "/openapi.json"):
                assert request(path)[0] == 200, path
            status, _, headers = request(
                "/api/ingest",
                "OPTIONS",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization,Content-Type",
                },
            )
            assert (
                status == 200
                and headers.get("Access-Control-Allow-Origin")
                == "http://localhost:3000"
            )
            assert (
                request("/healthz", headers={"Origin": "https://untrusted.invalid"})[
                    2
                ].get("Access-Control-Allow-Origin")
                is None
            )
            at = bucket_for(datetime.now(timezone.utc))

            def event(request_id, integration="moderate-errors", **changes):
                return dict(
                    timestamp=(at - timedelta(seconds=1)).isoformat(),
                    integration_id=integration,
                    request_id=request_id,
                    http_status=200,
                    latency_ms=100,
                    **changes,
                )

            for tenant in tenants:
                batch = [event(f"smoke-{i}") for i in range(100)]
                for item in batch[:3]:
                    item["http_status"] = 503
                status, result, _ = request(
                    "/api/ingest", "POST", {"events": batch}, keys[tenant][1]
                )
                assert status == 200 and result["accepted"] == 100
                status, result, _ = request(
                    "/api/ingest", "POST", {"events": batch}, keys[tenant][1]
                )
                assert (
                    status == 200
                    and result["duplicates"] == 100
                    and result["accepted"] == 0
                )
                assert (
                    request("/api/evaluate", "POST", credential=tokens[tenant])[0]
                    == 200
                )
                repeated = request("/api/evaluate", "POST", credential=tokens[tenant])[
                    1
                ]
                assert repeated["created"] == 0
            assert (
                request(
                    "/api/ingest", "POST", {"events": [event("invalid-key")]}, "invalid"
                )[0]
                == 401
            )
            forbidden = [
                event("valid-peer"),
                event("foreign-tenant", tenant_id="tenant-002"),
            ]
            status, result, _ = request(
                "/api/ingest", "POST", {"events": forbidden}, keys["brightline"][1]
            )
            assert status == 403 and result["accepted"] == 0
            assert (
                request(
                    "/api/ingest",
                    "POST",
                    {"events": [event("foreign-integration", "private-integration")]},
                    keys["brightline"][1],
                )[0]
                == 403
            )
            malformed = event("bad-event")
            malformed.pop("latency_ms")
            status, result, _ = request(
                "/api/ingest",
                "POST",
                {"events": [event("partial-valid"), malformed]},
                keys["brightline"][1],
            )
            assert (
                status == 200
                and result["accepted"] == 1
                and result["rejected"] == 1
                and result["validation_errors"]
            )
            assert (
                request(
                    "/api/ingest",
                    "POST",
                    {"events": [malformed]},
                    keys["brightline"][1],
                )[0]
                == 422
            )
            assert (
                request("/api/integrations", credential=keys["brightline"][1])[0] == 403
            )
            with Session(engine) as db:
                revoke_key(db, keys["brightline"][0])
            assert (
                request(
                    "/api/ingest",
                    "POST",
                    {"events": [event("revoked")]},
                    keys["brightline"][1],
                )[0]
                == 401
            )
            expected = {
                "workday-payroll": "HEALTHY",
                "adp-payroll": "UNHEALTHY",
                "docusign": "UNHEALTHY",
                "greenhouse-ats": "UNHEALTHY",
                "slack-notifications": "UNHEALTHY",
                "twilio-notifications": "UNKNOWN",
                "adp-recovery": "HEALTHY",
                "slack-spike": "HEALTHY",
                "workday-sustained": "UNHEALTHY",
                "moderate-errors": "DEGRADED",
                "no-traffic": "UNKNOWN",
            }
            from generate_synthetic_data import CATALOG

            scenario_ids = {spec.scenario: spec.id for spec in CATALOG}
            summary_before = None
            for tenant in tenants:
                status, listing, _ = request(
                    "/api/integrations?limit=200", credential=tokens[tenant]
                )
                assert status == 200 and listing["tenant_id"] == tenant
                counts = dict.fromkeys(
                    ("HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"), 0
                )
                for item in listing["items"]:
                    integration = item["integration"]["id"]
                    state = (
                        item["snapshot"]["status"] if item["snapshot"] else "UNKNOWN"
                    )
                    counts[state] += 1
                    if integration in expected:
                        assert state == expected[integration], (integration, state)
                summary = request("/api/health-summary", credential=tokens[tenant])[1]
                assert summary["status_counts"] == counts
                if tenant == "brightline":
                    summary_before = summary
                for state in counts:
                    filtered = request(
                        f"/api/integrations?health_status={state}",
                        credential=tokens[tenant],
                    )[1]
                    assert filtered["total"] == counts[state]
                assert (
                    request(
                        "/api/integrations?tenant_id=tenant-002",
                        credential=tokens["brightline"],
                    )[0]
                    == 403
                )
            spike = scenario_ids["brief_spike"]
            recovery = scenario_ids["recovery_after_incident"]
            with Session(engine) as db:
                assert not db.scalars(
                    select(Incident).where(
                        Incident.tenant_id == "brightline",
                        Incident.integration_id == spike,
                    )
                ).all()
                recovered = db.scalars(
                    select(Incident).where(
                        Incident.tenant_id == "brightline",
                        Incident.integration_id == recovery,
                    )
                ).all()
                assert recovered and all(x.resolved_at is not None for x in recovered)
                history = db.scalars(
                    select(Snapshot)
                    .where(
                        Snapshot.tenant_id == "brightline",
                        Snapshot.integration_id == recovery,
                    )
                    .order_by(Snapshot.bucket)
                ).all()
                resolved = next(
                    x for x in history if x.bucket == recovered[0].resolved_at
                )
                assert resolved.healthy_window_streak >= 2
            detail = request(
                "/api/integrations/workday-payroll", credential=tokens["brightline"]
            )[1]
            explanation = request(
                "/api/integrations/workday-payroll/explain",
                "POST",
                credential=tokens["brightline"],
            )[1]
            assert (
                explanation["source"] == "deterministic"
                and explanation["explanation"] == detail["snapshot"]["reason_text"]
            )
            status, generated_brief, _ = request(
                "/api/integrations/workday-payroll/brief",
                "POST",
                credential=tokens["brightline"],
            )
            assert status == 200 and generated_brief["audit"]["fallback_used"]
            status, answer, _ = request(
                f"/api/integrations/{recovery}/investigate",
                "POST",
                {"topic": "recovery", "incident_id": recovered[0].id},
                tokens["brightline"],
            )
            assert status == 200 and answer["audit"]["health_state"] == "HEALTHY"
            assert answer["audit"]["incident_id"] == recovered[0].id
            status, operations_answer, _ = request(
                "/api/assistant/ask",
                "POST",
                {"question": "What needs attention right now?"},
                tokens["brightline"],
            )
            assert status == 200 and operations_answer["availability"] == "FALLBACK"
            assert (
                operations_answer["evidence"]
                and operations_answer["audit"]["failure_category"] == "MISSING_API_KEY"
            )
            assert (
                request(
                    "/api/assistant/ask?tenant_id=other",
                    "POST",
                    {"question": "What needs attention?"},
                    tokens["brightline"],
                )[0]
                == 403
            )
            status, incident_feed, _ = request(
                "/api/incidents?limit=100", credential=tokens["brightline"]
            )
            assert status == 200 and incident_feed["items"]
            assert all(
                item["tenant_id"] == "brightline" for item in incident_feed["items"]
            )
            assert (
                request(
                    "/api/incidents?tenant_id=other", credential=tokens["brightline"]
                )[0]
                == 403
            )
            pilot_batch = {"events": [event("pilot-file-smoke")]}
            status, preview, _ = request(
                "/api/imports/preview?format=json",
                "POST",
                pilot_batch,
                tokens["brightline"],
            )
            assert status == 200 and preview["valid_records"] == 1
            status, imported, _ = request(
                "/api/imports/commit?format=json",
                "POST",
                pilot_batch,
                tokens["brightline"],
                headers={
                    "X-Confirm-Import": "true",
                    "X-Preview-Digest": preview["file_digest"],
                },
            )
            assert status == 200 and imported["accepted"] == 1
            status, sources, _ = request(
                "/api/data-sources", credential=tokens["brightline"]
            )
            assert status == 200
            moderate = next(
                row
                for row in sources["items"]
                if row["integration_id"] == "moderate-errors"
            )
            assert {row["source_type"] for row in moderate["sources"]} == {
                "LIVE_API",
                "FILE_IMPORT",
            }
            workday = next(
                row
                for row in sources["items"]
                if row["integration_id"] == "workday-payroll"
            )
            assert {row["source_type"] for row in workday["sources"]} == {"DEMO"}
            stop()
            process = launch()
            restored = request("/api/health-summary", credential=tokens["brightline"])[
                1
            ]
            assert restored["status_counts"] == summary_before["status_counts"]
            print(
                json.dumps(
                    {
                        "result": "passed",
                        "database": engine.dialect.name,
                        "states": restored["status_counts"],
                        "scenarios": "10 generated + moderate errors + no traffic",
                        "checks": [
                            "HTTP probes/docs/CORS",
                            "authenticated ingestion",
                            "duplicate retries",
                            "tenant isolation",
                            "revocation",
                            "safe partial validation",
                            "incident recovery and spike",
                            "repeat evaluation",
                            "AI fallback and grounded brief/recovery assistance",
                            "file preview/confirmation and observed source types",
                            "API process restart",
                        ],
                    }
                ),
                flush=True,
            )
            if args.serve:
                print(
                    f"Isolated demo API ready at {base}; Ctrl+C stops it. No credentials are printed.",
                    flush=True,
                )
                process.wait()
        finally:
            stop()
            log.close()
            engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SQLAlchemyError:
        raise SystemExit(
            "Local database operation failed; verify container availability and migration state. No connection details printed."
        ) from None
