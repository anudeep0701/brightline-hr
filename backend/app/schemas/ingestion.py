"""Envelope validation is separate from per-record validation for partial acceptance."""

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field

from app.schemas.contracts import LogInput


class RequestEventInput(LogInput):
    event_id: str = Field(
        validation_alias=AliasChoices("event_id", "request_id"),
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_.:-]+$",
    )
    occurred_at: datetime = Field(
        validation_alias=AliasChoices("occurred_at", "timestamp")
    )
    status_code: int = Field(
        validation_alias=AliasChoices("status_code", "http_status"), ge=100, le=599
    )
    tenant_id: str | None = Field(default=None, min_length=1, max_length=64)
    integration_name: str | None = Field(default=None, max_length=160)
    integration_type: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=2000)
    scenario: str | None = Field(default=None, max_length=64)
    latency_target_ms: int | None = Field(default=None, gt=0)


class RequestBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[Any] = Field(min_length=1, max_length=1000)


class Rejection(BaseModel):
    index: int
    code: str
    fields: list[str] = Field(default_factory=list)


class IngestResult(BaseModel):
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    rejections: list[Rejection] = Field(default_factory=list)

    @computed_field
    @property
    def validation_errors(self) -> list[Rejection]:
        """Canonical safe per-record errors; rejections is retained for compatibility."""
        return self.rejections

    @computed_field
    @property
    def inserted(self) -> int:
        """Deprecated compatibility alias for /logs callers."""
        return self.accepted


class IngestFailure(IngestResult):
    detail: str
    code: str


class UploadPreview(BaseModel):
    total_records: int
    valid_records: int
    duplicates: int
    rejected_records: int
    unknown_integrations: int
    validation_errors: list[Rejection]
    can_import: bool
    file_digest: str
