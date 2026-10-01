from datetime import date

import pytest

from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.datasets import DatasetService, ImportedDataset
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import DatasetMetadata, MetricName, PriceBasis

ALL_METRICS = (
    MetricName.PERIOD_RETURN,
    MetricName.ANNUALIZED_VOLATILITY,
    MetricName.MAX_DRAWDOWN,
)


def imported_dataset(
    asset_id: str,
    rows: list[tuple[str, float]],
    *,
    session_id: str = "session-1",
    complete: bool = True,
    price_basis: PriceBasis = PriceBasis.FORWARD_ADJUSTED,
    currency: str = "CNY",
) -> ImportedDataset:
    csv = "date,close\n" + "".join(f"{day},{price}\n" for day, price in rows)
    metadata = DatasetMetadata(
        asset_id=asset_id,
        source_name="synthetic test fixture",
        price_basis=price_basis,
        currency=currency,
        frequency="daily",
        calendar_label="synthetic weekdays",
        daily_series_complete=complete,
        is_synthetic=True,
    )
    result = DatasetService().import_csv(
        csv.encode("utf-8"), metadata=metadata, session_id=session_id
    )
    assert result.dataset is not None
    return result.dataset


def test_single_asset_analysis_computes_requested_metrics() -> None:
    dataset = imported_dataset(
        "DEMO_A",
        [("2024-01-02", 100.0), ("2024-01-03", 110.0), ("2024-01-04", 99.0), ("2024-01-05", 108.9)],
    )
    service = AnalysisService()

    analysis = service.prepare(
        [dataset],
        session_id="session-1",
        requested_start=date(2024, 1, 2),
        requested_end=date(2024, 1, 5),
        requested_metrics=ALL_METRICS,
    )
    result = service.compute_metrics(analysis)

    metrics = result.assets[0].metrics
    assert result.analysis_id == analysis.spec.analysis_id
    assert metrics[MetricName.PERIOD_RETURN].value == pytest.approx(0.089)
    assert metrics[MetricName.MAX_DRAWDOWN].value == pytest.approx(-0.10)
    assert metrics[MetricName.ANNUALIZED_VOLATILITY].value is not None
    assert "fewer than 20" in metrics[MetricName.ANNUALIZED_VOLATILITY].assumptions[-1]


def test_exposed_series_cannot_mutate_analysis_snapshot() -> None:
    dataset = imported_dataset(
        "DEMO_A",
        [("2024-01-02", 100.0), ("2024-01-03", 101.0)],
    )
    analysis = AnalysisService().prepare(
        [dataset],
        session_id="session-1",
        requested_start=date(2024, 1, 2),
        requested_end=date(2024, 1, 3),
        requested_metrics=(MetricName.PERIOD_RETURN,),
    )

    exposed = analysis.prices_by_asset["DEMO_A"]
    exposed.iloc[0] = 1.0

    assert analysis.prices_by_asset["DEMO_A"].iloc[0] == 100.0


def test_two_assets_align_to_common_dates_and_disable_daily_volatility() -> None:
    first = imported_dataset(
        "A",
        [
            ("2024-01-02", 100.0),
            ("2024-01-03", 101.0),
            ("2024-01-04", 102.0),
            ("2024-01-05", 103.0),
        ],
    )
    second = imported_dataset(
        "B",
        [("2024-01-02", 100.0), ("2024-01-04", 99.0), ("2024-01-05", 101.0)],
    )

    service = AnalysisService()
    analysis = service.prepare(
        [first, second],
        session_id="session-1",
        requested_start=date(2024, 1, 2),
        requested_end=date(2024, 1, 5),
        requested_metrics=ALL_METRICS,
    )
    result = service.compute_metrics(analysis)

    assert analysis.spec.excluded_observations == {"A": 1, "B": 0}
    assert len(analysis.prices_by_asset["A"]) == 3
    assert not analysis.spec.capabilities[MetricName.ANNUALIZED_VOLATILITY].available
    for asset in result.assets:
        volatility = asset.metrics[MetricName.ANNUALIZED_VOLATILITY]
        assert volatility.value is None
        assert "date sequences differ" in volatility.unavailable_reason


def test_unknown_price_basis_blocks_comparison() -> None:
    first = imported_dataset("A", [("2024-01-02", 100), ("2024-01-03", 101)])
    second = imported_dataset(
        "B",
        [("2024-01-02", 100), ("2024-01-03", 101)],
        price_basis=PriceBasis.UNKNOWN,
    )

    with pytest.raises(QuantLabError) as error:
        AnalysisService().prepare(
            [first, second],
            session_id="session-1",
            requested_start=date(2024, 1, 2),
            requested_end=date(2024, 1, 3),
            requested_metrics=(MetricName.PERIOD_RETURN,),
        )

    assert error.value.code is ErrorCode.INCOMPATIBLE_PRICE_BASIS


def test_different_currency_blocks_comparison() -> None:
    first = imported_dataset("A", [("2024-01-02", 100), ("2024-01-03", 101)])
    second = imported_dataset(
        "B",
        [("2024-01-02", 100), ("2024-01-03", 101)],
        currency="USD",
    )

    with pytest.raises(QuantLabError) as error:
        AnalysisService().prepare(
            [first, second],
            session_id="session-1",
            requested_start=date(2024, 1, 2),
            requested_end=date(2024, 1, 3),
            requested_metrics=(MetricName.PERIOD_RETURN,),
        )

    assert error.value.code is ErrorCode.INCOMPATIBLE_CURRENCY


def test_cross_session_dataset_is_rejected() -> None:
    dataset = imported_dataset(
        "A",
        [("2024-01-02", 100), ("2024-01-03", 101)],
        session_id="other-session",
    )

    with pytest.raises(QuantLabError) as error:
        AnalysisService().prepare(
            [dataset],
            session_id="session-1",
            requested_start=date(2024, 1, 2),
            requested_end=date(2024, 1, 3),
            requested_metrics=(MetricName.PERIOD_RETURN,),
        )

    assert error.value.code is ErrorCode.INVALID_ARGUMENT


def test_no_overlapping_dates_is_rejected() -> None:
    first = imported_dataset("A", [("2024-01-02", 100), ("2024-01-03", 101)])
    second = imported_dataset("B", [("2024-02-01", 100), ("2024-02-02", 101)])

    with pytest.raises(QuantLabError) as error:
        AnalysisService().prepare(
            [first, second],
            session_id="session-1",
            requested_start=date(2024, 1, 1),
            requested_end=date(2024, 2, 28),
            requested_metrics=(MetricName.PERIOD_RETURN,),
        )

    assert error.value.code is ErrorCode.NO_OVERLAP


def test_short_range_returns_null_metric_with_reason() -> None:
    dataset = imported_dataset("A", [("2024-01-02", 100), ("2024-01-03", 101)])
    service = AnalysisService()
    analysis = service.prepare(
        [dataset],
        session_id="session-1",
        requested_start=date(2024, 1, 2),
        requested_end=date(2024, 1, 2),
        requested_metrics=(MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN),
    )

    result = service.compute_metrics(analysis)

    for metric in result.assets[0].metrics.values():
        assert metric.value is None
        assert metric.unavailable_reason == "At least two price observations are required."
