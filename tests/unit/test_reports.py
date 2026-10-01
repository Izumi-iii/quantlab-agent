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
    assert "QuantLab analysis report" in md
    assert "Deterministic demo mode" in md
    assert RUN_ID in md
    assert f"{0.089 * 100:.2f}%" in md
    assert "Run completed at: n/a" not in md


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
    assert "date sequences differ" in md
    assert "annualized_volatility" in md


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
