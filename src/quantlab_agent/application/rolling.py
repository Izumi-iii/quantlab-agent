"""Rolling-window metrics on a prepared price series.

Default windows: ``[20, 60, 252]``. Tool callers may request a subset
of those. Window must be at least 2 observations; the first
``window - 1`` observations are returned as ``None`` per the pandas
``rolling(window, min_periods=window).agg(...)`` convention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab_agent.application.analyses import PreparedAnalysis
from quantlab_agent.domain.models import (
    RollingPoint,
    RollingReport,
    RollingSeries,
)
from quantlab_agent.domain.policies import DEFAULT_ANNUALIZATION_FACTOR

DEFAULT_WINDOWS: tuple[int, ...] = (20, 60, 252)


@dataclass(frozen=True, slots=True)
class RollingMetricsService:
    annualization_factor: int = DEFAULT_ANNUALIZATION_FACTOR

    def compute(
        self,
        prepared: PreparedAnalysis,
        windows: tuple[int, ...] = DEFAULT_WINDOWS,
    ) -> RollingReport:
        if not windows:
            return RollingReport(
                analysis_id=prepared.spec.analysis_id,
                windows=(),
                series=(),
            )
        valid_windows = tuple(sorted({w for w in windows if w >= 2}))
        if not valid_windows:
            raise ValueError("At least one window >= 2 is required.")
        series_out: list[RollingSeries] = []
        for asset in prepared.assets:
            prices = asset.to_series()
            returns = prices.pct_change().dropna()
            for window in valid_windows:
                series_out.extend(
                    [
                        self._rolling_series(
                            asset.asset_id,
                            prices,
                            window,
                            "rolling_return",
                            prices.pct_change(window),
                        ),
                        self._rolling_series(
                            asset.asset_id,
                            prices,
                            window,
                            "rolling_volatility",
                            returns.rolling(window=window, min_periods=window).std(ddof=1)
                            * math.sqrt(self.annualization_factor),
                        ),
                        self._rolling_series(
                            asset.asset_id,
                            prices,
                            window,
                            "rolling_drawdown",
                            self._rolling_drawdown(prices, window),
                        ),
                        self._rolling_series(
                            asset.asset_id,
                            prices,
                            window,
                            "rolling_sharpe",
                            self._rolling_sharpe(returns, window),
                        ),
                    ]
                )
        return RollingReport(
            analysis_id=prepared.spec.analysis_id,
            windows=valid_windows,
            series=tuple(series_out),
        )

    @staticmethod
    def _rolling_series(
        asset_id: str,
        prices: pd.Series,
        window: int,
        metric: str,
        raw: pd.Series,
    ) -> RollingSeries:
        points: list[RollingPoint] = []
        for ts, value in raw.items():
            ts_date = ts.date() if hasattr(ts, "date") else ts
            points.append(
                RollingPoint(
                    date=ts_date.isoformat() if hasattr(ts_date, "isoformat") else str(ts_date),
                    value=None if pd.isna(value) or not math.isfinite(value) else float(value),
                )
            )
        return RollingSeries(
            asset_id=asset_id,
            metric=metric,  # type: ignore[arg-type]
            window=window,
            points=tuple(points),
        )

    @staticmethod
    def _rolling_drawdown(prices: pd.Series, window: int) -> pd.Series:
        return prices.rolling(window, min_periods=window).apply(
            lambda values: float((values / np.maximum.accumulate(values) - 1).min()), raw=True
        )

    def _rolling_sharpe(self, returns: pd.Series, window: int) -> pd.Series:
        rolling_mean = returns.rolling(window=window, min_periods=window).mean()
        rolling_std = returns.rolling(window=window, min_periods=window).std(ddof=1)
        sharpe = rolling_mean / rolling_std * math.sqrt(self.annualization_factor)
        return sharpe


__all__ = ["RollingMetricsService", "DEFAULT_WINDOWS"]
