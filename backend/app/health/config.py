"""Single source of policy defaults; values persist per integration in PostgreSQL."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

POLICY_VERSION = "2026-10-v2"


class HealthPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        from_attributes=True,
        strict=True,
        validate_default=True,
    )
    evaluation_window_minutes: int = Field(default=15, ge=5, le=1440)
    refresh_minutes: int = Field(default=5, ge=5, le=15)
    min_requests: int = Field(default=20, ge=1)
    latency_target_ms: int = Field(default=1000, gt=0)
    max_gap_minutes: int = Field(default=30, ge=1)
    error_warning: float = Field(default=0.01, gt=0, le=1, allow_inf_nan=False)
    error_critical: float = Field(default=0.05, gt=0, le=1, allow_inf_nan=False)
    error_recovery: float = Field(default=0.005, ge=0, le=1, allow_inf_nan=False)
    timeout_warning: float = Field(default=0.01, gt=0, le=1, allow_inf_nan=False)
    timeout_critical: float = Field(default=0.05, gt=0, le=1, allow_inf_nan=False)
    timeout_recovery: float = Field(default=0.005, ge=0, le=1, allow_inf_nan=False)
    latency_warning_multiplier: float = Field(default=1.5, gt=1, allow_inf_nan=False)
    latency_critical_multiplier: float = Field(default=3, gt=1, allow_inf_nan=False)
    latency_recovery_multiplier: float = Field(default=1.25, ge=1, allow_inf_nan=False)
    baseline_enabled: bool = True
    baseline_lookback_minutes: int = Field(default=1440, ge=5, le=1440)
    baseline_min_requests: int = Field(default=100, ge=1)
    baseline_min_delta_ms: float = Field(default=100, ge=0, allow_inf_nan=False)
    unhealthy_bad_windows: int = Field(default=2, ge=2, le=20)
    healthy_recovery_windows: int = Field(default=2, ge=2, le=20)
    sustained_degraded_windows: int = Field(default=3, ge=2, le=100)
    top_error_limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def coherent_policy(self):
        if self.refresh_minutes % 5:
            raise ValueError("Refresh cadence must be 5, 10 or 15 minutes")
        if self.evaluation_window_minutes < self.refresh_minutes:
            raise ValueError(
                "Evaluation window must cover at least one refresh interval"
            )
        if not self.error_recovery < self.error_warning < self.error_critical:
            raise ValueError("Error thresholds require recovery < warning < critical")
        if not self.timeout_recovery < self.timeout_warning < self.timeout_critical:
            raise ValueError("Timeout thresholds require recovery < warning < critical")
        if (
            not self.latency_recovery_multiplier
            < self.latency_warning_multiplier
            < self.latency_critical_multiplier
        ):
            raise ValueError("Latency thresholds require recovery < warning < critical")
        if self.sustained_degraded_windows < self.unhealthy_bad_windows:
            raise ValueError(
                "Sustained degradation cannot bypass the bad-window confirmation requirement"
            )
        return self


DEFAULT_POLICY = HealthPolicy()
