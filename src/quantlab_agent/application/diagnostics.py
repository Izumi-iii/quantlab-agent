"""Anomaly detection on a prepared price series.

Uses a robust MAD-based threshold (Iglewicz–Hoaglin, k=3.5) plus a
configurable absolute threshold and gap threshold. Pure computation
on a ``PreparedAnalysis`` — no I/O, no model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from quantlab_agent.application.analyses import PreparedAnalysis
from quantlab_agent.domain.models import (
    AnomalyItem,
    AnomalyKind,
    AnomalyReport,
    AnomalySeverity,
)


@dataclass(frozen=True, slots=True)
class AnomalyDetectionService:
    """Rule-based anomaly detection on a prepared analysis.

    Defaults follow Iglewicz–Hoaglin (1993) recommendations:
    - ``mad_k = 3.5`` (robust z-score threshold for outlier labelling)
    - ``absolute_threshold = 0.15`` (single-day move in return space)
    - ``gap_threshold_days = 10`` (consecutive calendar days without an
      observation)
    """

    mad_k: float = 3.5
    absolute_threshold: float = 0.15
    gap_threshold_days: int = 10

    def detect(self, prepared: PreparedAnalysis) -> AnomalyReport:
        asset_summaries: list[tuple[str, tuple[AnomalyItem, ...]]] = []
        for asset in prepared.assets:
            series = asset.to_series()
            dates = [ts.date() if hasattr(ts, "date") else ts for ts in series.index]
            prices = series.to_numpy(dtype=float)
            returns = (
                prices[1:] / prices[:-1] - 1.0 if len(prices) >= 2 else np.array([], dtype=float)
            )
            return_dates = dates[1:] if len(prices) >= 2 else []
            items: list[AnomalyItem] = []
            items.extend(self._extreme_returns(returns, return_dates))
            items.extend(self._price_gaps(dates))
            items.sort(key=lambda item: item.date)
            asset_summaries.append((asset.asset_id, tuple(items)))
        return AnomalyReport(
            analysis_id=prepared.spec.analysis_id,
            asset_anomalies=tuple(asset_summaries),
            parameters={
                "mad_k": self.mad_k,
                "absolute_threshold": self.absolute_threshold,
                "gap_threshold_days": float(self.gap_threshold_days),
            },
        )

    def _extreme_returns(
        self,
        returns: np.ndarray,
        dates: list[date],
    ) -> list[AnomalyItem]:
        if len(returns) < 2:
            return []
        median = float(np.median(returns))
        mad = float(np.median(np.abs(returns - median)))
        items: list[AnomalyItem] = []
        if mad > 0:
            threshold = self.mad_k * mad / 0.6745  # scale MAD to σ-equivalent
            for idx, value in enumerate(returns):
                if abs(value - median) > threshold:
                    kind = (
                        AnomalyKind.EXTREME_POSITIVE_RETURN
                        if value > median
                        else AnomalyKind.EXTREME_NEGATIVE_RETURN
                    )
                    items.append(
                        AnomalyItem(
                            date=dates[idx].isoformat(),
                            kind=kind,
                            severity=AnomalySeverity.WARNING,
                            value=float(value),
                            message=(
                                "Single-period return exceeds the robust threshold; "
                                "verify whether this is a data issue or genuine market move."
                            ),
                        )
                    )
        # Absolute threshold (always reported alongside MAD).
        for idx, value in enumerate(returns):
            if abs(value) >= self.absolute_threshold and not any(
                item.date == dates[idx].isoformat() for item in items
            ):
                kind = (
                    AnomalyKind.EXTREME_POSITIVE_RETURN
                    if value > 0
                    else AnomalyKind.EXTREME_NEGATIVE_RETURN
                )
                items.append(
                    AnomalyItem(
                        date=dates[idx].isoformat(),
                        kind=kind,
                        severity=AnomalySeverity.WARNING,
                        value=float(value),
                        message=(
                            f"Single-period move of {value * 100:.2f}% exceeds the "
                            f"{self.absolute_threshold * 100:.0f}% absolute threshold."
                        ),
                    )
                )
        return items

    def _price_gaps(self, dates: list[date]) -> list[AnomalyItem]:
        if len(dates) < 2:
            return []
        items: list[AnomalyItem] = []
        sorted_dates = sorted(dates)
        for prev, curr in zip(sorted_dates, sorted_dates[1:]):
            gap_days = (curr - prev).days
            if gap_days >= self.gap_threshold_days:
                items.append(
                    AnomalyItem(
                        date=curr.isoformat(),
                        kind=AnomalyKind.PRICE_GAP,
                        severity=AnomalySeverity.INFO,
                        value=float(gap_days),
                        message=(
                            f"{gap_days} calendar days between observations; "
                            "this may indicate missing trading days or a data gap."
                        ),
                    )
                )
        return items


__all__ = ["AnomalyDetectionService"]
