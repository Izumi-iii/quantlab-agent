"""ToolRegistry and the five tool handlers.

The handlers consume the existing application services
(``DatasetService``, ``AnalysisService``, ``ChartService``,
``ReportService``) via ``ToolContext`` and never write files or
construct DataFrames directly. All persistence flows through the
Protocols (``ports/stores.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    ChartArtifact,
    ChartKind,
    MetricName,
    Provenance,
    ToolCallRecord,
    ToolResultEnvelope,
    ToolStatus,
)
from quantlab_agent.ports.stores import (
    ChartStore,
    DatasetStore,
    ReportStore,
    RunStore,
)
from quantlab_agent.ports.tools import ToolContext, ToolHandler

# ---------------------------------------------------------------------------
# ToolDefinition — runtime struct, not Pydantic.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_description: str
    handler: ToolHandler
    tool_kind: Literal["read", "mutate"] = "mutate"


# ---------------------------------------------------------------------------
# Pydantic input models — ValidationError → PROTOCOL_ERROR.
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectDatasetInput(_StrictModel):
    dataset_id: str = Field(min_length=36, max_length=36)


class PrepareAnalysisInput(_StrictModel):
    dataset_ids: tuple[str, ...] = Field(min_length=1, max_length=2)
    requested_start: str = Field(min_length=10, max_length=10)
    requested_end: str = Field(min_length=10, max_length=10)
    requested_metrics: tuple[MetricName, ...] = Field(min_length=1)


class ComputeMetricsInput(_StrictModel):
    analysis_id: str = Field(min_length=36, max_length=36)


class CreateChartsInput(_StrictModel):
    analysis_id: str = Field(min_length=36, max_length=36)
    kinds: tuple[ChartKind, ...] = Field(min_length=1)


class BuildReportInput(_StrictModel):
    analysis_id: str = Field(min_length=36, max_length=36)
    metrics_id: str = Field(min_length=36, max_length=36)
    chart_ids: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_envelope(
    *,
    ok: bool,
    run_id: str,
    tool_call_id: str,
    provenance: Provenance,
    data: dict[str, Any] | None = None,
    warnings: tuple[dict[str, Any], ...] = (),
    error: dict[str, Any] | None = None,
) -> ToolResultEnvelope:
    return ToolResultEnvelope(
        ok=ok,
        run_id=run_id,
        tool_call_id=tool_call_id,
        data=data,
        warnings=warnings,
        error=error,
        provenance=provenance,
    )


def _handle_quantlab_error(
    exc: QuantLabError, *, run_id: str, tool_call_id: str, provenance: Provenance
) -> ToolResultEnvelope:
    return _make_envelope(
        ok=False,
        run_id=run_id,
        tool_call_id=tool_call_id,
        provenance=provenance,
        error=exc.as_dict(),
    )


def _handle_unexpected_error(
    exc: Exception, *, run_id: str, tool_call_id: str, provenance: Provenance
) -> ToolResultEnvelope:
    return _make_envelope(
        ok=False,
        run_id=run_id,
        tool_call_id=tool_call_id,
        provenance=provenance,
        error={
            "code": ErrorCode.TOOL_FAILURE.value,
            "message": "Tool handler raised an unexpected error.",
            "retryable": False,
            "details": {"exception": type(exc).__name__},
        },
    )


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _make_provenance(run: object) -> Provenance:
    return Provenance(
        session_id=getattr(run, "session_id"),
        run_id=getattr(run, "run_id"),
        dataset_ids=getattr(run, "dataset_ids", ()),
        analysis_id=getattr(run, "analysis_id", None),
        metrics_id=getattr(run, "metrics_id", None),
        chart_ids=getattr(run, "chart_ids", ()),
    )


def make_inspect_dataset_handler() -> ToolHandler:
    def handle(ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        assert isinstance(args, InspectDatasetInput)
        snapshot = ctx.dataset_store.get(args.dataset_id, ctx.session_id)
        manifest = snapshot.manifest
        return {
            "dataset_id": manifest.dataset_id,
            "asset_id": manifest.metadata.asset_id,
            "date_min": manifest.date_min.isoformat(),
            "date_max": manifest.date_max.isoformat(),
            "row_count": manifest.row_count,
            "quality_issues": [
                {
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in manifest.quality_report.issues
            ],
            "transformations": list(manifest.quality_report.transformations),
            "metadata": {
                "price_basis": manifest.metadata.price_basis.value,
                "currency": manifest.metadata.currency,
                "frequency": manifest.metadata.frequency,
                "calendar_label": manifest.metadata.calendar_label,
                "daily_series_complete": manifest.metadata.daily_series_complete,
                "is_synthetic": manifest.metadata.is_synthetic,
            },
        }

    return handle


def make_prepare_analysis_handler(
    *,
    analysis_service: AnalysisService,
    run_service: RunService,
) -> ToolHandler:
    from datetime import date as _date

    def handle(ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        assert isinstance(args, PrepareAnalysisInput)
        for dataset_id in args.dataset_ids:
            run_service.add_dataset(ctx.run_id, ctx.session_id, dataset_id)

        datasets = [
            ctx.dataset_store.get(dataset_id, ctx.session_id) for dataset_id in args.dataset_ids
        ]
        prepared = analysis_service.prepare(
            datasets,
            session_id=ctx.session_id,
            requested_start=_date.fromisoformat(args.requested_start),
            requested_end=_date.fromisoformat(args.requested_end),
            requested_metrics=args.requested_metrics,
        )
        run_service.bind_analysis(ctx.run_id, ctx.session_id, prepared.spec.analysis_id)

        # Persist the requested/effective range into the run's context_snapshot.
        run = run_service.get_run(ctx.run_id, ctx.session_id)
        snapshot = dict(run.context_snapshot)
        snapshot["requested_start"] = args.requested_start
        snapshot["requested_end"] = args.requested_end
        snapshot["effective_start"] = prepared.spec.effective_start.isoformat()
        snapshot["effective_end"] = prepared.spec.effective_end.isoformat()
        snapshot["alignment_policy"] = prepared.spec.alignment_policy
        snapshot["requested_metrics"] = [m.value for m in args.requested_metrics]
        run_service.update_context_snapshot(ctx.run_id, ctx.session_id, snapshot)

        return {
            "analysis_id": prepared.spec.analysis_id,
            "effective_start": prepared.spec.effective_start.isoformat(),
            "effective_end": prepared.spec.effective_end.isoformat(),
            "alignment_policy": prepared.spec.alignment_policy,
            "excluded_observations": dict(prepared.spec.excluded_observations),
            "capabilities": {
                metric.value: {
                    "available": decision.available,
                    "reason": decision.reason,
                }
                for metric, decision in prepared.spec.capabilities.items()
            },
        }

    return handle


def make_compute_metrics_handler(
    *,
    analysis_service: AnalysisService,
    run_service: RunService,
) -> ToolHandler:
    from datetime import date as _date

    def handle(ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        assert isinstance(args, ComputeMetricsInput)
        run_service.assert_analysis_owned(ctx.run_id, ctx.session_id, args.analysis_id)

        run = run_service.get_run(ctx.run_id, ctx.session_id)
        datasets = [
            ctx.dataset_store.get(dataset_id, ctx.session_id) for dataset_id in run.dataset_ids
        ]
        requested_metrics = tuple(MetricName(m) for m in run.context_snapshot["requested_metrics"])
        prepared = analysis_service.prepare(
            datasets,
            session_id=ctx.session_id,
            requested_start=_date.fromisoformat(run.context_snapshot["requested_start"]),
            requested_end=_date.fromisoformat(run.context_snapshot["requested_end"]),
            requested_metrics=requested_metrics,
            analysis_id=run.analysis_id,
        )
        result = analysis_service.compute_metrics(prepared)
        run_service.bind_metrics(ctx.run_id, ctx.session_id, result.metrics_id)

        return {
            "metrics_id": result.metrics_id,
            "analysis_id": result.analysis_id,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "metrics": {
                        metric.value: {
                            "value": metric_value.value,
                            "observations": metric_value.observations,
                            "assumptions": list(metric_value.assumptions),
                            "unavailable_reason": metric_value.unavailable_reason,
                        }
                        for metric, metric_value in asset.metrics.items()
                    },
                }
                for asset in result.assets
            ],
        }

    return handle


def make_create_charts_handler(
    *,
    chart_service: ChartService,
    analysis_service: AnalysisService,
    run_service: RunService,
) -> ToolHandler:
    from datetime import date as _date

    def handle(ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        assert isinstance(args, CreateChartsInput)
        run_service.assert_analysis_owned(ctx.run_id, ctx.session_id, args.analysis_id)

        run = run_service.get_run(ctx.run_id, ctx.session_id)
        datasets = [
            ctx.dataset_store.get(dataset_id, ctx.session_id) for dataset_id in run.dataset_ids
        ]
        requested_metrics = tuple(MetricName(m) for m in run.context_snapshot["requested_metrics"])
        prepared = analysis_service.prepare(
            datasets,
            session_id=ctx.session_id,
            requested_start=_date.fromisoformat(run.context_snapshot["requested_start"]),
            requested_end=_date.fromisoformat(run.context_snapshot["requested_end"]),
            requested_metrics=requested_metrics,
            analysis_id=run.analysis_id,
        )

        artifacts = chart_service.create_charts(
            run_id=ctx.run_id,
            session_id=ctx.session_id,
            analysis=prepared,
            kinds=args.kinds,
        )

        return {
            "chart_ids": [a.chart_id for a in artifacts],
            "kinds": [a.kind.value for a in artifacts],
            "png_paths": [
                ctx.chart_store.get_png_path(a.chart_id, ctx.session_id, ctx.run_id)
                for a in artifacts
            ],
        }

    return handle


def make_build_report_handler(
    *,
    report_service: ReportService,
    analysis_service: AnalysisService,
    chart_store: ChartStore,
    report_store: ReportStore,
    run_service: RunService,
) -> ToolHandler:
    from datetime import date as _date

    def handle(ctx: ToolContext, args: BaseModel) -> dict[str, Any]:
        assert isinstance(args, BuildReportInput)
        run_service.assert_analysis_owned(ctx.run_id, ctx.session_id, args.analysis_id)
        run_service.assert_metrics_owned(ctx.run_id, ctx.session_id, args.metrics_id)

        run = run_service.get_run(ctx.run_id, ctx.session_id)
        datasets = [
            ctx.dataset_store.get(dataset_id, ctx.session_id) for dataset_id in run.dataset_ids
        ]
        requested_metrics = tuple(MetricName(m) for m in run.context_snapshot["requested_metrics"])
        prepared = analysis_service.prepare(
            datasets,
            session_id=ctx.session_id,
            requested_start=_date.fromisoformat(run.context_snapshot["requested_start"]),
            requested_end=_date.fromisoformat(run.context_snapshot["requested_end"]),
            requested_metrics=requested_metrics,
            analysis_id=run.analysis_id,
        )
        metric_result = analysis_service.compute_metrics(prepared)

        charts: list[ChartArtifact] = []
        for chart_id in args.chart_ids:
            run_service.assert_chart_owned(ctx.run_id, ctx.session_id, chart_id)
            charts.append(chart_store.get(chart_id, ctx.session_id, ctx.run_id))

        artifact = report_service.build_report(
            run_id=ctx.run_id,
            session_id=ctx.session_id,
            analysis_id=args.analysis_id,
            metrics_id=args.metrics_id,
            metrics=metric_result,
            charts=tuple(charts),
        )

        return {
            "report_id": artifact.report_id,
            "markdown_path": report_store.get_markdown_path(
                artifact.report_id, ctx.session_id, ctx.run_id
            ),
            "run_status": "succeeded",
        }

    return handle


# ---------------------------------------------------------------------------
# ToolRegistry — the execution pipeline.
# ---------------------------------------------------------------------------


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._run_service: RunService | None = None
        self._run_store: RunStore | None = None
        self._dataset_store: DatasetStore | None = None
        self._chart_store: ChartStore | None = None
        self._report_store: ReportStore | None = None

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools.keys())

    def get(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise QuantLabError(
                ErrorCode.UNKNOWN_TOOL,
                "Tool is not registered.",
                details={"tool_name": name},
            )
        return self._tools[name]

    def execute(
        self,
        *,
        run_id: str,
        session_id: str,
        tool_call_id: str | None = None,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResultEnvelope:
        assert self._run_service is not None, "ToolRegistry is not wired."
        assert self._run_store is not None
        assert self._dataset_store is not None
        assert self._chart_store is not None
        assert self._report_store is not None

        tool_call_id = tool_call_id or str(uuid4())
        started_at = _utcnow()
        empty_provenance = Provenance(session_id=session_id, run_id=run_id, dataset_ids=())
        envelope = _make_envelope(
            ok=False,
            run_id=run_id,
            tool_call_id=tool_call_id,
            provenance=empty_provenance,
        )
        status = ToolStatus.FAILED
        error_code: str | None = None
        run = None
        provenance = empty_provenance

        try:
            try:
                definition = self.get(tool_name)
            except QuantLabError as exc:
                error_code = exc.code.value
                envelope = _handle_quantlab_error(
                    exc,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=empty_provenance,
                )
                return envelope

            try:
                run = self._run_store.get(run_id, session_id)
            except QuantLabError as exc:
                error_code = exc.code.value
                envelope = _handle_quantlab_error(
                    exc,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=empty_provenance,
                )
                return envelope

            provenance = _make_provenance(run)

            try:
                validated = definition.input_model.model_validate(arguments)
            except ValidationError as exc:
                error_code = ErrorCode.PROTOCOL_ERROR.value
                envelope = _handle_quantlab_error(
                    QuantLabError(
                        ErrorCode.PROTOCOL_ERROR,
                        "Tool arguments failed schema validation.",
                        details={"errors": exc.errors(include_url=False)},
                    ),
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=provenance,
                )
                return envelope

            try:
                self._run_service.assert_can_accept_tool_call(run_id, session_id)
            except QuantLabError as exc:
                error_code = exc.code.value
                envelope = _handle_quantlab_error(
                    exc,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=provenance,
                )
                return envelope

            ref_error = _check_reference_ownership(definition, validated, run)
            if ref_error is not None:
                error_code = ref_error.code.value
                envelope = _handle_quantlab_error(
                    ref_error,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=provenance,
                )
                return envelope

            ctx = ToolContext(
                run_id=run_id,
                session_id=session_id,
                tool_call_id=tool_call_id,
                started_at=started_at,
                budget_state={},
                dataset_store=self._dataset_store,
                run_store=self._run_store,
                chart_store=self._chart_store,
                report_store=self._report_store,
            )

            try:
                data = definition.handler(ctx, validated)
                self._run_service.record_tool_execution(run_id, session_id)
                run_after = self._run_store.get(run_id, session_id)
                envelope = _make_envelope(
                    ok=True,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=Provenance(
                        session_id=session_id,
                        run_id=run_id,
                        dataset_ids=run_after.dataset_ids,
                        analysis_id=run_after.analysis_id,
                        metrics_id=run_after.metrics_id,
                        chart_ids=run_after.chart_ids,
                    ),
                    data=data,
                )
                status = ToolStatus.SUCCEEDED
            except QuantLabError as exc:
                self._run_service.record_tool_execution(run_id, session_id)
                error_code = exc.code.value
                envelope = _handle_quantlab_error(
                    exc,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=provenance,
                )
            except Exception as exc:  # noqa: BLE001 - top-level guard
                self._run_service.record_tool_execution(run_id, session_id)
                error_code = ErrorCode.TOOL_FAILURE.value
                envelope = _handle_unexpected_error(
                    exc,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    provenance=provenance,
                )
            return envelope
        finally:
            # Always persist the call record so the run's tool_calls.jsonl
            # reflects every invocation, including precheck failures.
            try:
                record = ToolCallRecord(
                    tool_call_id=tool_call_id,
                    run_id=run_id,
                    tool_name=tool_name,
                    arguments_redacted=dict(arguments),
                    status=status,
                    started_at=started_at,
                    completed_at=_utcnow(),
                    result_envelope=envelope,
                    error_code=error_code,
                )
                self._run_store.append_tool_call(run_id, session_id, record)
            except QuantLabError:
                # If even the record write fails (e.g., unknown run), there is
                # nothing to persist; the original envelope is still returned.
                pass


def _check_reference_ownership(
    definition: ToolDefinition,
    validated: BaseModel,
    run: object,
) -> QuantLabError | None:
    dataset_ids = getattr(run, "dataset_ids", ())
    analysis_id = getattr(run, "analysis_id", None)
    metrics_id = getattr(run, "metrics_id", None)
    chart_ids = getattr(run, "chart_ids", ())

    if definition.name == "inspect_dataset":
        ds = getattr(validated, "dataset_id", None)
        if ds and ds not in dataset_ids:
            return QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Dataset is not bound to this run.",
                details={"dataset_id": ds},
            )
    elif definition.name == "prepare_analysis":
        for ds in getattr(validated, "dataset_ids", ()):
            if ds not in dataset_ids:
                return QuantLabError(
                    ErrorCode.UNKNOWN_REFERENCE,
                    "Dataset is not bound to this run.",
                    details={"dataset_id": ds},
                )
    elif definition.name == "compute_metrics":
        target = getattr(validated, "analysis_id", None)
        if target and target != analysis_id:
            return QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Analysis is not bound to this run.",
                details={"analysis_id": target},
            )
    elif definition.name == "create_charts":
        target = getattr(validated, "analysis_id", None)
        if target and target != analysis_id:
            return QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Analysis is not bound to this run.",
                details={"analysis_id": target},
            )
    elif definition.name == "build_report":
        if getattr(validated, "analysis_id", None) != analysis_id:
            return QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Analysis is not bound to this run.",
                details={"analysis_id": getattr(validated, "analysis_id", None)},
            )
        if getattr(validated, "metrics_id", None) != metrics_id:
            return QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Metrics are not bound to this run.",
                details={"metrics_id": getattr(validated, "metrics_id", None)},
            )
        for chart_id in getattr(validated, "chart_ids", ()):
            if chart_id not in chart_ids:
                return QuantLabError(
                    ErrorCode.UNKNOWN_REFERENCE,
                    "Chart is not bound to this run.",
                    details={"chart_id": chart_id},
                )
    return None


def default_registry(
    *,
    dataset_service: DatasetService,
    analysis_service: AnalysisService,
    chart_service: ChartService,
    report_service: ReportService,
    run_service: RunService,
    dataset_store: DatasetStore,
    run_store: RunStore,
    chart_store: ChartStore,
    report_store: ReportStore,
) -> ToolRegistry:
    """Build a registry wired with the application services."""
    registry = ToolRegistry()
    registry._run_service = run_service
    registry._run_store = run_store
    registry._dataset_store = dataset_store
    registry._chart_store = chart_store
    registry._report_store = report_store

    registry.register(
        ToolDefinition(
            name="inspect_dataset",
            description=(
                "Return metadata, coverage, and quality issues for a dataset "
                "already bound to the current run."
            ),
            input_model=InspectDatasetInput,
            output_description="dataset summary and quality issues",
            handler=make_inspect_dataset_handler(),
        )
    )
    registry.register(
        ToolDefinition(
            name="prepare_analysis",
            description=(
                "Slice datasets into the requested date range, align common "
                "dates for two-asset comparisons, and produce an analysis_id "
                "bound to the run."
            ),
            input_model=PrepareAnalysisInput,
            output_description="analysis_id, effective range, alignment policy, capabilities",
            handler=make_prepare_analysis_handler(
                analysis_service=analysis_service,
                run_service=run_service,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="compute_metrics",
            description=(
                "Compute the requested metrics over the prepared analysis. "
                "Unavailable metrics are returned as null with a reason."
            ),
            input_model=ComputeMetricsInput,
            output_description="metrics_id and per-asset metric values",
            handler=make_compute_metrics_handler(
                analysis_service=analysis_service,
                run_service=run_service,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="create_charts",
            description=(
                "Render normalized-price and/or drawdown charts for the "
                "prepared analysis; persist PNG + chart_data.json."
            ),
            input_model=CreateChartsInput,
            output_description="chart_ids and PNG paths",
            handler=make_create_charts_handler(
                chart_service=chart_service,
                analysis_service=analysis_service,
                run_service=run_service,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="build_report",
            description=(
                "Validate evidence references and render the Markdown report "
                "for the run. Marks the run as succeeded on success."
            ),
            input_model=BuildReportInput,
            output_description="report_id and markdown path",
            handler=make_build_report_handler(
                report_service=report_service,
                analysis_service=analysis_service,
                chart_store=chart_store,
                report_store=report_store,
                run_service=run_service,
            ),
        )
    )
    return registry


__all__ = [
    "ToolDefinition",
    "ToolRegistry",
    "default_registry",
    "InspectDatasetInput",
    "PrepareAnalysisInput",
    "ComputeMetricsInput",
    "CreateChartsInput",
    "BuildReportInput",
]
