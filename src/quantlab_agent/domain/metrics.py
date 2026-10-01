"""Pure, deterministic calculations used by every application mode."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quantlab_agent.domain.errors import ErrorCode, QuantLabError


def _validated_numeric_series(values: pd.Series, *, name: str) -> pd.Series:
    if not isinstance(values, pd.Series):
        raise QuantLabError(
            ErrorCode.INVALID_ARGUMENT,
            f"{name} must be a pandas Series.",
        )
    if values.empty:
        raise QuantLabError(ErrorCode.INSUFFICIENT_DATA, f"{name} cannot be empty.")

    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    finite = np.isfinite(numeric.to_numpy())
    if numeric.isna().any() or not finite.all():
        raise QuantLabError(
            ErrorCode.INVALID_ARGUMENT,
            f"{name} contains missing or non-finite values.",
        )
    return numeric


def _validated_prices(prices: pd.Series, *, minimum: int = 2) -> pd.Series:
    numeric = _validated_numeric_series(prices, name="prices")
    if len(numeric) < minimum:
        raise QuantLabError(
            ErrorCode.INSUFFICIENT_DATA,
            f"At least {minimum} price observations are required.",
            details={"observations": len(numeric), "required": minimum},
        )
    if (numeric <= 0).any():
        raise QuantLabError(ErrorCode.INVALID_PRICE, "Prices must be greater than zero.")
    return numeric


def period_return(prices: pd.Series) -> float:
    numeric = _validated_prices(prices)
    return float(numeric.iloc[-1] / numeric.iloc[0] - 1.0)


def simple_returns(prices: pd.Series) -> pd.Series:
    numeric = _validated_prices(prices)
    result = numeric.iloc[1:].to_numpy() / numeric.iloc[:-1].to_numpy() - 1.0
    return pd.Series(result, index=numeric.index[1:], name="simple_return", dtype=float)


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    numeric = _validated_numeric_series(returns, name="returns")
    if len(numeric) < 2:
        raise QuantLabError(
            ErrorCode.INSUFFICIENT_DATA,
            "At least two return observations are required for sample volatility.",
            details={"observations": len(numeric), "required": 2},
        )
    if periods_per_year <= 0:
        raise QuantLabError(
            ErrorCode.INVALID_ARGUMENT,
            "periods_per_year must be greater than zero.",
        )
    return float(numeric.std(ddof=1) * math.sqrt(periods_per_year))


def drawdown_series(prices: pd.Series) -> pd.Series:
    numeric = _validated_prices(prices)
    running_peak = numeric.cummax()
    result = numeric / running_peak - 1.0
    result.name = "drawdown"
    return result


def max_drawdown(prices: pd.Series) -> float:
    return float(drawdown_series(prices).min())


def normalized_prices(prices: pd.Series) -> pd.Series:
    numeric = _validated_prices(prices)
    result = numeric / numeric.iloc[0] * 100.0
    result.name = "normalized_price"
    return result
