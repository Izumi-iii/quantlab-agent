"""Risk analysis on a prepared price series.

Produces a ``RiskAnalysisResult`` containing per-asset risk indicators
that do NOT overlap with ``compute_metrics`` (no max_drawdown — already
owned by ``compute_metrics``; no annualized_volatility — already
owned; no period_return — already owned). The two services
deliberately own disjoint outputs to keep the evidence chain
unambiguous (see ``Docs/ANALYSIS_UPGRADE_DESIGN.md §2.6``).

Annualization factor is fixed at ``AnalysisService.annualization_factor``
(defaults to 252); ``risk_free_rate`` and ``confidence_level`` are NOT
exposed as tool parameters in the first slice (see design doc §5.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from quantlab_agent.application.analyses import PreparedAnalysis
from quantlab_agent.domain.models import (
    AssetRiskResult,
    RiskAnalysisResult,
    RiskMetricName,
)
from quantlab_agent.domain.policies import (
    DEFAULT_ANNUALIZATION_FACTOR,
    SHORT_SAMPLE_RETURN_OBSERVATIONS,
)


@dataclass(frozen=True, slots=True)
class RiskAnalysisService:
    risk_free_rate: float = 0.0
    confidence_level: float = 0.95
    annualization_factor: int = DEFAULT_ANNUALIZATION_FACTOR
    short_sample_observations: int = SHORT_SAMPLE_RETURN_OBSERVATIONS

    def analyze(self, prepared: PreparedAnalysis) -> RiskAnalysisResult:
        spec = prepared.spec
        annualization_factor = spec.annualization_factor
        asset_results: list[AssetRiskResult] = []
        any_short_sample = False
        for asset in prepared.assets:
            series = asset.to_series()
            prices = series.to_numpy(dtype=float)
            if len(prices) < 2:
                asset_results.append(
                    AssetRiskResult(
                        asset_id=asset.asset_id,
                        values={},
                        unavailable={"all": "At least two price observations are required."},
                    )
                )
                continue
            returns = prices[1:] / prices[:-1] - 1.0
            n_returns = len(returns)
            if n_returns < self.short_sample_observations:
                any_short_sample = True
            values: dict[RiskMetricName, float] = {}
            unavailable: dict[str, str] = {}
            values[RiskMetricName.MEAN_DAILY_RETURN] = float(returns.mean())
            values[RiskMetricName.STD_DAILY_RETURN] = (
                float(returns.std(ddof=1)) if n_returns >= 2 else float("nan")
            )
            if not math.isnan(values[RiskMetricName.STD_DAILY_RETURN]):
                values[RiskMetricName.ANNUALIZED_RETURN] = float(
                    (1.0 + returns.mean()) ** annualization_factor - 1.0
                )
            else:
                unavailable["annualized_return"] = "Insufficient return observations."
            sharpe = self._sharpe(returns, annualization_factor=annualization_factor)
            if sharpe is not None:
                values[RiskMetricName.SHARPE_RATIO] = sharpe
            else:
                unavailable["sharpe_ratio"] = "Zero or undefined stddev."
            sortino = self._sortino(returns, annualization_factor=annualization_factor)
            if sortino is not None:
                values[RiskMetricName.SORTINO_RATIO] = sortino
            else:
                unavailable["sortino_ratio"] = "No negative returns observed."
            var = self._var(returns)
            if var is not None:
                values[RiskMetricName.VAR_95] = var
            else:
                unavailable["var_95"] = "Insufficient return observations."
            cvar = self._cvar(returns)
            if cvar is not None:
                values[RiskMetricName.CVAR_95] = cvar
            else:
                unavailable["cvar_95"] = "Insufficient return observations for CVaR."
            calmar = self._calmar(prepared, asset.asset_id)
            if calmar is not None:
                values[RiskMetricName.CALMAR_RATIO] = calmar
            else:
                unavailable["calmar_ratio"] = (
                    "Max drawdown unavailable; cannot compute Calmar ratio."
                )
            asset_results.append(
                AssetRiskResult(
                    asset_id=asset.asset_id,
                    values=values,
                    unavailable=unavailable,
                )
            )
        assumptions = (
            f"Annualization factor fixed at {annualization_factor}. "
            f"Risk-free rate assumed {self.risk_free_rate}. "
            f"VaR / CVaR use historical quantile (no normal assumption) at "
            f"{self.confidence_level * 100:.0f}% confidence."
        )
        if any_short_sample:
            assumptions += " Sample size is small; treat outputs as descriptive only."
        return RiskAnalysisResult(
            analysis_id=spec.analysis_id,
            annualization_factor=annualization_factor,
            risk_free_rate=self.risk_free_rate,
            confidence_level=self.confidence_level,
            assets=tuple(asset_results),
            assumptions=assumptions,
        )

    def _sharpe(self, returns: np.ndarray, *, annualization_factor: int) -> float | None:
        std = returns.std(ddof=1)
        if std == 0 or math.isnan(std):
            return None
        excess = returns.mean() - self.risk_free_rate / annualization_factor
        return float(excess * math.sqrt(annualization_factor) / std)

    def _sortino(self, returns: np.ndarray, *, annualization_factor: int) -> float | None:
        downside = returns[returns < 0]
        if len(downside) < 2:
            return None
        down_std = downside.std(ddof=1)
        if down_std == 0 or math.isnan(down_std):
            return None
        excess = returns.mean() - self.risk_free_rate / annualization_factor
        return float(excess * math.sqrt(annualization_factor) / down_std)

    def _var(self, returns: np.ndarray) -> float | None:
        if len(returns) < 2:
            return None
        return float(-np.quantile(returns, 1 - self.confidence_level))

    def _cvar(self, returns: np.ndarray) -> float | None:
        if len(returns) < 2:
            return None
        cutoff = np.quantile(returns, 1 - self.confidence_level)
        tail = returns[returns <= cutoff]
        if len(tail) == 0:
            return None
        return float(-tail.mean())

    def _calmar(self, prepared: PreparedAnalysis, asset_id: str) -> float | None:
        spec = prepared.spec
        for asset in prepared.assets:
            if asset.asset_id != asset_id:
                continue
            series = asset.to_series()
            if len(series) < 2:
                return None
            running_peak = series.cummax()
            drawdowns = series / running_peak - 1.0
            max_dd = float(drawdowns.min())
            if max_dd == 0:
                return None
            total_return = float(series.iloc[-1] / series.iloc[0])
            periods = max(len(series) - 1, 1)
            annualized = total_return ** (spec.annualization_factor / periods) - 1.0
            return float(annualized / abs(max_dd))
        return None


__all__ = ["RiskAnalysisService"]
