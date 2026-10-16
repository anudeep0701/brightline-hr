from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.metrics.categories import error_category, is_timeout
from app.schemas.enrichment import AIAuditOut, EnrichmentReport


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
        self.timed_out = is_timeout(self.status_code, self.timed_out)
        category = error_category(self.status_code, self.timed_out)
        if category == "none" and self.error_category != "none":
            raise ValueError("Successful response cannot have an error category")
        self.error_category = category
        return self


class LogBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logs: list[Any] = Field(min_length=1, max_length=1000)


class ErrorCategoryOut(BaseModel):
    category: str
    count: int
    fraction_of_errors: float


class BaselineOut(BaseModel):
    request_count: int
    error_rate: float | None
    timeout_rate: float | None = None
    p95_ms: float | None
    window_start: datetime
    window_end: datetime


class MetricsOut(BaseModel):
    request_count: int
    error_count: int
    success_count: int | None = None
    timeout_count: int | None = None
    timeout_rate: float | None = None
    p50_ms: float | None = None
    p99_ms: float | None = None
    top_error_categories: list[ErrorCategoryOut] = Field(default_factory=list)
    baseline: BaselineOut | None = None
    error_rate: float | None
    p95_ms: float | None
    last_request_at: datetime | None
    daily_request_count: int
    daily_error_rate: float | None
    error_categories: dict[str, int]


class EvidenceOut(BaseModel):
    policy_version: str
    thresholds: dict[str, int | float | bool]
    metrics: MetricsOut
    window_start: datetime
    window_end: datetime
    reasons: list[str]
    configuration_fingerprint: str | None = None
    signal_reason_codes: list[str] = Field(default_factory=list)
    baseline_used: bool = False
    baseline_reason_code: str | None = None
    hysteresis: dict[str, Any] = Field(default_factory=dict)
    continuity: bool = False
    recovery_thresholds_met: bool = False


class IntegrationOut(BaseModel):
    tenant_id: str
    id: str
    name: str
    category: str
    owner: str
    latency_target_ms: int
    max_gap_minutes: int
    evaluation_window_minutes: int
    refresh_minutes: int
    min_requests: int


class SnapshotOut(BaseModel):
    id: str
    tenant_id: str
    integration_id: str
    bucket: datetime
    evaluated_at: datetime
    status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]
    observed_status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]
    metrics: MetricsOut
    evidence_sufficient: bool
    confidence: float
    reason_code: str
    reason_text: str
    bad_window_streak: int
    degraded_window_streak: int
    healthy_window_streak: int
    score: int | None = None
    evidence: EvidenceOut


class FreshnessOut(BaseModel):
    status: Literal["RECENT_TRAFFIC", "STALE_TELEMETRY", "NO_TELEMETRY"]
    current_evidence_status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]
    last_event_at: datetime | None
    last_event_received_at: datetime | None
    last_evaluated_at: datetime | None
    evaluation_overdue: bool
    max_gap_minutes: int


class IncidentOut(BaseModel):
    id: str
    tenant_id: str
    integration_id: str
    opening_snapshot_id: str
    last_snapshot_id: str
    opened_at: datetime
    resolved_at: datetime | None = None
    recovery_streak: int
    opening_reason_code: str | None = None
    opening_reason_text: str | None = None
    recovery_began_at: datetime | None = None
    recovery_condition: str | None = None
    healthy_windows_required: int | None = None
    healthy_windows_observed: int = 0
    resolution_snapshot_id: str | None = None


class IntegrationSummary(BaseModel):
    freshness: FreshnessOut | None = None
    previous_snapshot: SnapshotOut | None = None
    integration: IntegrationOut
    snapshot: SnapshotOut | None
    stale: bool


class OperationalImpactOut(BaseModel):
    period_start: datetime
    period_end: datetime
    integrations_requiring_attention: int
    healthy_percentage: float | None
    unknown_integrations: int
    stale_or_absent_integrations: int
    incidents_detected: int
    recovered_incidents: int
    mean_confirmed_incident_duration_seconds: float | None


class DashboardOut(BaseModel):
    operational_impact: OperationalImpactOut
    tenant: str
    mode: str
    server_time: datetime
    refresh_seconds: int
    integrations: list[IntegrationSummary]
    incidents: list[IncidentOut]


class LogOut(LogInput):
    tenant_id: str


class EnrichmentOut(BaseModel):
    audit: AIAuditOut | None = None
    id: str
    snapshot_id: str
    generated_at: datetime
    source: str
    explanation: str
    evidence_digest: str
    report: EnrichmentReport | None
    evidence_payload: dict | None
    prompt_version: str
    fallback_code: str | None


class DetailOut(BaseModel):
    freshness: FreshnessOut | None = None
    enrichment: EnrichmentOut | None = None
    integration: IntegrationOut
    snapshot: SnapshotOut | None
    history: list[SnapshotOut]
    logs: list[LogOut]
    incidents: list[IncidentOut]


class RefreshOut(BaseModel):
    created: int
    bucket: datetime
