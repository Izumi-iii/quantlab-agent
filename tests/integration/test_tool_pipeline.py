"""Pipeline tests for the ToolRegistry execution surface.

These exercise the registry's precheck pipeline (state, budget, references)
end-to-end, without going through the demo scenarios.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.tools import default_registry
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode
from quantlab_agent.domain.models import (
    DatasetMetadata,
    PriceBasis,
    Run,
    RunBudget,
    RunMode,
    RunStatus,
)

SESSION = "00000000-0000-4000-8000-000000000001"


def _build(tmp_path: Path) -> dict[str, object]:
    runs_dir = tmp_path
    dataset_store = LocalDatasetStore(runs_dir)
    run_store = LocalRunStore(runs_dir)
    chart_store = LocalChartStore(runs_dir)
    report_store = LocalReportStore(runs_dir)
    dataset_service = DatasetService()
    analysis_service = AnalysisService()
    run_service = RunService(run_store)
    chart_service = ChartService(
        chart_store=chart_store, plot_service=PlotService(), run_service=run_service
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
    return {
        "registry": registry,
        "run_service": run_service,
        "run_store": run_store,
        "dataset_store": dataset_store,
    }


def _import_demo_a(dataset_store: LocalDatasetStore) -> str:
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
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n2024-01-05,103\n"
    res = DatasetService().import_csv(csv, metadata=metadata, session_id=SESSION)
    assert res.dataset is not None
    dataset_store.save(res.dataset, SESSION)
    return res.dataset.manifest.dataset_id


def _seed_run(run_store: LocalRunStore) -> Run:
    run = Run(
        run_id="11111111-1111-4111-8111-111111111111",
        session_id=SESSION,
        mode=RunMode.DEMO,
        status=RunStatus.RUNNING,
        user_request="x",
        dataset_ids=(),
        budgets=RunBudget(
            max_model_interactions=8,
            max_tool_executions=2,  # tiny budget for the budget-exceeded test
            max_same_validation_retry=1,
            max_retryable_network_errors=1,
            per_request_timeout_seconds=30,
            total_deadline_seconds=120,
        ),
        created_at=datetime.now(UTC),
    )
    run_store.create(run)
    return run


def test_stale_run_blocks_subsequent_tool_call(tmp_path: Path) -> None:
    stack = _build(tmp_path)
    registry = stack["registry"]
    run_service = stack["run_service"]
    run_store = stack["run_store"]

    run = _seed_run(run_store)
    run_service.mark_succeeded(run.run_id, SESSION)

    envelope = registry.execute(
        run_id=run.run_id,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.STALE_RUN.value


def test_budget_exhausted_blocks_subsequent_tool_call(tmp_path: Path) -> None:
    stack = _build(tmp_path)
    registry = stack["registry"]
    run_service = stack["run_service"]
    run_store = stack["run_store"]

    run = _seed_run(run_store)
    # Drain budget before any call.
    run_service.record_tool_execution(run.run_id, SESSION)
    run_service.record_tool_execution(run.run_id, SESSION)

    envelope = registry.execute(
        run_id=run.run_id,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.BUDGET_EXCEEDED.value


def test_dataset_not_in_run_fails_reference_check(tmp_path: Path) -> None:
    stack = _build(tmp_path)
    registry = stack["registry"]
    run_store = stack["run_store"]

    run = _seed_run(run_store)
    envelope = registry.execute(
        run_id=run.run_id,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.UNKNOWN_REFERENCE.value


def test_tool_call_record_persisted_even_on_failure(tmp_path: Path) -> None:
    stack = _build(tmp_path)
    registry = stack["registry"]
    run_store = stack["run_store"]

    run = _seed_run(run_store)
    registry.execute(
        run_id=run.run_id,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )

    records = run_store.list_tool_calls(run.run_id, SESSION)
    assert len(records) == 1
    assert records[0].tool_name == "inspect_dataset"
    assert records[0].status.value == "failed"
