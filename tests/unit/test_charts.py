"""Unit tests for ChartService."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from quantlab_agent.adapters.local_stores import LocalChartStore, LocalRunStore
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.application.analyses import PreparedAnalysis, PreparedAssetData
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.models import (
    AnalysisSpec,
    CapabilityDecision,
    ChartKind,
    MetricName,
    Run,
    RunBudget,
    RunMode,
    RunStatus,
)

SESSION = "00000000-0000-4000-8000-000000000001"
RUN_ID = "11111111-1111-4111-8111-111111111111"
ANALYSIS_ID = "33333333-3333-4333-8333-333333333333"


def _budget() -> RunBudget:
    return RunBudget(
        max_model_interactions=8,
        max_tool_executions=12,
        max_same_validation_retry=1,
        max_retryable_network_errors=1,
        per_request_timeout_seconds=30,
        total_deadline_seconds=120,
    )


def _prepared() -> PreparedAnalysis:
    dates = tuple(datetime(2024, 1, d, tzinfo=UTC).date() for d in (2, 3, 4, 5))
    assets = (
        PreparedAssetData(
            asset_id="DEMO_A",
            dates=dates,
            prices=(100.0, 101.0, 99.0, 103.0),
        ),
    )
    spec = AnalysisSpec(
        analysis_id=ANALYSIS_ID,
        session_id=SESSION,
        dataset_ids=(),
        asset_ids=("DEMO_A",),
        requested_start=dates[0],
        requested_end=dates[-1],
        effective_start=dates[0],
        effective_end=dates[-1],
        requested_metrics=(MetricName.PERIOD_RETURN,),
        alignment_policy="single_asset_dates",
        excluded_observations={"DEMO_A": 0},
        capabilities={
            MetricName.PERIOD_RETURN: CapabilityDecision(available=True),
            MetricName.ANNUALIZED_VOLATILITY: CapabilityDecision(available=False, reason="x"),
            MetricName.MAX_DRAWDOWN: CapabilityDecision(available=True),
        },
        annualization_factor=252,
    )
    return PreparedAnalysis(spec=spec, assets=assets)


def _seed_run(tmp_path: Path) -> RunService:
    store = LocalRunStore(tmp_path)
    store.create(
        Run(
            run_id=RUN_ID,
            session_id=SESSION,
            mode=RunMode.DEMO,
            status=RunStatus.RUNNING,
            user_request="x",
            dataset_ids=(),
            budgets=_budget(),
            created_at=datetime.now(UTC),
        )
    )
    return RunService(store)


def _service(tmp_path: Path, runs: RunService) -> ChartService:
    return ChartService(
        chart_store=LocalChartStore(tmp_path),
        plot_service=PlotService(),
        run_service=runs,
    )


def test_create_charts_produces_png_and_data(tmp_path: Path) -> None:
    runs = _seed_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    svc = _service(tmp_path, runs)

    artifacts = svc.create_charts(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis=_prepared(),
        kinds=(ChartKind.NORMALIZED_PRICES, ChartKind.DRAWDOWN),
    )

    assert len(artifacts) == 2
    chart_store = LocalChartStore(tmp_path)
    for artifact in artifacts:
        png_path = chart_store.get_png_path(artifact.chart_id, SESSION, RUN_ID)
        png_bytes = Path(png_path).read_bytes()
        assert png_bytes.startswith(b"\x89PNG")
        assert len(png_bytes) > 200


def test_create_charts_binds_each_chart_to_run(tmp_path: Path) -> None:
    runs = _seed_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    svc = _service(tmp_path, runs)

    artifacts = svc.create_charts(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis=_prepared(),
        kinds=(ChartKind.NORMALIZED_PRICES,),
    )

    run = runs.get_run(RUN_ID, SESSION)
    assert run.chart_ids == tuple(a.chart_id for a in artifacts)


def test_create_charts_runs_without_unbound_check(tmp_path: Path) -> None:
    """ChartService trusts the caller; ownership is checked at the tool layer."""
    runs = _seed_run(tmp_path)
    svc = _service(tmp_path, runs)

    # Without an analysis_id bound on the run, ChartService still produces
    # artifacts (the tool registry is responsible for the ownership check).
    artifacts = svc.create_charts(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis=_prepared(),
        kinds=(ChartKind.NORMALIZED_PRICES,),
    )
    assert len(artifacts) == 1


def test_chart_data_payload_is_round_trippable(tmp_path: Path) -> None:
    runs = _seed_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    svc = _service(tmp_path, runs)

    artifacts = svc.create_charts(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis=_prepared(),
        kinds=(ChartKind.NORMALIZED_PRICES,),
    )

    chart_store = LocalChartStore(tmp_path)
    data_path = chart_store.get_data_path(artifacts[0].chart_id, SESSION, RUN_ID)
    payload = json.loads(Path(data_path).read_text(encoding="utf-8"))
    assert "series" in payload
    assert payload["series"][0]["asset_id"] == "DEMO_A"
    assert len(payload["series"][0]["x"]) == 4


def test_chart_data_sha256_matches_payload(tmp_path: Path) -> None:
    runs = _seed_run(tmp_path)
    runs.bind_analysis(RUN_ID, SESSION, ANALYSIS_ID)
    svc = _service(tmp_path, runs)

    artifacts = svc.create_charts(
        run_id=RUN_ID,
        session_id=SESSION,
        analysis=_prepared(),
        kinds=(ChartKind.DRAWDOWN,),
    )
    chart_store = LocalChartStore(tmp_path)
    data_path = chart_store.get_data_path(artifacts[0].chart_id, SESSION, RUN_ID)
    payload = json.loads(Path(data_path).read_text(encoding="utf-8"))
    expected = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    assert artifacts[0].data_sha256 == expected
