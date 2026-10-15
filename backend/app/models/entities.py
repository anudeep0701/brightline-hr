from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_id():
    return str(uuid4())


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))


class AccessToken(Base):
    __tablename__ = "access_tokens"
    __table_args__ = (
        CheckConstraint("role IN ('reader', 'operator')", name="ck_token_role"),
    )
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="reader")


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (
        CheckConstraint(
            "latency_target_ms > 0 AND max_gap_minutes > 0", name="ck_positive_targets"
        ),
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(64))
    owner: Mapped[str] = mapped_column(String(160))
    latency_target_ms: Mapped[int] = mapped_column(Integer, default=1000)
    max_gap_minutes: Mapped[int] = mapped_column(Integer, default=30)


class RequestLog(Base):
    __tablename__ = "request_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        CheckConstraint(
            "status_code >= 100 AND status_code <= 599 AND latency_ms >= 0",
            name="ck_log_values",
        ),
        Index("ix_logs_window", "tenant_id", "integration_id", "occurred_at"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    integration_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    error_category: Mapped[str] = mapped_column(String(32), default="none")


class Snapshot(Base):
    __tablename__ = "health_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        UniqueConstraint("tenant_id", "integration_id", "bucket"),
        UniqueConstraint("tenant_id", "integration_id", "id"),
        CheckConstraint(
            "status IN ('healthy', 'degraded', 'unhealthy', 'unknown')",
            name="ck_health_status",
        ),
        Index("ix_snapshots_history", "tenant_id", "integration_id", "bucket"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    integration_id: Mapped[str] = mapped_column(String(64))
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "integration_id", "opening_snapshot_id"],
            [
                "health_snapshots.tenant_id",
                "health_snapshots.integration_id",
                "health_snapshots.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "integration_id", "last_snapshot_id"],
            [
                "health_snapshots.tenant_id",
                "health_snapshots.integration_id",
                "health_snapshots.id",
            ],
        ),
        Index(
            "ix_one_open_incident",
            "tenant_id",
            "integration_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    integration_id: Mapped[str] = mapped_column(String(64))
    opening_snapshot_id: Mapped[str] = mapped_column(ForeignKey("health_snapshots.id"))
    last_snapshot_id: Mapped[str] = mapped_column(ForeignKey("health_snapshots.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_streak: Mapped[int] = mapped_column(Integer, default=0)


class Enrichment(Base):
    __tablename__ = "enrichments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("health_snapshots.id"), unique=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(String(2400))
    evidence_digest: Mapped[str] = mapped_column(String(64))
