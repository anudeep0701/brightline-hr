"""Advisory output only: deliberately contains no health classification field."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class EnrichmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1200)
    likely_issue_category: Literal[
        "auth",
        "rate_limit",
        "upstream",
        "timeout",
        "validation",
        "other",
        "latency",
        "insufficient_evidence",
        "unknown",
    ]
    suggested_checks: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        max_length=5
    )
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    what_changed: str = Field(min_length=1, max_length=1200)

    # String item limits also become part of the provider's structured-output schema.
    # Confidence describes this advisory interpretation, never the health decision.


InvestigationTopic = Literal[
    "why_unhealthy",
    "previous_healthy",
    "error_driver",
    "investigate_first",
    "escalation",
    "error_or_latency",
    "recovery",
]


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: InvestigationTopic
    incident_id: str | None = Field(default=None, min_length=1, max_length=36)


class GroundedPlan(BaseModel):
    """AI selects known facts/checks; no free-form factual claims or tool actions."""

    model_config = ConfigDict(extra="forbid")
    summary_fact_ids: list[Annotated[str, Field(max_length=64)]] = Field(
        min_length=1, max_length=4
    )
    change_fact_ids: list[Annotated[str, Field(max_length=64)]] = Field(
        min_length=1, max_length=3
    )
    likely_issue_category: str = Field(max_length=32)
    check_ids: list[Annotated[str, Field(max_length=64)]] = Field(
        min_length=1, max_length=3
    )
    confidence: Literal["high", "medium", "low"]


class AIAuditOut(BaseModel):
    tenant_id: str
    integration_id: str
    incident_id: str | None
    snapshot_id: str
    health_state: str
    current_evidence_status: str
    freshness_status: str
    evidence_at: str
    generated_at: str
    model: str | None
    fallback_used: bool
    evidence_digest: str
    topic: str
    failure_category: str | None = None
    requested_model: str | None = None
    duration_ms: int | None = None
    selected_fact_ids: list[str] = Field(default_factory=list)
    selected_change_ids: list[str] = Field(default_factory=list)
    selected_check_ids: list[str] = Field(default_factory=list)


class InvestigationOut(BaseModel):
    report: EnrichmentReport
    source: str
    fallback_code: str | None
    audit: AIAuditOut
