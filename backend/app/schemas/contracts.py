from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")
    integration_id: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    status_code: int = Field(ge=100, le=599)
    latency_ms: float = Field(ge=0, le=3600000, allow_inf_nan=False)
    timed_out: bool = False
    error_category: Literal[
        "none", "auth", "rate_limit", "upstream", "timeout", "validation", "other"
    ] = "none"

    @field_validator("occurred_at")
    @classmethod
    def utc_only(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def consistent_error(self):
        if self.timed_out:
            self.error_category = "timeout"
        elif self.status_code == 429:
            self.error_category = "rate_limit"
        elif self.status_code in (401, 403):
            self.error_category = "auth"
        elif self.status_code >= 500:
            self.error_category = "upstream"
        elif self.status_code >= 400:
            self.error_category = "validation"
        elif self.error_category != "none":
            raise ValueError("Successful response cannot have an error category")
        return self


class LogBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logs: list[LogInput] = Field(min_length=1, max_length=1000)


class ExplanationText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str = Field(min_length=1, max_length=2400)


class MetricsOut(BaseModel):
    request_count: int
    error_count: int
    error_rate: float | None
    p95_ms: float | None
    last_request_at: datetime | None
    daily_request_count: int
    daily_error_rate: float | None
    error_categories: dict[str, int]


class EvidenceOut(BaseModel):
    policy_version: str
    thresholds: dict[str, float]
    metrics: MetricsOut
    window_start: datetime
    window_end: datetime
    reasons: list[str]


class IntegrationOut(BaseModel):
    tenant_id: str
    id: str
    name: str
    category: str
    owner: str
    latency_target_ms: int
    max_gap_minutes: int


class SnapshotOut(BaseModel):
    id: str
    tenant_id: str
    integration_id: str
    bucket: datetime
    evaluated_at: datetime
    status: Literal["healthy", "degraded", "unhealthy", "unknown"]
    score: int | None = None
    evidence: EvidenceOut


class IncidentOut(BaseModel):
    id: str
    tenant_id: str
    integration_id: str
    opening_snapshot_id: str
    last_snapshot_id: str
    opened_at: datetime
    resolved_at: datetime | None = None
    recovery_streak: int


class IntegrationSummary(BaseModel):
    integration: IntegrationOut
    snapshot: SnapshotOut | None
    stale: bool


class DashboardOut(BaseModel):
    tenant: str
    mode: str
    server_time: datetime
    refresh_seconds: int
    integrations: list[IntegrationSummary]
    incidents: list[IncidentOut]


class LogOut(LogInput):
    tenant_id: str


class DetailOut(BaseModel):
    integration: IntegrationOut
    snapshot: SnapshotOut | None
    history: list[SnapshotOut]
    logs: list[LogOut]
    incidents: list[IncidentOut]


class EnrichmentOut(BaseModel):
    id: str
    snapshot_id: str
    generated_at: datetime
    source: str
    explanation: str
    evidence_digest: str


class IngestOut(BaseModel):
    inserted: int
    duplicates: int


class RefreshOut(BaseModel):
    created: int
    bucket: datetime
