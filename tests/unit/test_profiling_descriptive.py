"""Unit tests for ProfilingService and DescriptiveService."""

from __future__ import annotations

from datetime import date

from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.descriptive import DescriptiveService
from quantlab_agent.application.profiling import ProfilingService
from quantlab_agent.domain.models import DatasetMetadata, MetricName, PriceBasis


def _make_dataset(asset_id: str = "DEMO_A"):
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
    content = b"date,close\n2024-01-02,100\n2024-01-03,110\n2024-01-04,99\n2024-01-05,108.9\n"
    return DatasetService().import_csv(content, metadata=metadata, session_id="s").dataset


def test_profiling_service_returns_columns_and_quality_summary() -> None:
    dataset = _make_dataset()
    profile = ProfilingService().profile(dataset)
    assert profile.asset_id == "DEMO_A"
    assert profile.row_count == 4
    date_col = next(c for c in profile.columns if c.semantic_type == "date")
    price_col = next(c for c in profile.columns if c.semantic_type == "numeric_price")
    assert date_col.min == "2024-01-02"
    assert date_col.max == "2024-01-05"
    assert price_col.min == 99.0
    assert price_col.max == 110.0
    assert price_col.mean is not None
    assert price_col.std is not None


def test_descriptive_service_returns_total_return_and_streaks() -> None:
    dataset = _make_dataset()
    from quantlab_agent.application.analyses import AnalysisService

    prepared = AnalysisService().prepare(
        [dataset],
        session_id="s",
        requested_start=date.fromisoformat("2024-01-02"),
        requested_end=date.fromisoformat("2024-01-05"),
        requested_metrics=(MetricName.PERIOD_RETURN,),
    )
    summary = DescriptiveService().describe(prepared)
    assert summary.assets[0].total_return is not None
    assert summary.assets[0].total_return > 0
    assert summary.assets[0].max_price == 110.0
    assert summary.assets[0].min_price == 99.0
    assert summary.assets[0].up_days is not None
    assert summary.assets[0].up_days + summary.assets[0].down_days <= 3
