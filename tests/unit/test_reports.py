"""Unit tests for ReportService."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantlab_agent.adapters.local_stores import LocalReportStore, LocalRunStore
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    AssetMetricResult,
    ChartArtifact,
    ChartKind,
    MetricName,
    MetricResult,
    MetricValue,
    Run,
    RunBudget,
    RunMode,
    RunStatus,
)

SESSION = "00000000-0000-4000-8000-000000000001"
RUN_ID = "11111111-1111-4111-8111-111111111111"
ANALYSIS_ID = "33333333-3333-4333-8333-333333333333"
METRICS_ID = "55555555-5555-4555-8555-555555555555"
CHART_ID = "22222222-2222-4222-8222-222222222222"


def _budget() -> RunBudget:
    return RunBudget(
        max_model_interactions=8,
        max_tool_executions=12,
        max_same_validation_retry=1,
        max_retryable_network_errors=1,
        per_request_timeout_seconds=30,
        total_deadline_seconds=120,
    )


def _seeded_run(tmp_path: Path) -> RunService:
    store = LocalRunStore(tmp_path)
    store.create(
        Run(
            run_id=RUN_ID,
            session_id=SESSION,
            mode=RunMode.DEMO,
            status=RunStatus.RUNNING,
            user_request="compare A vs B",
            dataset_ids=(),
            budgets=_budget(),
            context_snapshot={
                "requested_start": "2024-01-02",
                "requested_end": "2024-01-15",
                "effective_start": "2024-01-02",
                "effective_end": "2024-01-15",
                "alignment_policy": "common_observation_dates",
                "requested_metrics": ["period_return", "max_drawdown"],
            },
            created_at=datetime.now(UTC),
        )
    )
    return RunService(store)


def _metrics() -> MetricResult:
    return MetricResult(
        metrics_id=METRICS_ID,
        analysis_id=ANALYSIS_ID,
        assets=(
            AssetMetricResult(
                asset_id="DEMO_A",
                metrics={
                    MetricName.PERIOD_RETURN: MetricValue(
                        value=0.089, observations=4, assumptions=("base test",)
                    ),
                    MetricName.MAX_DRAWDOWN: MetricValue(
                        value=-0.10, observations=4, assumptions=("base test",)
                    ),
                    MetricName.ANNUALIZED_VOLATILITY: MetricValue(
                        value=None,
                        observations=3,
                        unavailable_reason="date sequences differ",
                    ),
                },
            ),
        ),
    )


def _chart() -> ChartArtifact:
    return ChartArtifact(
        chart_id=CHART_ID,
        run_id=RUN_ID,
        analysis_id=ANALYSIS_ID,
        kind=ChartKind.NORMALIZED_PRICES,
        png_path="",
        data_path="",
        data_sha256="0" * 64,
        title="t",
        x_label="date",
        y_label="price",
        series_labels=("DEMO_A",),
        created_at=datetime.now(UTC),
    )


def _service(tmp_path: Path, runs: RunService) -> ReportService:
    return ReportService(
        report_store=LocalReportStore(tmp_path),
        run_service=runs,
    )


def test_build_report_writes_markdown_and_binds(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    runs.bind_metrics(RUN_ID, SESSION, METRICS_ID)
    runs.bind_chart(RUN_ID, SESSION, CHART_ID)

    svc = _service(tmp_path, runs)
    report = svc.build_report(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis_id=ANALYSIS_ID,
        metrics_id=METRICS_ID,
        metrics=_metrics(),
        charts=(_chart(),),
    )

    path = LocalReportStore(tmp_path).get_markdown_path(report.report_id, SESSION, RUN_ID)
    md = Path(path).read_text(encoding="utf-8")
    assert "QuantLab 数据分析报告" in md
    assert "确定性演示模式" in md
    assert "## 1. 分析结论" in md
    assert "虽然期末取得正收益" in md
    assert RUN_ID in md
    assert f"{0.089 * 100:.2f}%" in md
    assert "完成时间：未记录" not in md


def test_build_report_rejects_unbound_analysis(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    svc = _service(tmp_path, runs)

    with pytest.raises(QuantLabError) as error:
        svc.build_report(
            run_id=RUN_ID,
            session_id=SESSION,
            analysis_id=ANALYSIS_ID,
            metrics_id=METRICS_ID,
            metrics=_metrics(),
            charts=(),
        )
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_build_report_rejects_mismatched_metrics_analysis(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    runs.bind_metrics(RUN_ID, SESSION, METRICS_ID)
    runs.bind_chart(RUN_ID, SESSION, CHART_ID)

    other = _metrics().model_copy(update={"analysis_id": "other-analysis"})
    svc = _service(tmp_path, runs)

    with pytest.raises(QuantLabError) as error:
        svc.build_report(
            run_id=RUN_ID,
            session_id=SESSION,
            analysis_id=ANALYSIS_ID,
            metrics_id=METRICS_ID,
            metrics=other,
            charts=(_chart(),),
        )
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_build_report_rejects_mismatched_chart_analysis(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    runs.bind_metrics(RUN_ID, SESSION, METRICS_ID)
    runs.bind_chart(RUN_ID, SESSION, CHART_ID)

    bad_chart = _chart().model_copy(update={"analysis_id": "other-analysis"})
    svc = _service(tmp_path, runs)

    with pytest.raises(QuantLabError) as error:
        svc.build_report(
            run_id=RUN_ID,
            session_id=SESSION,
            analysis_id=ANALYSIS_ID,
            metrics_id=METRICS_ID,
            metrics=_metrics(),
            charts=(bad_chart,),
        )
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_build_report_failure_does_not_write_markdown(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    # No metrics bound → UNKNOWN_REFERENCE, no markdown written.

    svc = _service(tmp_path, runs)
    with pytest.raises(QuantLabError):
        svc.build_report(
            run_id=RUN_ID,
            session_id=SESSION,
            analysis_id=ANALYSIS_ID,
            metrics_id=METRICS_ID,
            metrics=_metrics(),
            charts=(_chart(),),
        )

    # Confirm no report.md was written.
    run_dir = tmp_path / SESSION / "runs" / RUN_ID
    if run_dir.exists():
        for child in run_dir.rglob("report.md"):
            raise AssertionError(f"Unexpected report file: {child}")


def test_limitations_section_lists_unavailable_metrics(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    runs.bind_metrics(RUN_ID, SESSION, METRICS_ID)
    runs.bind_chart(RUN_ID, SESSION, CHART_ID)

    svc = _service(tmp_path, runs)
    report = svc.build_report(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis_id=ANALYSIS_ID,
        metrics_id=METRICS_ID,
        metrics=_metrics(),
        charts=(_chart(),),
    )
    md = Path(
        LocalReportStore(tmp_path).get_markdown_path(report.report_id, SESSION, RUN_ID)
    ).read_text(encoding="utf-8")
    assert "日期序列不一致" in md
    assert "年化波动率" in md


def _summary_metrics(*assets: tuple[str, float | None, float | None]) -> MetricResult:
    return MetricResult(
        metrics_id=METRICS_ID,
        analysis_id=ANALYSIS_ID,
        assets=tuple(
            AssetMetricResult(
                asset_id=name,
                metrics={
                    MetricName.PERIOD_RETURN: MetricValue(
                        value=period,
                        observations=100,
                        unavailable_reason="insufficient data" if period is None else None,
                    ),
                    MetricName.MAX_DRAWDOWN: MetricValue(
                        value=drawdown,
                        observations=100,
                        unavailable_reason="insufficient data" if drawdown is None else None,
                    ),
                },
            )
            for name, period, drawdown in assets
        ),
    )


def test_report_interprets_positive_return_and_drawdown(tmp_path: Path) -> None:
    run = _seeded_run(tmp_path).get_run(RUN_ID, SESSION)
    text = ReportService._format_analysis_summary(run, _summary_metrics(("A", 0.9518, -0.7482)))
    assert "+95.18%" in text
    assert "74.82%" in text
    assert "虽然期末取得正收益" in text
    assert "297.14%" in text
    assert "不表示已恢复或将恢复" in text


@pytest.mark.parametrize("period,direction", [(-0.2, "低于"), (0, "等于")])
def test_report_interprets_negative_and_flat_return(
    tmp_path: Path, period: float, direction: str
) -> None:
    run = _seeded_run(tmp_path).get_run(RUN_ID, SESSION)
    text = ReportService._format_analysis_summary(run, _summary_metrics(("A", period, -0.2)))
    assert f"期末价格{direction}期初" in text
    assert "虽然期末取得正收益" not in text


def test_report_unavailable_values_do_not_invent_conclusions(tmp_path: Path) -> None:
    run = _seeded_run(tmp_path).get_run(RUN_ID, SESSION)
    text = ReportService._format_analysis_summary(run, _summary_metrics(("A", None, None)))
    assert "当前没有可用指标" in text
    assert "期末价格高于期初" not in text
    assert "回到此前高点需上涨" not in text


def test_report_compares_only_aligned_complete_metrics(tmp_path: Path) -> None:
    run = _seeded_run(tmp_path).get_run(RUN_ID, SESSION)
    metrics = _summary_metrics(("A", 0.2, -0.5), ("B", 0.1, -0.1))
    text = ReportService._format_analysis_summary(run, metrics)
    assert "A 的区间收益最高" in text
    assert "10.00 个百分点" in text
    assert "B 的最大回撤较浅" in text
    assert "不能把收益排名直接当作综合优劣" in text
    run = run.model_copy(update={"context_snapshot": {"alignment_policy": "single_asset_dates"}})
    text = ReportService._format_analysis_summary(run, metrics)
    assert "不做直接排名" in text
    assert "区间收益最高" not in text


def test_report_zero_drawdown_and_short_volatility_sample(tmp_path: Path) -> None:
    run = _seeded_run(tmp_path).get_run(RUN_ID, SESSION)
    metrics = _summary_metrics(("A", 0.1, 0))
    asset = metrics.assets[0].model_copy(
        update={
            "metrics": {
                **metrics.assets[0].metrics,
                MetricName.ANNUALIZED_VOLATILITY: MetricValue(value=0.12, observations=10),
            }
        }
    )
    text = ReportService._format_analysis_summary(
        run, metrics.model_copy(update={"assets": (asset,)})
    )
    assert "不意味着未来没有风险" in text
    assert "不是预期收益" in text
    assert "少于 20 条" in text
    assert "需上涨约" not in text


def test_build_report_marks_run_succeeded(tmp_path: Path) -> None:
    runs = _seeded_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    runs.bind_metrics(RUN_ID, SESSION, METRICS_ID)
    runs.bind_chart(RUN_ID, SESSION, CHART_ID)

    svc = _service(tmp_path, runs)
    svc.build_report(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis_id=ANALYSIS_ID,
        metrics_id=METRICS_ID,
        metrics=_metrics(),
        charts=(_chart(),),
    )

    final = runs.get_run(RUN_ID, SESSION)
    assert final.status is RunStatus.SUCCEEDED
    assert final.report_id is not None
