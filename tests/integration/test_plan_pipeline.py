"""End-to-end integration: Planner → PlanValidator → PlanExecutor."""

from __future__ import annotations

import json
from pathlib import Path

from quantlab_agent.adapters.fake_provider import FakeProvider
from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.plan_executor import PlanExecutor
from quantlab_agent.agent.plan_validator import PlanValidator
from quantlab_agent.agent.planner import LLMPlanner, PlannerContext, RulePlanner
from quantlab_agent.agent.planner_factory import build_planner
from quantlab_agent.agent.tools import default_registry
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.config import ModelConfig
from quantlab_agent.domain.models import (
    DatasetMetadata,
    PriceBasis,
    RunMode,
    RunStatus,
)
from quantlab_agent.ports.model_provider import ModelTurn

SESSION = "00000000-0000-4000-8000-000000000099"


def _stack(tmp_path: Path):
    dataset_store = LocalDatasetStore(tmp_path)
    run_store = LocalRunStore(tmp_path)
    chart_store = LocalChartStore(tmp_path)
    report_store = LocalReportStore(tmp_path)
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
    return registry, run_service, dataset_store, dataset_service


def _seed_demo(
    dataset_service: DatasetService, dataset_store: LocalDatasetStore, asset_id: str
) -> str:
    metadata = DatasetMetadata(
        asset_id=asset_id,
        source_name="test",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="test",
        daily_series_complete=True,
        is_synthetic=True,
    )
    content = (
        b"date,close\n"
        b"2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n2024-01-05,102\n"
        b"2024-01-08,103\n2024-01-09,101\n2024-01-10,100\n2024-01-11,99\n"
        b"2024-01-12,98\n2024-01-15,99\n"
    )
    result = dataset_service.import_csv(content, metadata=metadata, session_id=SESSION)
    assert result.dataset is not None
    dataset_store.save(result.dataset, SESSION)
    return result.dataset.manifest.dataset_id


def test_data_quality_intent_runs_only_inspect(tmp_path: Path) -> None:
    registry, run_service, dataset_store, dataset_service = _stack(tmp_path)
    _seed_demo(dataset_service, dataset_store, "DEMO_A")
    ctx = PlannerContext(
        session_id=SESSION,
        dataset_summaries=tuple(dataset_store.list_in_session(SESSION)),
    )
    plan = RulePlanner().plan("数据质量怎么样", ctx)
    resolved = PlanValidator(resolver=dataset_store).validate(plan, session_id=SESSION)
    assert isinstance(resolved.intent.value, str)  # type narrowing hint
    run = run_service.create_run(
        session_id=SESSION, mode=RunMode.REAL_AGENT, user_request="数据质量怎么样"
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run.run_id, session_id=SESSION, plan=resolved
    )
    tool_names = [r.tool_name for r in run_service.list_tool_calls(run.run_id, SESSION)]
    assert tool_names == ["inspect_dataset"]
    assert final.status is RunStatus.SUCCEEDED
    assert final.context_snapshot["intent"] == "data_quality"


def test_metrics_intent_runs_three_tools(tmp_path: Path) -> None:
    registry, run_service, dataset_store, dataset_service = _stack(tmp_path)
    _seed_demo(dataset_service, dataset_store, "DEMO_A")
    ctx = PlannerContext(
        session_id=SESSION,
        dataset_summaries=tuple(dataset_store.list_in_session(SESSION)),
    )
    plan = RulePlanner().plan("DEMO_A 最大回撤 2024-01-02 2024-01-15", ctx)
    resolved = PlanValidator(resolver=dataset_store).validate(plan, session_id=SESSION)
    run = run_service.create_run(
        session_id=SESSION, mode=RunMode.REAL_AGENT, user_request="DEMO_A 最大回撤"
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run.run_id, session_id=SESSION, plan=resolved
    )
    tool_names = [r.tool_name for r in run_service.list_tool_calls(run.run_id, SESSION)]
    assert tool_names == ["inspect_dataset", "prepare_analysis", "compute_metrics"]
    assert final.status is RunStatus.SUCCEEDED
    assert final.context_snapshot["intent"] == "metrics"
    assert final.metrics_id is not None


def test_out_of_scope_intent_marks_failed(tmp_path: Path) -> None:
    registry, run_service, dataset_store, dataset_service = _stack(tmp_path)
    _seed_demo(dataset_service, dataset_store, "DEMO_A")
    ctx = PlannerContext(
        session_id=SESSION,
        dataset_summaries=tuple(dataset_store.list_in_session(SESSION)),
    )
    plan = RulePlanner().plan("推荐股票", ctx)
    resolved = PlanValidator(resolver=dataset_store).validate(plan, session_id=SESSION)
    run = run_service.create_run(
        session_id=SESSION, mode=RunMode.REAL_AGENT, user_request="推荐股票"
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run.run_id, session_id=SESSION, plan=resolved
    )
    assert final.status is RunStatus.FAILED
    assert final.failure is not None
    assert final.failure["code"] == "OUT_OF_SCOPE"


def test_llm_planner_end_to_end_via_factory(tmp_path: Path) -> None:
    """LLMPlanner + PlanValidator + PlanExecutor round trip with FakeProvider."""
    registry, run_service, dataset_store, dataset_service = _stack(tmp_path)
    _seed_demo(dataset_service, dataset_store, "DEMO_A")

    payload = json.dumps(
        {
            "intent": "metrics",
            "dataset_refs": ["DEMO_A"],
            "date_range": {"start": "2024-01-02", "end": "2024-01-15"},
            "metrics": ["max_drawdown"],
            "charts": [],
            "clarifying_question": None,
            "user_visible_summary": "ok",
        }
    )
    scripted = FakeProvider([ModelTurn(text=payload, finish_reason="stop")])
    planner = LLMPlanner(model_provider=scripted)
    ctx = PlannerContext(
        session_id=SESSION,
        dataset_summaries=tuple(dataset_store.list_in_session(SESSION)),
    )
    plan = planner.plan("anything", ctx)
    resolved = PlanValidator(resolver=dataset_store).validate(plan, session_id=SESSION)

    run = run_service.create_run(
        session_id=SESSION, mode=RunMode.REAL_AGENT, user_request="anything"
    )
    final = PlanExecutor(registry=registry, run_service=run_service).execute(
        run_id=run.run_id, session_id=SESSION, plan=resolved
    )
    tool_names = [r.tool_name for r in run_service.list_tool_calls(run.run_id, SESSION)]
    assert tool_names == ["inspect_dataset", "prepare_analysis", "compute_metrics"]
    assert final.status is RunStatus.SUCCEEDED
    assert final.metrics_id is not None


def test_build_planner_falls_back_to_rule_when_unconfigured() -> None:
    planner = build_planner(None)
    assert isinstance(planner, RulePlanner)


def test_build_planner_uses_llm_when_configured() -> None:
    cfg = ModelConfig(
        base_url="https://example.invalid/v1",
        api_key="sk-test",
        model="gpt-test",
    )
    planner = build_planner(cfg)
    assert isinstance(planner, LLMPlanner)
