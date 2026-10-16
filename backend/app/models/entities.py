from datetime import datetime, timezone
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.health.config import DEFAULT_POLICY


class UTCDateTime(TypeDecorator):
    """TIMESTAMPTZ on PostgreSQL; normalize reads and reject naive writes everywhere."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # SQLite loses timezone metadata; its bound values above are always UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)


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


class IngestionAPIKey(Base):
    __tablename__ = "ingestion_api_keys"
    __table_args__ = (
        CheckConstraint("length(digest) = 64", name="ck_ingestion_key_digest"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Integration(Base):
    __tablename__ = "integrations"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(64))
    owner: Mapped[str] = mapped_column(String(160))
    config: Mapped["IntegrationConfig"] = relationship(
        back_populates="integration",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        # Preserve the existing constructor/API while storing settings in one table.
        target = kwargs.pop("latency_target_ms", DEFAULT_POLICY.latency_target_ms)
        gap = kwargs.pop("max_gap_minutes", DEFAULT_POLICY.max_gap_minutes)
        super().__init__(**kwargs)
        self.config = IntegrationConfig(
            **dict(
                DEFAULT_POLICY.model_dump(),
                latency_target_ms=target,
                max_gap_minutes=gap,
            )
        )

    @property
    def latency_target_ms(self):
        return self.config.latency_target_ms

    @latency_target_ms.setter
    def latency_target_ms(self, value):
        self.config.latency_target_ms = value

    @property
    def max_gap_minutes(self):
        return self.config.max_gap_minutes

    @max_gap_minutes.setter
    def max_gap_minutes(self, value):
        self.config.max_gap_minutes = value


class IntegrationConfig(Base):
    __tablename__ = "integration_config"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        CheckConstraint(
            "evaluation_window_minutes >= refresh_minutes AND evaluation_window_minutes BETWEEN 5 AND 1440 AND refresh_minutes IN (5,10,15)",
            name="ck_config_windows",
        ),
        CheckConstraint(
            "min_requests >= 1 AND baseline_min_requests >= 1 AND baseline_lookback_minutes BETWEEN 5 AND 1440 AND baseline_min_delta_ms >= 0 AND top_error_limit BETWEEN 1 AND 20",
            name="ck_config_evidence",
        ),
        CheckConstraint(
            "0 <= error_recovery AND error_recovery < error_warning AND error_warning < error_critical AND error_critical <= 1",
            name="ck_config_error_rates",
        ),
        CheckConstraint(
            "0 <= timeout_recovery AND timeout_recovery < timeout_warning AND timeout_warning < timeout_critical AND timeout_critical <= 1",
            name="ck_config_timeout_rates",
        ),
        CheckConstraint(
            "1 <= latency_recovery_multiplier AND latency_recovery_multiplier < latency_warning_multiplier AND latency_warning_multiplier < latency_critical_multiplier",
            name="ck_config_latency",
        ),
        CheckConstraint(
            "unhealthy_bad_windows BETWEEN 2 AND 20 AND healthy_recovery_windows BETWEEN 2 AND 20 AND sustained_degraded_windows BETWEEN unhealthy_bad_windows AND 100",
            name="ck_config_hysteresis",
        ),
        CheckConstraint(
            "latency_target_ms > 0 AND max_gap_minutes > 0",
            name="ck_config_positive_targets",
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    integration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    latency_target_ms: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.latency_target_ms
    )
    max_gap_minutes: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.max_gap_minutes
    )
    evaluation_window_minutes: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.evaluation_window_minutes
    )
    refresh_minutes: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.refresh_minutes
    )
    min_requests: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.min_requests
    )
    error_warning: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.error_warning
    )
    error_critical: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.error_critical
    )
    error_recovery: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.error_recovery
    )
    timeout_warning: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.timeout_warning
    )
    timeout_critical: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.timeout_critical
    )
    timeout_recovery: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.timeout_recovery
    )
    latency_warning_multiplier: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.latency_warning_multiplier
    )
    latency_critical_multiplier: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.latency_critical_multiplier
    )
    latency_recovery_multiplier: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.latency_recovery_multiplier
    )
    baseline_enabled: Mapped[bool] = mapped_column(
        Boolean, default=DEFAULT_POLICY.baseline_enabled
    )
    baseline_lookback_minutes: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.baseline_lookback_minutes
    )
    baseline_min_requests: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.baseline_min_requests
    )
    baseline_min_delta_ms: Mapped[float] = mapped_column(
        Float, default=DEFAULT_POLICY.baseline_min_delta_ms
    )
    unhealthy_bad_windows: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.unhealthy_bad_windows
    )
    healthy_recovery_windows: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.healthy_recovery_windows
    )
    sustained_degraded_windows: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.sustained_degraded_windows
    )
    top_error_limit: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_POLICY.top_error_limit
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
    integration: Mapped[Integration] = relationship(back_populates="config")


class RequestEvent(Base):
    __tablename__ = "request_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        CheckConstraint(
            "status_code >= 100 AND status_code <= 599 AND latency_ms >= 0",
            name="ck_log_values",
        ),
        CheckConstraint(
            "source_type IN ('LIVE_API','FILE_IMPORT','DEMO','UNKNOWN')",
            name="ck_event_source_type",
        ),
        Index("ix_logs_window", "tenant_id", "integration_id", "occurred_at"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    integration_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    error_category: Mapped[str] = mapped_column(String(32), default="none")

    source_type: Mapped[str] = mapped_column(
        String(16), default="UNKNOWN", server_default="UNKNOWN"
    )
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    integration_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    integration_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_event: Mapped[dict] = mapped_column(JSON, default=dict)


class MetricRollup(Base):
    __tablename__ = "metric_rollups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        UniqueConstraint("tenant_id", "integration_id", "window_start", "window_end"),
        UniqueConstraint("tenant_id", "integration_id", "id"),
        CheckConstraint("window_end > window_start", name="ck_rollup_window"),
        Index("ix_rollups_window", "tenant_id", "integration_id", "window_end"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    integration_id: Mapped[str] = mapped_column(String(64))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    calculated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    metrics: Mapped[dict] = mapped_column(JSON)


class HealthSnapshot(Base):
    __tablename__ = "health_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integrations.tenant_id", "integrations.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "integration_id", "metric_rollup_id"],
            [
                "metric_rollups.tenant_id",
                "metric_rollups.integration_id",
                "metric_rollups.id",
            ],
        ),
        UniqueConstraint("tenant_id", "integration_id", "bucket"),
        UniqueConstraint("tenant_id", "integration_id", "id"),
        CheckConstraint(
            "status IN ('HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNKNOWN')",
            name="ck_health_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1 AND bad_window_streak >= 0 AND degraded_window_streak >= 0 AND healthy_window_streak >= 0",
            name="ck_health_evidence",
        ),
        CheckConstraint(
            "observed_status IN ('HEALTHY','DEGRADED','UNHEALTHY','UNKNOWN')",
            name="ck_health_observed_status",
        ),
        Index("ix_snapshots_history", "tenant_id", "integration_id", "bucket"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    integration_id: Mapped[str] = mapped_column(String(64))
    metric_rollup_id: Mapped[str] = mapped_column(String(36))
    bucket: Mapped[datetime] = mapped_column(UTCDateTime())
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20))
    observed_status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    evidence_sufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    reason_code: Mapped[str] = mapped_column(String(64), default="LEGACY_SNAPSHOT")
    reason_text: Mapped[str] = mapped_column(
        String(2400), default="Historical decision; see evidence."
    )
    bad_window_streak: Mapped[int] = mapped_column(Integer, default=0)
    degraded_window_streak: Mapped[int] = mapped_column(Integer, default=0)
    healthy_window_streak: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON)


class HealthIncident(Base):
    __tablename__ = "health_incidents"
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
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    recovery_streak: Mapped[int] = mapped_column(Integer, default=0)


class Enrichment(Base):
    __tablename__ = "enrichments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id", "snapshot_id"],
            [
                "health_snapshots.tenant_id",
                "health_snapshots.integration_id",
                "health_snapshots.id",
            ],
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(64))
    integration_id: Mapped[str] = mapped_column(String(64))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("health_snapshots.id"), unique=True
    )
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(String(2400))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[str] = mapped_column(
        String(64), default="legacy-v1", server_default="legacy-v1"
    )
    fallback_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


# Compatibility names keep existing callers and public API field names stable.
RequestLog = RequestEvent
Snapshot = HealthSnapshot
Incident = HealthIncident
