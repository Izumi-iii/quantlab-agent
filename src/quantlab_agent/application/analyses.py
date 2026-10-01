"""Prepare immutable analysis snapshots and compute requested metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pandas as pd

from quantlab_agent.application.datasets import ImportedDataset
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.metrics import (
    annualized_volatility,
    max_drawdown,
    period_return,
    simple_returns,
)
from quantlab_agent.domain.models import (
    AnalysisSpec,
    AssetMetricResult,
    CapabilityDecision,
    MetricName,
    MetricResult,
    MetricValue,
    PriceBasis,
)
from quantlab_agent.domain.policies import (
    DEFAULT_ANNUALIZATION_FACTOR,
    MIN_PRICE_POINTS,
    MIN_RETURN_OBSERVATIONS_FOR_VOLATILITY,
    SHORT_SAMPLE_RETURN_OBSERVATIONS,
)


@dataclass(frozen=True, slots=True)
class PreparedAssetData:
    asset_id: str
    dates: tuple[date, ...]
    prices: tuple[float, ...]

    def to_series(self) -> pd.Series:
        return pd.Series(
            self.prices,
            index=pd.DatetimeIndex(self.dates, name="date"),
            name=self.asset_id,
            dtype=float,
        )


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    spec: AnalysisSpec
    assets: tuple[PreparedAssetData, ...]

    @property
    def prices_by_asset(self) -> dict[str, pd.Series]:
        """Return fresh Series objects so callers cannot mutate the snapshot."""
        return {asset.asset_id: asset.to_series() for asset in self.assets}


class AnalysisService:
    def prepare(
        self,
        datasets: list[ImportedDataset],
        *,
        session_id: str,
        requested_start: date,
        requested_end: date,
        requested_metrics: tuple[MetricName, ...],
    ) -> PreparedAnalysis:
        if not 1 <= len(datasets) <= 2:
            raise QuantLabError(
                ErrorCode.INVALID_ARGUMENT,
                "The first version supports one or two datasets per analysis.",
            )
        if requested_start > requested_end:
            raise QuantLabError(
                ErrorCode.INVALID_DATE_RANGE,
                "The start date must not be after the end date.",
            )
        if not requested_metrics:
            raise QuantLabError(ErrorCode.INVALID_ARGUMENT, "At least one metric is required.")
        if len(set(requested_metrics)) != len(requested_metrics):
            raise QuantLabError(ErrorCode.INVALID_ARGUMENT, "Requested metrics must be unique.")

        asset_ids = [dataset.manifest.metadata.asset_id for dataset in datasets]
        if len(set(asset_ids)) != len(asset_ids):
            raise QuantLabError(
                ErrorCode.INVALID_ARGUMENT,
                "Asset identifiers must be unique within an analysis.",
            )

        if len(datasets) == 2:
            price_bases = {dataset.manifest.metadata.price_basis for dataset in datasets}
            if PriceBasis.UNKNOWN in price_bases or len(price_bases) != 1:
                raise QuantLabError(
                    ErrorCode.INCOMPATIBLE_PRICE_BASIS,
                    "Two-asset comparison requires the same known price basis.",
                    details={"price_bases": sorted(basis.value for basis in price_bases)},
                )
            currencies = {dataset.manifest.metadata.currency for dataset in datasets}
            if "UNKNOWN" in currencies or len(currencies) != 1:
                raise QuantLabError(
                    ErrorCode.INCOMPATIBLE_CURRENCY,
                    "Two-asset comparison requires the same known currency.",
                    details={"currencies": sorted(currencies)},
                )

        sliced: dict[str, pd.Series] = {}
        for dataset in datasets:
            if dataset.manifest.session_id != session_id:
                raise QuantLabError(
                    ErrorCode.INVALID_ARGUMENT,
                    "A dataset does not belong to the current session.",
                )
            selection = tuple(
                point for point in dataset.points if requested_start <= point.date <= requested_end
            )
            if not selection:
                raise QuantLabError(
                    ErrorCode.NO_DATA_IN_RANGE,
                    f"No observations are available for {dataset.manifest.metadata.asset_id} in the requested range.",
                    details={"asset_id": dataset.manifest.metadata.asset_id},
                )
            sliced[dataset.manifest.metadata.asset_id] = pd.Series(
                (point.close for point in selection),
                index=pd.DatetimeIndex((point.date for point in selection), name="date"),
                name=dataset.manifest.metadata.asset_id,
                dtype=float,
            )

        excluded = {asset_id: 0 for asset_id in asset_ids}
        indices_match = True
        if len(datasets) == 2:
            first, second = (sliced[asset_id] for asset_id in asset_ids)
            indices_match = first.index.equals(second.index)
            common_index = first.index.intersection(second.index, sort=True)
            if common_index.empty:
                raise QuantLabError(
                    ErrorCode.NO_OVERLAP,
                    "The selected datasets have no common observation dates.",
                )
            for asset_id in asset_ids:
                excluded[asset_id] = len(sliced[asset_id]) - len(common_index)
                sliced[asset_id] = sliced[asset_id].loc[common_index].copy()
            alignment_policy = "common_observation_dates"
        else:
            alignment_policy = "single_asset_dates"

        observation_count = min(len(series) for series in sliced.values())
        complete_daily = all(
            dataset.manifest.metadata.daily_series_complete for dataset in datasets
        )
        volatility_available = (
            observation_count - 1 >= MIN_RETURN_OBSERVATIONS_FOR_VOLATILITY
            and complete_daily
            and indices_match
        )
        if observation_count - 1 < MIN_RETURN_OBSERVATIONS_FOR_VOLATILITY:
            volatility_reason = "At least two return observations are required."
        elif not complete_daily:
            volatility_reason = "Daily-series completeness was not confirmed."
        elif not indices_match:
            volatility_reason = "The original date sequences differ; interval returns cannot be treated as daily returns."
        else:
            volatility_reason = None

        basic_available = observation_count >= MIN_PRICE_POINTS
        capabilities = {
            MetricName.PERIOD_RETURN: CapabilityDecision(
                available=basic_available,
                reason=None if basic_available else "At least two price observations are required.",
            ),
            MetricName.MAX_DRAWDOWN: CapabilityDecision(
                available=basic_available,
                reason=None if basic_available else "At least two price observations are required.",
            ),
            MetricName.ANNUALIZED_VOLATILITY: CapabilityDecision(
                available=volatility_available,
                reason=volatility_reason,
            ),
        }
        effective_start = max(series.index.min().date() for series in sliced.values())
        effective_end = min(series.index.max().date() for series in sliced.values())

        spec = AnalysisSpec(
            analysis_id=str(uuid4()),
            session_id=session_id,
            dataset_ids=tuple(dataset.manifest.dataset_id for dataset in datasets),
            asset_ids=tuple(asset_ids),
            requested_start=requested_start,
            requested_end=requested_end,
            effective_start=effective_start,
            effective_end=effective_end,
            requested_metrics=requested_metrics,
            alignment_policy=alignment_policy,
            excluded_observations=excluded,
            capabilities=capabilities,
            annualization_factor=DEFAULT_ANNUALIZATION_FACTOR,
        )
        prepared_assets = tuple(
            PreparedAssetData(
                asset_id=asset_id,
                dates=tuple(timestamp.date() for timestamp in prices.index),
                prices=tuple(float(value) for value in prices.to_numpy()),
            )
            for asset_id, prices in sliced.items()
        )
        return PreparedAnalysis(spec=spec, assets=prepared_assets)

    def compute_metrics(self, analysis: PreparedAnalysis) -> MetricResult:
        asset_results: list[AssetMetricResult] = []
        for asset in analysis.assets:
            asset_id = asset.asset_id
            prices = asset.to_series()
            metric_values: dict[MetricName, MetricValue] = {}
            for metric in analysis.spec.requested_metrics:
                capability = analysis.spec.capabilities[metric]
                if not capability.available:
                    metric_values[metric] = MetricValue(
                        value=None,
                        observations=max(len(prices) - 1, 0),
                        unavailable_reason=capability.reason,
                    )
                    continue

                if metric is MetricName.PERIOD_RETURN:
                    value = period_return(prices)
                    observations = len(prices)
                    assumptions = ("Uses the selected price basis and first/last observations.",)
                elif metric is MetricName.MAX_DRAWDOWN:
                    value = max_drawdown(prices)
                    observations = len(prices)
                    assumptions = (
                        "Running peak begins at the first observation in the analysis window.",
                    )
                elif metric is MetricName.ANNUALIZED_VOLATILITY:
                    returns = simple_returns(prices)
                    value = annualized_volatility(
                        returns,
                        periods_per_year=analysis.spec.annualization_factor,
                    )
                    observations = len(returns)
                    assumptions = (
                        f"Simple daily returns annualized with sqrt({analysis.spec.annualization_factor}).",
                        "Daily-series completeness is user-declared and not independently verified.",
                    )
                    if len(returns) < SHORT_SAMPLE_RETURN_OBSERVATIONS:
                        assumptions += ("The sample contains fewer than 20 return observations.",)
                else:  # pragma: no cover - enum exhaustiveness guard
                    raise QuantLabError(ErrorCode.INVALID_ARGUMENT, f"Unsupported metric: {metric}")

                metric_values[metric] = MetricValue(
                    value=value,
                    observations=observations,
                    assumptions=assumptions,
                )

            asset_results.append(AssetMetricResult(asset_id=asset_id, metrics=metric_values))

        return MetricResult(
            metrics_id=str(uuid4()),
            analysis_id=analysis.spec.analysis_id,
            assets=tuple(asset_results),
        )
