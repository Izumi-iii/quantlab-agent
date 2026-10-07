"""Unit tests for PlanExecutor."""

from __future__ import annotations

from pathlib import Path

from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.plan_executor import PlanExecutor
from quantlab_agent.agent.plan_validator import ClarificationRequest, OutOfScopeError
from quantlab_agent.agent.tools import default_registry
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.models import (
    ChartKind,
    DatasetMetadata,
    DateRange,
    Intent,
    MetricName,
    PriceBasis,
    ResolvedPlan,
    RunBudget,
    RunMode,
    RunStatus,
)
from quantlab_agent.domain.policies import DEFAULT_RUN_BUDGET

SESSION = "00000000-0000-4000-8000-000000000099"
RUN_ID = "11111111-1111-4111-8111-111111111111"
DATASET_ID = "00000000-0000-4000-8000-000000000001"


def _build(tmp_path: Path):
    runs_dir = tmp_path
    dataset_store = LocalDatasetStore(runs_dir)
    run_store = LocalRunStore(runs_dir)
    chart_store = LocalChartStore(runs_dir)
    report_store = LocalReportStore(runs_dir)
    dataset_service = DatasetService()
    analysis_service = AnalysisService()
    run_service = RunService(run_store)
    chart_service = ChartService(
        chart_store=chart_store,
        plot_service=PlotService(),
        run_service=run_service,
    )
    report_service = ReportService(report_store=report_store, run_service=run_service)
    registry = default_registry(
        dataset_service=dataset_service,
        analysis_service=analysis_service,
        chart_service=chart_service,
        report_service=report_service,
        run_service=run_service,
        dataset_store=dataset_store,
        run_store=run_store,
        chart_store=chart_store,
        report_store=report_store,
    )
    return registry, run_service, dataset_store


def _seed_dataset(dataset_store: LocalDatasetStore) -> str:
    metadata = DatasetMetadata(
        asset_id="DEMO_A",
        source_name="test",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="test",
        daily_series_complete=True,
        is_synthetic=True,
    )
    content = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
    result = DatasetService().import_csv(content, metadata=metadata, session_id=SESSION)
    assert result.dataset is not None
    dataset_store.save(result.dataset, SESSION)
    return result.dataset.manifest.dataset_id


def _seed_run(run_service: RunService) -> None:
    run_service._runs.create(  # noqa: SLF001
        run_service._runs._Run__dict__ if False else None,  # type: ignore[attr-defined]
    )
    # Use direct creation through the service for clarity.
    pass


def _make_run(run_service: RunService) -> str:
    run = run_service.create_run(
        session_id=SESSION,
        mode=RunMode.REAL_AGENT,
        user_request="test",
        budgets=RunBudget(
            max_model_interactions=DEFAULT_RUN_BUDGET.max_model_interactions,
            max_tool_executions=DEFAULT_RUN_BUDGET.max_tool_executions,
            max_same_validation_retry=DEFAULT_RUN_BUDGET.max_same_validation_retry,
            max_retryable_network_errors=DEFAULT_RUN_BUDGET.max_retryable_network_errors,
            per_request_timeout_seconds=DEFAULT_RUN_BUDGET.per_request_timeout_seconds,
            total_deadline_seconds=DEFAULT_RUN_BUDGET.total_deadline_seconds,
        ),
    )
    return run.run_id


def test_executor_data_quality_runs_only_inspect(tmp_path: Path) -> None:
    registry, run_service, dataset_store = _build(tmp_path)
    ds_id = _seed_dataset(dataset_store)
    run_id = _make_run(run_service)
    plan = ResolvedPlan(
        intent=Intent.DATA_QUALITY,
        resolved_dataset_ids=(ds_id,),
        date_range=None,
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )
    records = run_service.list_tool_calls(run_id, SESSION)
    tool_names = [r.tool_name for r in records]
    assert tool_names == ["inspect_dataset"]
    assert final.status is RunStatus.SUCCEEDED


def test_executor_metrics_runs_inspect_prepare_compute(tmp_path: Path) -> None:
    registry, run_service, dataset_store = _build(tmp_path)
    ds_id = _seed_dataset(dataset_store)
    run_id = _make_run(run_service)

    plan = ResolvedPlan(
        intent=Intent.METRICS,
        resolved_dataset_ids=(ds_id,),
        date_range=DateRange(start="2024-01-02", end="2024-01-15"),
        effective_start=None,
        effective_end=None,
        metrics=(MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN),
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )
    tool_names = [r.tool_name for r in run_service.list_tool_calls(run_id, SESSION)]
    assert tool_names == [
        "inspect_dataset",
        "prepare_analysis",
        "compute_metrics",
    ]
    assert final.metrics_id is not None
    assert final.status is RunStatus.SUCCEEDED


def test_executor_uses_effective_date_range_for_prepare(tmp_path: Path) -> None:
    registry, run_service, dataset_store = _build(tmp_path)
    ds_id = _seed_dataset(dataset_store)
    run_id = _make_run(run_service)

    plan = ResolvedPlan(
        intent=Intent.METRICS,
        resolved_dataset_ids=(ds_id,),
        date_range=DateRange(start="2023-01-01", end="2025-01-01"),
        effective_start=DateRange(start="2024-01-02", end="2024-01-04").start,
        effective_end=DateRange(start="2024-01-02", end="2024-01-04").end,
        metrics=(MetricName.PERIOD_RETURN,),
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )

    prepare = next(
        r for r in run_service.list_tool_calls(run_id, SESSION) if r.tool_name == "prepare_analysis"
    )
    assert final.status is RunStatus.SUCCEEDED
    assert prepare.arguments_redacted["requested_start"] == "2024-01-02"
    assert prepare.arguments_redacted["requested_end"] == "2024-01-04"


def test_executor_report_marks_run_succeeded(tmp_path: Path) -> None:
    registry, run_service, dataset_store = _build(tmp_path)
    ds_id = _seed_dataset(dataset_store)
    run_id = _make_run(run_service)

    plan = ResolvedPlan(
        intent=Intent.REPORT,
        resolved_dataset_ids=(ds_id,),
        date_range=DateRange(start="2024-01-02", end="2024-01-15"),
        effective_start=None,
        effective_end=None,
        metrics=(MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN),
        charts=(ChartKind.NORMALIZED_PRICES, ChartKind.DRAWDOWN),
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )
    tool_names = [r.tool_name for r in run_service.list_tool_calls(run_id, SESSION)]
    assert tool_names == [
        "inspect_dataset",
        "prepare_analysis",
        "compute_metrics",
        "create_charts",
        "build_report",
    ]
    assert final.status is RunStatus.SUCCEEDED
    assert final.report_id is not None


def test_executor_chart_runs_inspect_prepare_create_charts(tmp_path: Path) -> None:
    registry, run_service, dataset_store = _build(tmp_path)
    ds_id = _seed_dataset(dataset_store)
    run_id = _make_run(run_service)

    plan = ResolvedPlan(
        intent=Intent.CHART,
        resolved_dataset_ids=(ds_id,),
        date_range=DateRange(start="2024-01-02", end="2024-01-15"),
        effective_start=None,
        effective_end=None,
        charts=(ChartKind.NORMALIZED_PRICES,),
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )
    tool_names = [r.tool_name for r in run_service.list_tool_calls(run_id, SESSION)]
    assert tool_names == [
        "inspect_dataset",
        "prepare_analysis",
        "create_charts",
    ]
    assert final.status is RunStatus.SUCCEEDED
    assert final.chart_ids


def test_executor_clarify_marks_needs_clarification(tmp_path: Path) -> None:
    registry, run_service, _dataset_store = _build(tmp_path)
    run_id = _make_run(run_service)
    plan = ClarificationRequest("which?", summary="please")
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )
    assert final.status is RunStatus.NEEDS_CLARIFICATION
    assert final.failure is not None
    assert final.failure["code"] == "NEEDS_CLARIFICATION"
    assert final.failure["details"]["clarifying_question"] == "which?"


def test_executor_out_of_scope_marks_failed(tmp_path: Path) -> None:
    registry, run_service, _dataset_store = _build(tmp_path)
    run_id = _make_run(run_service)
    plan = OutOfScopeError("not supported")
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run_id, session_id=SESSION, plan=plan
    )
    assert final.status is RunStatus.FAILED
    assert final.failure is not None
    assert final.failure["code"] == "OUT_OF_SCOPE"
    assert final.failure["details"]["intent"] == "out_of_scope"
