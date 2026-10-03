"""Tests for AgentController with the in-memory FakeProvider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from quantlab_agent.adapters.fake_provider import FakeProvider
from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.controller import AgentController
from quantlab_agent.agent.tools import default_registry
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.models import (
    Run,
    RunBudget,
    RunCounters,
    RunMode,
)
from quantlab_agent.ports.model_provider import ModelTurn, ToolCall

SESSION = "00000000-0000-4000-8000-000000000099"


def _build_stack(tmp_path: Path):
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
    return registry, run_service


def _seed_run(run_service: RunService, run_id: str = "11111111-1111-4111-8111-111111111111") -> Run:
    """Create a pre-seeded Run directly via the store."""
    run_service._runs.create(  # noqa: SLF001 - test fixture writes through store
        Run(
            run_id=run_id,
            session_id=SESSION,
            mode=RunMode.REAL_AGENT,
            status=RunStatus.RUNNING,
            user_request="test",
            dataset_ids=(),
            budgets=RunBudget(
                max_model_interactions=4,
                max_tool_executions=8,
                max_same_validation_retry=1,
                max_retryable_network_errors=1,
                per_request_timeout_seconds=10,
                total_deadline_seconds=60,
            ),
            counters=RunCounters(),
            created_at=datetime.now(UTC),
        )
    )
    return run_service.get_run(run_id, SESSION)


# Late import to avoid double-line at top.
from quantlab_agent.domain.models import RunStatus  # noqa: E402


def test_controller_runs_build_report_via_model(tmp_path: Path) -> None:
    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)
    scripted = FakeProvider(
        [
            ModelTurn(
                tool_call=ToolCall(
                    id="call_1",
                    name="build_report",
                    arguments=json.dumps({"analysis_id": "x", "metrics_id": "y", "chart_ids": []}),
                ),
                finish_reason="tool_calls",
            ),
            ModelTurn(text="Report generated.", finish_reason="stop"),
        ],
        echo_calls=True,
    )
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="do the thing",
    )
    # The build_report tool was called; it failed because no analysis is
    # bound, but the controller recovered and the model produced a final
    # text. The run should be marked succeeded.
    assert final.status.value == "succeeded"
    assert len(scripted.calls) == 2


def test_controller_marks_budget_exceeded(tmp_path: Path) -> None:
    registry, run_service = _build_stack(tmp_path)
    # Tight budget: 2 model interactions; model never returns a final
    # text answer, only tool calls, so the loop must exhaust the budget.
    run = _seed_run(run_service)
    run_service._runs._write_manifest(  # noqa: SLF001 - test fixture
        run_service._runs._run_dir(run.run_id, SESSION),  # noqa: SLF001
        run.model_copy(
            update={
                "budgets": RunBudget(
                    max_model_interactions=2,
                    max_tool_executions=2,
                    max_same_validation_retry=1,
                    max_retryable_network_errors=1,
                    per_request_timeout_seconds=10,
                    total_deadline_seconds=60,
                )
            }
        ),
    )
    scripted = FakeProvider(
        [
            ModelTurn(
                tool_call=ToolCall(
                    id="t1",
                    name="inspect_dataset",
                    arguments=json.dumps({"dataset_id": "0" * 36}),
                ),
                finish_reason="tool_calls",
            ),
            ModelTurn(
                tool_call=ToolCall(
                    id="t2",
                    name="inspect_dataset",
                    arguments=json.dumps({"dataset_id": "0" * 36}),
                ),
                finish_reason="tool_calls",
            ),
            ModelTurn(text="never reached", finish_reason="stop"),
        ]
    )
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="x",
    )
    assert final.status.value == "failed"
    assert final.failure is not None
    assert final.failure["code"] == "BUDGET_EXCEEDED"


def test_controller_marks_failed_on_model_error(tmp_path: Path) -> None:
    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)
    scripted = FakeProvider([ModelTurn(error="rate limited", finish_reason="stop")])
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="x",
    )
    assert final.status.value == "failed"
    assert final.failure is not None
    assert final.failure["code"] == "MODEL_ERROR"
    assert "rate limited" in final.failure["message"]
