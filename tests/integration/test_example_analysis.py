from datetime import date
from pathlib import Path

from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.domain.models import DatasetMetadata, MetricName, PriceBasis

EXAMPLES = Path(__file__).parents[2] / "data" / "examples"


def import_example(filename: str, asset_id: str):
    metadata = DatasetMetadata(
        asset_id=asset_id,
        source_name="repository synthetic example",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="synthetic weekdays",
        daily_series_complete=True,
        is_synthetic=True,
    )
    result = DatasetService().import_csv(
        (EXAMPLES / filename).read_bytes(),
        metadata=metadata,
        session_id="example-session",
    )
    assert result.dataset is not None
    return result.dataset


def test_repository_examples_complete_analysis_flow() -> None:
    first = import_example("DEMO_A.csv", "DEMO_A")
    second = import_example("DEMO_B.csv", "DEMO_B")
    service = AnalysisService()

    analysis = service.prepare(
        [first, second],
        session_id="example-session",
        requested_start=date(2024, 1, 2),
        requested_end=date(2024, 1, 15),
        requested_metrics=(
            MetricName.PERIOD_RETURN,
            MetricName.ANNUALIZED_VOLATILITY,
            MetricName.MAX_DRAWDOWN,
        ),
    )
    result = service.compute_metrics(analysis)

    assert analysis.spec.effective_start == date(2024, 1, 2)
    assert analysis.spec.effective_end == date(2024, 1, 15)
    assert {asset.asset_id for asset in result.assets} == {"DEMO_A", "DEMO_B"}
    for asset in result.assets:
        assert all(metric.value is not None for metric in asset.metrics.values())
