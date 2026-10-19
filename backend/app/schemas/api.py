"""Public query and response contracts; all ranges use [start_time, end_time)."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.contracts import (
    IncidentOut,
    IntegrationSummary,
    MetricsOut,
    RefreshOut,
)

HealthStatus = Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Must match the workspace token tenant; cross-tenant requests return 403.",
    )
    start_time: AwareDatetime | None = Field(
        default=None, description="Inclusive ISO-8601 time bound with a timezone."
    )
    end_time: AwareDatetime | None = Field(
        default=None,
        description="Exclusive ISO-8601 time bound with a timezone; must be later than start_time.",
    )

    @model_validator(mode="after")
    def ordered(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("start_time must be earlier than end_time")
        return self


class IntegrationFilters(TimeRange):
    health_status: HealthStatus | None = None
    integration_type: str | None = Field(default=None, min_length=1, max_length=64)


class IntegrationListQuery(IntegrationFilters):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class HistoryQuery(TimeRange):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class IncidentQuery(HistoryQuery):
    state: Literal["OPEN", "RESOLVED"] | None = None


class ProbeOut(BaseModel):
    status: Literal["ok", "ready"]


class ErrorOut(BaseModel):
    detail: str
    code: str


class IntegrationListOut(BaseModel):
    tenant_id: str
    total: int
    limit: int
    offset: int
    items: list[IntegrationSummary]


class StatusCounts(BaseModel):
    HEALTHY: int = 0
    DEGRADED: int = 0
    UNHEALTHY: int = 0
    UNKNOWN: int = 0


class HealthSummaryOut(BaseModel):
    tenant_id: str
    generated_at: datetime
    total_integrations: int
    status_counts: StatusCounts
    current_evidence_status_counts: StatusCounts
    stale_integrations: int
    open_incidents: int
    latest_evaluated_at: datetime | None


class MetricPointOut(BaseModel):
    id: str
    window_start: datetime
    window_end: datetime
    calculated_at: datetime
    metrics: MetricsOut


class MetricsHistoryOut(BaseModel):
    tenant_id: str
    integration_id: str
    total: int
    limit: int
    offset: int
    items: list[MetricPointOut]


class IncidentHistoryOut(BaseModel):
    tenant_id: str
    integration_id: str
    total: int
    limit: int
    offset: int
    items: list[IncidentOut]


class WorkspaceIncidentsOut(BaseModel):
    tenant_id: str
    total: int
    limit: int
    offset: int
    items: list[IncidentOut]


class CronOut(BaseModel):
    results: list[RefreshOut]


class TenantOption(BaseModel):
    id: str
    name: str


class WorkspaceOut(BaseModel):
    tenant_id: str
    tenant_name: str
    role: Literal["reader", "operator"]
    mode: Literal["demo", "test", "production"]
    can_switch_tenants: bool
    tenants: list[TenantOption]
