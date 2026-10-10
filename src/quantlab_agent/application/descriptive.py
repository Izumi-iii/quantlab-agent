"""Descriptive statistics for a price series.

Builds a ``PriceSeriesSummary`` from an already-prepared
``PreparedAnalysis`` (one or two assets, single-dataset dates or
common observation dates). All statistics are derived in Python from
the prepared price sequence; no external libraries beyond pandas/
numpy are used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from quantlab_agent.application.analyses import PreparedAnalysis
from quantlab_agent.domain.models import (
    AssetSeriesSummary,
    PriceSeriesSummary,
)
from quantlab_agent.domain.policies import SHORT_SAMPLE_RETURN_OBSERVATIONS


@dataclass(frozen=True, slots=True)
class DescriptiveService:
    """Generate the user-facing ``PriceSeriesSummary`` from a prepared
    analysis. Reads price arrays only — never mutates the snapshot.
    """

    short_sample_observations: int = SHORT_SAMPLE_RETURN_OBSERVATIONS

    def describe(self, prepared: PreparedAnalysis) -> PriceSeriesSummary:
        spec = prepared.spec
        assets: list[AssetSeriesSummary] = []
        for asset in prepared.assets:
            series = asset.to_series()
            assets.append(self._summarize_asset(asset.asset_id, series))

        effective_start = spec.effective_start.isoformat()
        effective_end = spec.effective_end.isoformat()
        short_sample = any(
            len(asset.to_series()) - 1 < self.short_sample_observations for asset in prepared.assets
        )
        assumptions = "Single-day simple returns computed from the selected price basis."
        if short_sample:
            assumptions += (
                f" Sample size is small (< {self.short_sample_observations} "
                "observations); treat as descriptive only."
            )
        return PriceSeriesSummary(
            analysis_id=spec.analysis_id,
            effective_start=effective_start,
            effective_end=effective_end,
            alignment_policy=spec.alignment_policy,
            assets=tuple(assets),
            assumptions=assumptions,
        )

    def _summarize_asset(self, asset_id: str, prices: pd.Series) -> AssetSeriesSummary:
        if prices.empty or len(prices) < 2:
            return AssetSeriesSummary(
                asset_id=asset_id,
                start_price=None,
                end_price=None,
                min_price=None,
                min_price_date=None,
                max_price=None,
                max_price_date=None,
                total_return=None,
                up_days=None,
                down_days=None,
                flat_days=None,
                max_daily_gain=None,
                max_daily_gain_date=None,
                max_daily_loss=None,
                max_daily_loss_date=None,
                longest_up_streak=None,
                longest_down_streak=None,
            )

        start_price = float(prices.iloc[0])
        end_price = float(prices.iloc[-1])
        total_return = end_price / start_price - 1.0

        min_idx = prices.idxmin()
        max_idx = prices.idxmax()
        min_price = float(prices.loc[min_idx])
        max_price = float(prices.loc[max_idx])
        min_price_date = min_idx.date().isoformat() if hasattr(min_idx, "date") else str(min_idx)
        max_price_date = max_idx.date().isoformat() if hasattr(max_idx, "date") else str(max_idx)

        returns = prices.iloc[1:].to_numpy() / prices.iloc[:-1].to_numpy() - 1.0
        up_days = int((returns > 0).sum())
        down_days = int((returns < 0).sum())
        flat_days = int((returns == 0).sum())

        max_gain_idx = int(returns.argmax())
        max_loss_idx = int(returns.argmin())
        max_daily_gain = float(returns[max_gain_idx])
        max_daily_loss = float(returns[max_loss_idx])
        max_daily_gain_date = self._date_at(prices, max_gain_idx + 1)
        max_daily_loss_date = self._date_at(prices, max_loss_idx + 1)

        up_streak, down_streak = self._longest_streaks(returns)

        return AssetSeriesSummary(
            asset_id=asset_id,
            start_price=start_price,
            end_price=end_price,
            min_price=min_price,
            min_price_date=min_price_date,
            max_price=max_price,
            max_price_date=max_price_date,
            total_return=total_return,
            up_days=up_days,
            down_days=down_days,
            flat_days=flat_days,
            max_daily_gain=max_daily_gain,
            max_daily_gain_date=max_daily_gain_date,
            max_daily_loss=max_daily_loss,
            max_daily_loss_date=max_daily_loss_date,
            longest_up_streak=up_streak,
            longest_down_streak=down_streak,
        )

    @staticmethod
    def _date_at(prices: pd.Series, offset: int) -> str | None:
        if offset >= len(prices):
            return None
        ts = prices.index[offset]
        if hasattr(ts, "date"):
            return ts.date().isoformat()
        return str(ts)

    @staticmethod
    def _longest_streaks(returns: Any) -> tuple[int, int]:
        longest_up = 0
        longest_down = 0
        cur_up = 0
        cur_down = 0
        for value in returns:
            if value > 0:
                cur_up += 1
                cur_down = 0
            elif value < 0:
                cur_down += 1
                cur_up = 0
            else:
                cur_up = 0
                cur_down = 0
            if cur_up > longest_up:
                longest_up = cur_up
            if cur_down > longest_down:
                longest_down = cur_down
        return longest_up, longest_down


__all__ = ["DescriptiveService"]
