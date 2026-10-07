"""Unit tests for the Planner layer (RulePlanner + LLMPlanner)."""

from __future__ import annotations

import json

import pytest

from quantlab_agent.adapters.fake_provider import FakeProvider
from quantlab_agent.agent.planner import (
    LLMPlanner,
    PlannerContext,
    PlannerError,
    RulePlanner,
)
from quantlab_agent.domain.models import ChartKind, Intent, MetricName
from quantlab_agent.ports.model_provider import ModelTurn


def _ctx(*asset_ids: str) -> PlannerContext:
    summaries = tuple(
        {
            "dataset_id": f"{i:036x}",
            "asset_id": a,
            "date_min": "2024-01-02",
            "date_max": "2024-01-15",
            "row_count": 10,
        }
        for i, a in enumerate(asset_ids)
    )
    return PlannerContext(
        session_id="00000000-0000-4000-8000-000000000099", dataset_summaries=summaries
    )


def test_rule_planner_out_of_scope_short_circuits() -> None:
    plan = RulePlanner().plan("推荐股票", _ctx("DEMO_A", "DEMO_B"))
    assert plan.intent is Intent.OUT_OF_SCOPE


def test_rule_planner_data_quality_with_two_datasets_runs_on_all() -> None:
    plan = RulePlanner().plan("数据质量怎么样", _ctx("DEMO_A", "DEMO_B"))
    assert plan.intent is Intent.DATA_QUALITY
    # Empty dataset_refs means "use the whole session".
    assert plan.dataset_refs == ()


def test_rule_planner_metrics_with_specific_asset_and_dates() -> None:
    plan = RulePlanner().plan(
        "比较 DEMO_A 最大回撤 2024-01-02 2024-01-15",
        _ctx("DEMO_A", "DEMO_B"),
    )
    assert plan.intent is Intent.METRICS
    assert plan.dataset_refs == ("DEMO_A",)
    assert plan.metrics == (MetricName.MAX_DRAWDOWN,)
    assert plan.date_range is not None
    assert plan.date_range.start.isoformat() == "2024-01-02"
    assert plan.date_range.end.isoformat() == "2024-01-15"


def test_rule_planner_report_default_metrics_and_charts() -> None:
    plan = RulePlanner().plan(
        "生成报告 DEMO_A 和 DEMO_B 2024-01-02 2024-01-15",
        _ctx("DEMO_A", "DEMO_B"),
    )
    assert plan.intent is Intent.REPORT
    assert MetricName.PERIOD_RETURN in plan.metrics
    assert MetricName.MAX_DRAWDOWN in plan.metrics
    assert ChartKind.NORMALIZED_PRICES in plan.charts
    assert ChartKind.DRAWDOWN in plan.charts


def test_rule_planner_clarifies_when_two_datasets_no_pick_no_metrics() -> None:
    plan = RulePlanner().plan("分析一下", _ctx("DEMO_A", "DEMO_B"))
    assert plan.intent is Intent.CLARIFY
    assert plan.clarifying_question is not None


def test_rule_planner_picks_default_metrics_when_keyword_present() -> None:
    plan = RulePlanner().plan("看一下 DEMO_A 的收益", _ctx("DEMO_A"))
    assert plan.intent is Intent.METRICS
    assert MetricName.PERIOD_RETURN in plan.metrics


def test_rule_planner_compare_trend_uses_chart_for_all_datasets() -> None:
    plan = RulePlanner().plan("比较两个资产的走势", _ctx("DEMO_A", "DEMO_B"))
    assert plan.intent is Intent.CHART
    assert plan.dataset_refs == ()
    assert plan.charts == (ChartKind.NORMALIZED_PRICES,)


def test_rule_planner_trend_chart_uses_chart_intent() -> None:
    plan = RulePlanner().plan("生成趋势图表", _ctx("DEMO_A"))
    assert plan.intent is Intent.CHART
    assert plan.dataset_refs == ("DEMO_A",)
    assert plan.charts == (ChartKind.NORMALIZED_PRICES,)


def test_llm_planner_parses_valid_json() -> None:
    payload = {
        "intent": "metrics",
        "dataset_refs": ["DEMO_A"],
        "date_range": {"start": "2024-01-02", "end": "2024-01-15"},
        "metrics": ["max_drawdown"],
        "charts": [],
        "clarifying_question": None,
        "user_visible_summary": "ok",
    }
    scripted = FakeProvider(
        [ModelTurn(text=json.dumps(payload), finish_reason="stop")],
        echo_calls=True,
    )
    planner = LLMPlanner(model_provider=scripted)
    plan = planner.plan("anything", _ctx("DEMO_A"))
    assert plan.intent is Intent.METRICS
    assert plan.metrics == (MetricName.MAX_DRAWDOWN,)


def test_llm_planner_strips_code_fence() -> None:
    payload = json.dumps(
        {
            "intent": "data_quality",
            "dataset_refs": [],
            "date_range": None,
            "metrics": [],
            "charts": [],
            "clarifying_question": None,
            "user_visible_summary": "checking",
        }
    )
    scripted = FakeProvider([ModelTurn(text=f"```json\n{payload}\n```", finish_reason="stop")])
    plan = LLMPlanner(model_provider=scripted).plan("anything", _ctx("DEMO_A"))
    assert plan.intent is Intent.DATA_QUALITY


def test_llm_planner_raises_on_invalid_json() -> None:
    scripted = FakeProvider([ModelTurn(text="not json", finish_reason="stop")])
    with pytest.raises(PlannerError):
        LLMPlanner(model_provider=scripted).plan("anything", _ctx("DEMO_A"))


def test_llm_planner_raises_on_model_error() -> None:
    scripted = FakeProvider([ModelTurn(error="rate limited", finish_reason="stop")])
    with pytest.raises(PlannerError):
        LLMPlanner(model_provider=scripted).plan("anything", _ctx("DEMO_A"))


def test_rule_planner_empty_request_raises() -> None:
    with pytest.raises(PlannerError):
        RulePlanner().plan("   ", _ctx("DEMO_A"))
