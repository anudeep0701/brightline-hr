"""Typed, read-only operational questions and cited answers."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AssistantQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=600)
    scope: Literal["workspace", "integration", "incident"] = "workspace"
    integration_id: str | None = Field(default=None, min_length=1, max_length=64)
    incident_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("question", mode="before")
    @classmethod
    def normalize(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def scope_shape(self):
        if self.scope == "workspace" and (self.integration_id or self.incident_id):
            raise ValueError("Workspace scope cannot select an integration or incident")
        if self.scope != "workspace" and not self.integration_id:
            raise ValueError("Selected scope requires an integration")
        if (self.scope == "incident") != bool(self.incident_id):
            raise ValueError("Incident scope requires exactly one selected incident")
        return self


class AssistantPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_fact_ids: list[Annotated[str, Field(max_length=32)]] = Field(
        min_length=1, max_length=6
    )
    check_ids: list[Annotated[str, Field(max_length=32)]] = Field(max_length=3)
    confidence: Literal["high", "medium", "low"]


class EvidenceReference(BaseModel):
    id: str
    label: str
    value: str
    observed_at: datetime | None = None
    integration_id: str | None = None
    incident_id: str | None = None
    integration_name: str | None = None
    health_status: str | None = None
    observed_status: str | None = None
    error_rate: float | None = None
    next_check: str | None = None
    active_incident: bool = False
    stale_evidence: bool = False
    material_change: bool = False


class AssistantPriority(BaseModel):
    integration_id: str
    name: str
    status: str
    reason: str
    next_check: str


class AssistantAudit(BaseModel):
    request_id: str
    tenant_id: str
    scope: str
    integration_id: str | None
    incident_id: str | None
    requested_model: str
    model: str | None = None
    generated_at: datetime
    duration_ms: int = 0
    fallback_used: bool = False
    failure_category: str | None = None
    provider_request_id: str | None = None
    evidence_digest: str | None = None
    cache_hit: bool = False


class AssistantAnswer(BaseModel):
    availability: Literal["LIVE", "FALLBACK", "REFUSED"]
    answer: str
    summary: str
    evidence: list[EvidenceReference]
    recommended_checks: list[str]
    confidence: Literal["high", "medium", "low"]
    limitations: list[str]
    audit: AssistantAudit
    intent: str = "why"
    priorities: list[AssistantPriority] = Field(default_factory=list)
    answer_evidence: list[EvidenceReference] = Field(default_factory=list)
    additional_evidence: list[EvidenceReference] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
