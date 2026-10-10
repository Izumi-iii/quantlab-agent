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
from quantlab_agent.domain.models import (
    AnalysisExtra,
    AnalysisPlan,
    ChartKind,
    DateRange,
    Intent,
    MetricName,
)
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


@pytest.mark.parametrize(
    "text", ["生成一份报告", "帮我出一份分析报告", "整理完整报告", "导出分析报告"]
)
def test_report_phrases_with_multiple_datasets(text: str) -> None:
    plan = RulePlanner().plan(text, _ctx("DEMO_A", "DEMO_B"))
    assert plan.intent is Intent.REPORT


def test_report_inherits_analysis_but_explicit_parameters_override() -> None:
    ctx = _ctx("DEMO_A", "DEMO_B")
    previous = AnalysisPlan(
        intent=Intent.METRICS,
        dataset_refs=("DEMO_B",),
        date_range=DateRange(start="2024-01-03", end="2024-01-12"),
        metrics=(MetricName.MAX_DRAWDOWN,),
        charts=(ChartKind.ROLLING_VOLATILITY,),
        rolling_windows=(20,),
    )
    ctx = PlannerContext(
        session_id=ctx.session_id,
        dataset_summaries=ctx.dataset_summaries,
        previous_analysis=previous,
    )
    plan = RulePlanner().plan("生成一份报告", ctx)
    assert plan.dataset_refs == previous.dataset_refs
    assert plan.date_range == previous.date_range
    assert plan.metrics == previous.metrics
    assert plan.charts == previous.charts
    assert plan.rolling_windows == (20,)
    explicit = RulePlanner().plan("生成 DEMO_A 的区间收益报告 2024-01-02 2024-01-15", ctx)
    assert explicit.dataset_refs == ("DEMO_A",)
    assert explicit.date_range.start.isoformat() == "2024-01-02"
    assert explicit.metrics == (MetricName.PERIOD_RETURN,)


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


def test_rule_planner_risk_questions_are_in_scope() -> None:
    plan = RulePlanner().plan("风险怎么样？", _ctx("DEMO_A"))
    assert plan.intent is Intent.METRICS
    assert AnalysisExtra.RISK in plan.extras

    plan = RulePlanner().plan("计算夏普、VaR 和 CVaR", _ctx("DEMO_A"))
    assert plan.intent is Intent.METRICS
    assert AnalysisExtra.RISK in plan.extras


def test_rule_planner_compare_trend_describes_for_all_datasets() -> None:
    plan = RulePlanner().plan("比较两个资产的走势", _ctx("DEMO_A", "DEMO_B"))
    # "走势" alone is describe (M7): METRICS intent with describe extra.
    assert plan.intent is Intent.METRICS
    assert plan.dataset_refs == ()
    assert "describe_price_series" in [e.value for e in plan.extras]


def test_rule_planner_chart_keyword_overrides_describe() -> None:
    plan = RulePlanner().plan("画一下 DEMO_A 和 DEMO_B 的走势图", _ctx("DEMO_A", "DEMO_B"))
    assert plan.intent is Intent.CHART
    assert plan.charts == (ChartKind.NORMALIZED_PRICES,)


def test_rule_planner_trend_chart_uses_chart_intent() -> None:
    plan = RulePlanner().plan("生成趋势图表", _ctx("DEMO_A"))
    assert plan.intent is Intent.CHART
    assert plan.dataset_refs == ("DEMO_A",)
    assert plan.charts == (ChartKind.NORMALIZED_PRICES,)


@pytest.mark.parametrize("text", ["趋势图", "画一下走势", "接着画图"])
def test_rule_planner_short_chart_requests(text: str) -> None:
    plan = RulePlanner().plan(text, _ctx("DEMO_A"))
    assert plan.intent is Intent.CHART
    assert plan.dataset_refs == ("DEMO_A",)


def test_rule_planner_chart_and_anomalies() -> None:
    plan = RulePlanner().plan("生成趋势图，并检查有没有异常常值", _ctx("DEMO_A"))
    assert plan.intent is Intent.CHART
    assert plan.extras == (AnalysisExtra.ANOMALIES,)


def test_rule_planner_unknown_request_clarifies() -> None:
    plan = RulePlanner().plan("再处理一下", _ctx("DEMO_A"))
    assert plan.intent is Intent.CLARIFY


def test_rule_planner_rolling_chart_preserves_kind_and_window() -> None:
    plan = RulePlanner().plan("生成 60 日滚动波动率图", _ctx("DEMO_A"))
    assert plan.intent is Intent.CHART
    assert AnalysisExtra.ROLLING in plan.extras
    assert plan.charts == (ChartKind.ROLLING_VOLATILITY,)
    assert plan.rolling_windows == (60,)


def test_metrics_and_description_are_not_mistaken_for_chart() -> None:
    plan = RulePlanner().plan("分析区间收益和最大回撤，再说明走势有什么特点", _ctx("DEMO_A"))
    assert plan.intent is Intent.METRICS
    assert plan.metrics == (MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN)
    assert plan.charts == ()
    assert AnalysisExtra.DESCRIBE_PRICE_SERIES in plan.extras


def test_mixed_chart_kinds_are_preserved() -> None:
    plan = RulePlanner().plan("生成归一化价格图、回撤图和60日滚动波动率图", _ctx("DEMO_A"))
    assert set(plan.charts) == {
        ChartKind.NORMALIZED_PRICES,
        ChartKind.DRAWDOWN,
        ChartKind.ROLLING_VOLATILITY,
    }
    assert plan.rolling_windows == (60,)


def test_chart_interpretation_uses_prior_analysis_context() -> None:
    from dataclasses import replace

    from quantlab_agent.domain.models import AnalysisPlan, DateRange

    context = replace(
        _ctx("DEMO_A", "DEMO_B"),
        previous_analysis=AnalysisPlan(
            intent=Intent.CHART,
            dataset_refs=("DEMO_B",),
            date_range=DateRange(start="2024-01-03", end="2024-01-12"),
            charts=(ChartKind.NORMALIZED_PRICES, ChartKind.DRAWDOWN, ChartKind.ROLLING_VOLATILITY),
            rolling_windows=(60,),
        ),
        previous_chart_count=3,
    )
    plan = RulePlanner().plan("分析这三个图", context)
    assert plan.intent is Intent.METRICS
    assert plan.dataset_refs == ("DEMO_B",)
    assert plan.date_range == context.previous_analysis.date_range
    assert plan.rolling_windows == (60,)
    assert set(plan.extras) == {AnalysisExtra.DESCRIBE_PRICE_SERIES, AnalysisExtra.ROLLING}


def test_chart_interpretation_without_context_asks_specific_question() -> None:
    plan = RulePlanner().plan("分析这三个图", _ctx("DEMO_A"))
    assert plan.intent is Intent.CLARIFY
    assert "选择" in plan.clarifying_question


def test_llm_planner_parses_valid_json() -> None:
    payload = {
        "intent": "metrics",
        "dataset_refs": ["DEMO_A"],
        "date_range": {"start": "2024-01-02", "end": "2024-01-15"},
        "metrics": ["max_drawdown"],
        "charts": [],
        "extras": ["risk"],
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
    assert plan.extras == (AnalysisExtra.RISK,)


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
