"""Unit tests for the diagnostics, risk and rolling services (M8 / M9)."""

from __future__ import annotations

from datetime import date

from quantlab_agent.application.analyses import AnalysisService, PreparedAnalysis
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.diagnostics import AnomalyDetectionService
from quantlab_agent.application.risk import RiskAnalysisService
from quantlab_agent.application.rolling import RollingMetricsService
from quantlab_agent.domain.models import (
    DatasetMetadata,
    MetricName,
    PriceBasis,
)


def _import_csv(asset_id: str, rows: str) -> object:
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
    return (
        DatasetService().import_csv(rows.encode("utf-8"), metadata=metadata, session_id="s").dataset
    )


def _prepared(dataset, start: str = "2024-01-02", end: str = "2024-01-31"):
    return AnalysisService().prepare(
        [dataset],
        session_id="s",
        requested_start=date.fromisoformat(start),
        requested_end=date.fromisoformat(end),
        requested_metrics=(MetricName.PERIOD_RETURN,),
    )


def test_anomaly_detection_flags_extreme_return() -> None:
    rows = (
        "date,close\n"
        "2024-01-02,100\n2024-01-03,100\n2024-01-04,100\n"
        "2024-01-05,100\n2024-01-08,150\n2024-01-09,100\n"
    )
    dataset = _import_csv("DEMO_A", rows)
    prepared = _prepared(dataset)
    report = AnomalyDetectionService().detect(prepared)
    items = next(items for aid, items in report.asset_anomalies if aid == "DEMO_A")
    assert any("2024-01-08" in item.date for item in items)


def test_risk_metrics_compute_sharpe_and_var() -> None:
    rows = (
        "date,close\n"
        "2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
        "2024-01-05,102\n2024-01-08,98\n2024-01-09,103\n"
        "2024-01-10,97\n2024-01-11,104\n2024-01-12,99\n"
        "2024-01-15,105\n"
    )
    dataset = _import_csv("DEMO_A", rows)
    prepared = _prepared(dataset)
    result = RiskAnalysisService().analyze(prepared)
    assert result.assets[0].values["sharpe_ratio"] is not None
    assert result.assets[0].values["var_95"] is not None
    assert result.assets[0].values["cvar_95"] is not None
    # max_drawdown is owned by compute_metrics, NOT by compute_risk_metrics.
    assert "max_drawdown" not in result.assets[0].values


def test_risk_calmar_uses_geometric_annualized_return() -> None:
    rows = "date,close\n2024-01-02,100\n2024-01-03,110\n2024-01-04,90\n2024-01-05,105\n"
    dataset = _import_csv("DEMO_A", rows)
    prepared = _prepared(dataset, end="2024-01-05")
    prepared = PreparedAnalysis(
        spec=prepared.spec.model_copy(update={"annualization_factor": 3}),
        assets=prepared.assets,
    )
    result = RiskAnalysisService().analyze(prepared)
    calmar = result.assets[0].values["calmar_ratio"]
    # Total return = 1.05 over 3 periods, annualized at 3 periods/year = 5%.
    # Max drawdown is 90/110 - 1 = -18.1818%, so Calmar ≈ 0.275.
    assert 0.27 < calmar < 0.28


def test_rolling_metrics_compute_windows() -> None:
    rows = "date,close\n" + "\n".join(f"2024-01-{i:02d},{100 + i % 7}" for i in range(2, 30)) + "\n"
    dataset = _import_csv("DEMO_A", rows)
    prepared = _prepared(dataset)
    report = RollingMetricsService().compute(prepared, windows=(20,))
    series = [s for s in report.series if s.metric == "rolling_volatility"]
    assert len(series) == 1
    assert series[0].window == 20
    assert series[0].points[-1].value is not None


def test_rolling_drawdown_keeps_in_window_loss_after_recovery() -> None:
    import pandas as pd
    import pytest

    values = RollingMetricsService._rolling_drawdown(pd.Series([100, 80, 110]), 3)
    assert values.iloc[:2].isna().all()
    assert values.iloc[-1] == pytest.approx(-0.2)
