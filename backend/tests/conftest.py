import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CRON_SECRET"] = "test-cron-secret"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ.pop("OPENAI_API_KEY", None)
import hashlib

import pytest
from app.db.session import get_db
from app.main import app
from app.models.entities import AccessToken, Base, Integration, Tenant
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        for tenant in ("a", "b"):
            session.add(Tenant(id=tenant, name=tenant))
            session.flush()
            session.add(
                Integration(
                    tenant_id=tenant,
                    id="payroll",
                    name="Payroll",
                    category="Payroll",
                    owner="Ops",
                    latency_target_ms=1000,
                    max_gap_minutes=30,
                )
            )
            session.add(
                AccessToken(
                    digest=hashlib.sha256(tenant.encode()).hexdigest(),
                    tenant_id=tenant,
                    role="operator",
                )
            )
        session.add(
            AccessToken(
                digest=hashlib.sha256(b"reader").hexdigest(),
                tenant_id="a",
                role="reader",
            )
        )
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def forbid_unmocked_openai(monkeypatch):
    """Tests may replace this factory with a local fake, but cannot call the provider."""

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Unexpected OpenAI client construction; use an explicit offline fake"
        )

    monkeypatch.setattr("app.ai.enrichment.OpenAI", forbidden)


@pytest.fixture
def monitoring_clock(monkeypatch):
    """Fixed UTC application clock, advanced explicitly by API workflow tests."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    clock = SimpleNamespace(now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

    def advance(minutes=5):
        clock.now += timedelta(minutes=minutes)
        return clock.now

    clock.advance = advance
    for module in (
        "app.ingestion.service",
        "app.health.service",
        "app.services.operations",
        "app.ai.enrichment",
        "app.ai.incident_assistance",
        "app.ai.operations_assistant",
        "app.services.freshness",
    ):
        monkeypatch.setattr(f"{module}.datetime", FrozenDateTime)
    return clock


@pytest.fixture
def request_window(monitoring_clock):
    """Seeded request attempts with exact counts/errors and bounded UTC timestamps."""
    from datetime import timedelta

    import numpy as np

    def build(*, tenant="a", count=100, errors=0, latency_ms=250, label="window"):
        if not 0 <= errors <= count:
            raise ValueError("Error count must be within the request count")
        rng = np.random.default_rng(42)
        failed = set(rng.choice(count, size=errors, replace=False).tolist())
        at = monitoring_clock.now
        return [
            dict(
                tenant_id=tenant,
                integration_id="payroll",
                request_id=f"{label}:{at.strftime('%Y%m%dT%H%M%SZ')}:{index}",
                timestamp=(
                    at - timedelta(seconds=int(rng.integers(1, 300)))
                ).isoformat(),
                http_status=503 if index in failed else 200,
                latency_ms=latency_ms,
                error_code="PROVIDER_UNAVAILABLE" if index in failed else None,
                error_message="Synthetic provider failure" if index in failed else None,
            )
            for index in range(count)
        ]

    return build
