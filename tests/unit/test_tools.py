"""Unit tests for the ToolRegistry execution pipeline."""

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
from quantlab_agent.agent.tools import (
    InspectDatasetInput,
    ToolDefinition,
    ToolRegistry,
    default_registry,
)
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode
from quantlab_agent.domain.models import (
    ChartKind,
    DatasetMetadata,
    MetricName,
    PriceBasis,
    Run,
    RunBudget,
    RunMode,
    RunStatus,
)

SESSION = "00000000-0000-4000-8000-000000000001"
RUN_ID = "11111111-1111-4111-8111-111111111111"


def _budget() -> RunBudget:
    return RunBudget(
        max_model_interactions=8,
        max_tool_executions=12,
        max_same_validation_retry=1,
        max_retryable_network_errors=1,
        per_request_timeout_seconds=30,
        total_deadline_seconds=120,
    )


def _build_stack(tmp_path: Path) -> dict[str, object]:
    """Compose all stores + services and a registry wired to them."""
    dataset_store = LocalDatasetStore(tmp_path)
    run_store = LocalRunStore(tmp_path)
    chart_store = LocalChartStore(tmp_path)
    report_store = LocalReportStore(tmp_path)
    dataset_service = DatasetService()
    analysis_service = AnalysisService()
    run_service = RunService(run_store)
    plot_service = PlotService()
    chart_service = ChartService(
        chart_store=chart_store, plot_service=plot_service, run_service=run_service
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
        "chart_store": chart_store,
        "report_store": report_store,
        "run_id": RUN_ID,
    }


def _import_two_datasets(tmp_path: Path, stack: dict[str, object]) -> tuple[str, str]:
    csv_a = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n2024-01-05,103\n"
    csv_b = b"date,close\n2024-01-02,50\n2024-01-03,51\n2024-01-04,52\n2024-01-05,53\n"
    meta_a = DatasetMetadata(
        asset_id="DEMO_A",
        source_name="test",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="test",
        daily_series_complete=True,
        is_synthetic=True,
    )
    meta_b = DatasetMetadata(
        asset_id="DEMO_B",
        source_name="test",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="test",
        daily_series_complete=True,
        is_synthetic=True,
    )
    res_a = DatasetService().import_csv(csv_a, metadata=meta_a, session_id=SESSION)
    res_b = DatasetService().import_csv(csv_b, metadata=meta_b, session_id=SESSION)
    assert res_a.dataset is not None and res_b.dataset is not None
    dataset_store = stack["dataset_store"]
    assert isinstance(dataset_store, LocalDatasetStore)
    dataset_store.save(res_a.dataset, SESSION)
    dataset_store.save(res_b.dataset, SESSION)
    return res_a.dataset.manifest.dataset_id, res_b.dataset.manifest.dataset_id


def _seed_run(stack: dict[str, object]) -> Run:
    run_store = stack["run_store"]
    assert isinstance(run_store, LocalRunStore)
    run = Run(
        run_id=RUN_ID,
        session_id=SESSION,
        mode=RunMode.DEMO,
        status=RunStatus.RUNNING,
        user_request="compare A and B in 2024-01",
        dataset_ids=(),
        budgets=_budget(),
        context_snapshot={},
        created_at=datetime.now(UTC),
    )
    run_store.create(run)
    return run


def _seed_run_with_datasets(tmp_path: Path, stack: dict[str, object]) -> tuple[str, str]:
    run_service = stack["run_service"]
    assert isinstance(run_service, RunService)
    ds_a, ds_b = _import_two_datasets(tmp_path, stack)
    _seed_run(stack)
    run_service.add_dataset(RUN_ID, SESSION, ds_a)
    run_service.add_dataset(RUN_ID, SESSION, ds_b)
    return ds_a, ds_b


def test_unknown_tool_returns_protocol_error(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    _seed_run(stack)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="does_not_exist",
        arguments={},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.UNKNOWN_TOOL.value


def test_invalid_arguments_returns_protocol_error(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    _seed_run(stack)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "not-a-uuid"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.PROTOCOL_ERROR.value


def test_cross_session_dataset_returns_unknown_reference(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    _seed_run(stack)
    other_session = "00000000-0000-4000-8000-0000000000ff"

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=other_session,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.UNKNOWN_REFERENCE.value


def test_budget_exceeded_returns_budget_error(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    run_service = stack["run_service"]
    assert isinstance(run_service, RunService)
    _seed_run(stack)
    # Drain the budget.
    for _ in range(_budget().max_tool_executions):
        run_service.record_tool_execution(RUN_ID, SESSION)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.BUDGET_EXCEEDED.value


def test_wrong_run_state_returns_stale_run(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    run_service = stack["run_service"]
    assert isinstance(run_service, RunService)
    _seed_run(stack)
    run_service.mark_succeeded(RUN_ID, SESSION)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.STALE_RUN.value


def test_inspect_dataset_returns_summary(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    ds_a, ds_b = _seed_run_with_datasets(tmp_path, stack)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": ds_a},
    )
    assert envelope.ok
    assert envelope.data is not None
    assert envelope.data["asset_id"] == "DEMO_A"
    assert envelope.provenance.dataset_ids == (ds_a, ds_b)


def test_list_datasets_returns_session_dataset_ids(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    ds_a, ds_b = _import_two_datasets(tmp_path, stack)
    _seed_run(stack)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="list_datasets",
        arguments={},
    )

    assert envelope.ok, envelope.error
    assert envelope.data is not None
    by_asset = {item["asset_id"]: item["dataset_id"] for item in envelope.data["datasets"]}
    assert by_asset == {"DEMO_A": ds_a, "DEMO_B": ds_b}


def test_real_mode_prepare_binds_session_datasets_to_run(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    ds_a, ds_b = _import_two_datasets(tmp_path, stack)
    _seed_run(stack)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="prepare_analysis",
        arguments={
            "dataset_ids": [ds_a, ds_b],
            "requested_start": "2024-01-02",
            "requested_end": "2024-01-05",
            "requested_metrics": [
                MetricName.PERIOD_RETURN.value,
                MetricName.MAX_DRAWDOWN.value,
            ],
        },
    )

    assert envelope.ok, envelope.error
    run = stack["run_store"].get(RUN_ID, SESSION)  # type: ignore[union-attr]
    assert run.dataset_ids == (ds_a, ds_b)


def test_full_pipeline_succeeds(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    ds_a, ds_b = _seed_run_with_datasets(tmp_path, stack)

    # inspect
    env = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": ds_a},
    )
    assert env.ok

    # prepare
    env = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="prepare_analysis",
        arguments={
            "dataset_ids": [ds_a, ds_b],
            "requested_start": "2024-01-02",
            "requested_end": "2024-01-05",
            "requested_metrics": [
                MetricName.PERIOD_RETURN.value,
                MetricName.MAX_DRAWDOWN.value,
            ],
        },
    )
    assert env.ok, env.error
    analysis_id = env.data["analysis_id"]

    # compute
    env = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="compute_metrics",
        arguments={"analysis_id": analysis_id},
    )
    assert env.ok, env.error
    metrics_id = env.data["metrics_id"]

    # charts
    env = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="create_charts",
        arguments={
            "analysis_id": analysis_id,
            "kinds": [ChartKind.NORMALIZED_PRICES.value, ChartKind.DRAWDOWN.value],
        },
    )
    assert env.ok, env.error
    chart_ids = env.data["chart_ids"]

    # report
    env = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="build_report",
        arguments={
            "analysis_id": analysis_id,
            "metrics_id": metrics_id,
            "chart_ids": chart_ids,
        },
    )
    assert env.ok, env.error

    # Run should now be succeeded.
    final = stack["run_store"].get(RUN_ID, SESSION)  # type: ignore[union-attr]
    assert final.status is RunStatus.SUCCEEDED
    assert final.report_id is not None


def test_envelope_includes_provenance_after_each_call(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    ds_a, _ = _seed_run_with_datasets(tmp_path, stack)

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="inspect_dataset",
        arguments={"dataset_id": ds_a},
    )
    assert envelope.provenance.session_id == SESSION
    assert envelope.provenance.run_id == RUN_ID


def test_tool_calls_persisted_to_jsonl(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    _seed_run(stack)

    for _ in range(3):
        registry.execute(
            run_id=RUN_ID,
            session_id=SESSION,
            tool_name="inspect_dataset",
            arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
        )
    jsonl = tmp_path / SESSION / "runs" / RUN_ID / "tool_calls.jsonl"
    assert jsonl.exists()
    lines = jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_handler_unexpected_exception_returns_tool_failure(tmp_path: Path) -> None:
    stack = _build_stack(tmp_path)
    registry = stack["registry"]
    assert isinstance(registry, ToolRegistry)
    _seed_run(stack)

    def boom(ctx, args):  # noqa: ANN001
        raise RuntimeError("kaboom")

    registry.register(
        ToolDefinition(
            name="explode",
            description="test",
            input_model=InspectDatasetInput,
            output_description="never",
            handler=boom,
        )
    )

    envelope = registry.execute(
        run_id=RUN_ID,
        session_id=SESSION,
        tool_name="explode",
        arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
    )
    assert not envelope.ok
    assert envelope.error["code"] == ErrorCode.TOOL_FAILURE.value
