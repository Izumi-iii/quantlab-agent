"""Immutable data contracts for datasets, analyses, and metric results."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PriceBasis(StrEnum):
    UNADJUSTED = "unadjusted"
    FORWARD_ADJUSTED = "forward_adjusted"
    BACKWARD_ADJUSTED = "backward_adjusted"
    TOTAL_RETURN_INDEX = "total_return_index"
    UNKNOWN = "unknown"


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class MetricName(StrEnum):
    PERIOD_RETURN = "period_return"
    ANNUALIZED_VOLATILITY = "annualized_volatility"
    MAX_DRAWDOWN = "max_drawdown"


class DatasetMetadata(FrozenModel):
    asset_id: str = Field(min_length=1, max_length=64)
    source_name: str = Field(default="user_provided_unverified", min_length=1, max_length=200)
    source_url: str | None = Field(default=None, max_length=2_000)
    price_basis: PriceBasis = PriceBasis.UNKNOWN
    currency: str = Field(default="UNKNOWN", min_length=1, max_length=12)
    frequency: str = Field(default="daily", min_length=1, max_length=32)
    calendar_label: str = Field(default="unknown", min_length=1, max_length=100)
    daily_series_complete: bool = False
    is_synthetic: bool = False

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("asset_id cannot be blank")
        if any(character in cleaned for character in ("/", "\\", "\x00")):
            raise ValueError("asset_id cannot contain path separators or NUL")
        return cleaned

    @field_validator("currency", "frequency")
    @classmethod
    def normalize_upper_or_lower(cls, value: str, info: Any) -> str:
        cleaned = value.strip()
        return cleaned.upper() if info.field_name == "currency" else cleaned.lower()


class QualityIssue(FrozenModel):
    severity: IssueSeverity
    code: str
    message: str
    row_numbers: tuple[int, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


class QualityReport(FrozenModel):
    issues: tuple[QualityIssue, ...] = ()
    transformations: tuple[str, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is IssueSeverity.WARNING)


class DatasetManifest(FrozenModel):
    schema_version: str = "dataset-v1"
    dataset_id: str
    session_id: str
    metadata: DatasetMetadata
    raw_sha256: str
    normalized_sha256: str
    date_min: date
    date_max: date
    row_count: int = Field(ge=1)
    imported_at: datetime
    quality_report: QualityReport


class PricePoint(FrozenModel):
    date: date
    close: float = Field(gt=0, allow_inf_nan=False)


class CapabilityDecision(FrozenModel):
    available: bool
    reason: str | None = None

    @model_validator(mode="after")
    def require_reason_when_unavailable(self) -> "CapabilityDecision":
        if not self.available and not self.reason:
            raise ValueError("an unavailable capability requires a reason")
        return self


class AnalysisSpec(FrozenModel):
    schema_version: str = "analysis-v1"
    analysis_id: str
    session_id: str
    dataset_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    requested_start: date
    requested_end: date
    effective_start: date
    effective_end: date
    requested_metrics: tuple[MetricName, ...]
    alignment_policy: str
    excluded_observations: dict[str, int]
    capabilities: dict[MetricName, CapabilityDecision]
    annualization_factor: int = Field(default=252, gt=0)


class MetricValue(FrozenModel):
    value: float | None
    observations: int = Field(ge=0)
    unavailable_reason: str | None = None
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_availability(self) -> "MetricValue":
        if self.value is None and not self.unavailable_reason:
            raise ValueError("an unavailable metric requires a reason")
        if self.value is not None and self.unavailable_reason is not None:
            raise ValueError("an available metric cannot have an unavailable reason")
        return self


class AssetMetricResult(FrozenModel):
    asset_id: str
    metrics: dict[MetricName, MetricValue]


class MetricResult(FrozenModel):
    schema_version: str = "metrics-v1"
    metrics_id: str
    analysis_id: str
    calculation_version: str = "metrics-v1"
    assets: tuple[AssetMetricResult, ...]
