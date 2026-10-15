import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CRON_SECRET"] = "test-cron-secret"
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
