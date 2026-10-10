"""Immutable data contracts for datasets, analyses, and metric results."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

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


class ColumnProfile(FrozenModel):
    """Per-column summary used by ``profile_dataset``."""

    name: str = Field(min_length=1, max_length=64)
    semantic_type: Literal["date", "numeric_price"]
    missing_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    min: str | float | int | None = None
    max: str | float | int | None = None
    mean: float | None = None
    std: float | None = None


class DatasetProfile(FrozenModel):
    """Whole-dataset summary emitted by the profile service."""

    schema_version: Literal["profile-v1"] = "profile-v1"
    dataset_id: str
    asset_id: str
    row_count: int = Field(ge=0)
    columns: tuple[ColumnProfile, ...]
    quality_summary: dict[str, Any] = Field(default_factory=dict)


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


# ---------------------------------------------------------------------------
# M2: run state, tool calling envelopes, and persisted artifacts.
# ---------------------------------------------------------------------------


class RunMode(StrEnum):
    DEMO = "demo"
    REAL_AGENT = "real_agent"


class RunStatus(StrEnum):
    IDLE = "idle"
    DATA_READY = "data_ready"
    RUNNING = "running"
    NEEDS_CLARIFICATION = "needs_clarification"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class RunBudget(FrozenModel):
    max_model_interactions: int = Field(ge=0)
    max_tool_executions: int = Field(ge=0)
    max_same_validation_retry: int = Field(ge=0)
    max_retryable_network_errors: int = Field(ge=0)
    per_request_timeout_seconds: int = Field(ge=0)
    total_deadline_seconds: int = Field(ge=0)


class RunCounters(FrozenModel):
    model_interactions_used: int = Field(default=0, ge=0)
    tool_executions_used: int = Field(default=0, ge=0)
    same_validation_retries_used: int = Field(default=0, ge=0)
    retryable_network_errors_used: int = Field(default=0, ge=0)


class Run(FrozenModel):
    schema_version: Literal["run-v1"] = "run-v1"
    run_id: str
    session_id: str
    mode: RunMode
    status: RunStatus
    user_request: str
    dataset_ids: tuple[str, ...]
    analysis_id: str | None = None
    metrics_id: str | None = None
    chart_ids: tuple[str, ...] = ()
    report_id: str | None = None
    budgets: RunBudget
    counters: RunCounters = RunCounters()
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure: dict[str, Any] | None = None


class ToolStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ChartKind(StrEnum):
    NORMALIZED_PRICES = "normalized_prices"
    DRAWDOWN = "drawdown"
    ROLLING_RETURN = "rolling_return"
    ROLLING_VOLATILITY = "rolling_volatility"
    ROLLING_DRAWDOWN = "rolling_drawdown"


class RiskMetricName(StrEnum):
    """Risk metrics produced by ``compute_risk_metrics``.

    Deliberately distinct from ``MetricName`` so that ``compute_metrics``
    (basic indicators: period return, max drawdown, annualized
    volatility) and ``compute_risk_metrics`` (risk indicators: Sharpe,
    Sortino, Calmar, VaR, CVaR, etc.) own disjoint outputs. The
    design doc §5.2 / §2.6 mandates this separation to keep the
    evidence chain unambiguous.
    """

    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"
    VAR_95 = "var_95"
    CVAR_95 = "cvar_95"
    MEAN_DAILY_RETURN = "mean_daily_return"
    STD_DAILY_RETURN = "std_daily_return"
    ANNUALIZED_RETURN = "annualized_return"


class AnomalyKind(StrEnum):
    EXTREME_NEGATIVE_RETURN = "extreme_negative_return"
    EXTREME_POSITIVE_RETURN = "extreme_positive_return"
    PRICE_GAP = "price_gap"
    REPEATED_DATE = "repeated_date"


class AnomalySeverity(StrEnum):
    WARNING = "warning"
    INFO = "info"


class AnomalyItem(FrozenModel):
    date: str
    kind: AnomalyKind
    severity: AnomalySeverity
    value: float | None = None
    message: str


class AnomalyReport(FrozenModel):
    schema_version: Literal["anomaly-v1"] = "anomaly-v1"
    analysis_id: str
    asset_anomalies: tuple[tuple[str, tuple[AnomalyItem, ...]], ...]
    parameters: dict[str, float]


class RollingPoint(FrozenModel):
    date: str
    value: float | None


class RollingSeries(FrozenModel):
    asset_id: str
    metric: Literal[
        "rolling_return",
        "rolling_volatility",
        "rolling_drawdown",
        "rolling_sharpe",
    ]
    window: int = Field(ge=2)
    points: tuple[RollingPoint, ...]


class RollingReport(FrozenModel):
    schema_version: Literal["rolling-v1"] = "rolling-v1"
    analysis_id: str
    windows: tuple[int, ...]
    series: tuple[RollingSeries, ...]


# ---------------------------------------------------------------------------
# M6 — Planner layer contracts (AnalysisPlan, ResolvedPlan).
# ---------------------------------------------------------------------------


class Intent(StrEnum):
    """First-class action the user-visible intent maps to.

    Maps to the state machine / tool chain:

      data_quality  → list_datasets + inspect_dataset
      profile       → list_datasets + inspect_dataset + profile_dataset
      metrics       → list_datasets + inspect_dataset + prepare + compute
      chart         → list_datasets + inspect_dataset + prepare + compute + create_charts
      report        → full 5-tool chain + build_report
      clarify       → mark NEEDS_CLARIFICATION, no tools
      out_of_scope  → mark FAILED(OUT_OF_SCOPE), no tools
    """

    DATA_QUALITY = "data_quality"
    PROFILE = "profile"
    METRICS = "metrics"
    CHART = "chart"
    REPORT = "report"
    CLARIFY = "clarify"
    OUT_OF_SCOPE = "out_of_scope"


class AnalysisExtra(StrEnum):
    """Optional sub-actions attached to ``metrics`` / ``data_quality`` /
    ``chart`` intents. Stored on ``AnalysisPlan.extras``.

    The planner sets these from user keywords; the executor branches on
    them after the main intent pipeline finishes.
    """

    DESCRIBE_PRICE_SERIES = "describe_price_series"
    RISK = "risk"
    ANOMALIES = "anomalies"
    ROLLING = "rolling"


class DateRange(FrozenModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _validate_dates(self) -> "DateRange":
        if self.start > self.end:
            raise ValueError("date_range.start must be on or before date_range.end")
        return self


class AnalysisPlan(FrozenModel):
    """Structured output of the Planner layer.

    ``intent`` decides the executor branch; ``dataset_refs`` are user-facing
    asset_ids or filenames that the validator resolves to session UUIDs;
    ``metrics`` and ``charts`` are subsets of the closed enums. The
    validator fills in ``resolved_dataset_ids`` and clamps the date range
    to dataset coverage. ``extras`` is an optional list of
    ``AnalysisExtra`` actions that hang off the main pipeline (describe /
    summarize/ risk / anomalies / rolling).
    """

    schema_version: Literal["plan-v1"] = "plan-v1"
    intent: Intent
    dataset_refs: tuple[str, ...] = ()
    date_range: DateRange | None = None
    metrics: tuple[MetricName, ...] = ()
    charts: tuple[ChartKind, ...] = ()
    extras: tuple["AnalysisExtra", ...] = ()
    clarifying_question: str | None = None
    user_visible_summary: str = ""

    @model_validator(mode="after")
    def _validate_intent_requirements(self) -> "AnalysisPlan":
        if self.intent in (Intent.METRICS, Intent.REPORT, Intent.CHART):
            if not self.metrics and self.intent is not Intent.CHART:
                raise ValueError(
                    f"intent={self.intent.value} requires at least one metric in `metrics`"
                )
        if self.intent is Intent.CLARIFY and not self.clarifying_question:
            raise ValueError("intent=clarify requires a clarifying_question")
        if self.user_visible_summary and len(self.user_visible_summary) > 500:
            raise ValueError("user_visible_summary must be ≤ 500 characters")
        return self


class ResolvedPlan(FrozenModel):
    """``AnalysisPlan`` after PlanValidator resolves references and dates.

    ``resolved_dataset_ids`` is always a tuple of UUIDs from the current
    session. ``effective_start`` / ``effective_end`` are the clamped dates
    that get fed into ``prepare_analysis``.
    """

    schema_version: Literal["resolved-plan-v1"] = "resolved-plan-v1"
    intent: Intent
    resolved_dataset_ids: tuple[str, ...]
    date_range: DateRange | None
    effective_start: date | None = None
    effective_end: date | None = None
    metrics: tuple[MetricName, ...] = ()
    charts: tuple[ChartKind, ...] = ()
    extras: tuple["AnalysisExtra", ...] = ()
    clarifying_question: str | None = None
    user_visible_summary: str = ""
    plan_summary: str = ""


class ReportSection(StrEnum):
    OVERVIEW = "overview"
    DATA_SOURCES = "data_sources"
    DATA_QUALITY = "data_quality"
    METHODOLOGY = "methodology"
    METRICS_TABLE = "metrics_table"
    LIMITATIONS = "limitations"
    RUN_INFO = "run_info"


class EvidenceRef(FrozenModel):
    kind: Literal["dataset", "analysis", "metrics", "chart", "report"]
    ref_id: str
    analysis_id: str | None = None


class Provenance(FrozenModel):
    session_id: str
    run_id: str
    dataset_ids: tuple[str, ...]
    analysis_id: str | None = None
    metrics_id: str | None = None
    chart_ids: tuple[str, ...] = ()


class ToolResultEnvelope(FrozenModel):
    ok: bool
    run_id: str
    tool_call_id: str
    data: dict[str, Any] | None = None
    warnings: tuple[dict[str, Any], ...] = ()
    error: dict[str, Any] | None = None
    provenance: Provenance


class ToolCallRecord(FrozenModel):
    tool_call_id: str
    run_id: str
    tool_name: str
    arguments_redacted: dict[str, Any]
    status: ToolStatus
    started_at: datetime
    completed_at: datetime | None = None
    result_envelope: ToolResultEnvelope | None = None
    error_code: str | None = None


class AssetSeriesSummary(FrozenModel):
    """Per-asset descriptive statistics for ``PriceSeriesSummary``."""

    asset_id: str
    start_price: float | None
    end_price: float | None
    min_price: float | None
    min_price_date: str | None
    max_price: float | None
    max_price_date: str | None
    total_return: float | None
    up_days: int | None
    down_days: int | None
    flat_days: int | None
    max_daily_gain: float | None
    max_daily_gain_date: str | None
    max_daily_loss: float | None
    max_daily_loss_date: str | None
    longest_up_streak: int | None
    longest_down_streak: int | None


class PriceSeriesSummary(FrozenModel):
    """Output of the descriptive service.

    Captures summary statistics for every asset in the prepared analysis.
    Intended to be human-readable from the WebUI bubble and persisted
    alongside the run.
    """

    schema_version: Literal["describe-v1"] = "describe-v1"
    analysis_id: str
    effective_start: str
    effective_end: str
    alignment_policy: str
    assets: tuple[AssetSeriesSummary, ...]
    assumptions: str = ""


class AssetRiskResult(FrozenModel):
    """Per-asset risk indicators produced by ``RiskAnalysisService``."""

    asset_id: str
    values: dict[RiskMetricName, float]
    unavailable: dict[str, str] = Field(default_factory=dict)


class RiskAnalysisResult(FrozenModel):
    """Output of the risk analysis service."""

    schema_version: Literal["risk-v1"] = "risk-v1"
    analysis_id: str
    annualization_factor: int = Field(ge=1)
    risk_free_rate: float
    confidence_level: float
    assets: tuple[AssetRiskResult, ...]
    assumptions: str = ""


class ChartArtifact(FrozenModel):
    chart_id: str
    run_id: str
    analysis_id: str
    kind: ChartKind
    png_path: str
    data_path: str
    data_sha256: str
    title: str
    x_label: str
    y_label: str
    series_labels: tuple[str, ...]
    created_at: datetime


class ReportArtifact(FrozenModel):
    report_id: str
    run_id: str
    analysis_id: str
    metrics_id: str
    chart_ids: tuple[str, ...]
    section_ids: tuple[ReportSection, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    markdown_path: str
    created_at: datetime
