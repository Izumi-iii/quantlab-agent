import math

import pandas as pd
import pytest

from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.metrics import (
    annualized_volatility,
    drawdown_series,
    max_drawdown,
    normalized_prices,
    period_return,
    simple_returns,
)


def test_hand_calculated_price_sequence() -> None:
    prices = pd.Series([100.0, 110.0, 99.0, 108.9])

    returns = simple_returns(prices)

    assert returns.tolist() == pytest.approx([0.10, -0.10, 0.10])
    assert period_return(prices) == pytest.approx(0.089)
    assert max_drawdown(prices) == pytest.approx(-0.10)
    assert normalized_prices(prices).tolist() == pytest.approx([100.0, 110.0, 99.0, 108.9])

    mean = 1 / 30
    expected_sample_variance = ((0.10 - mean) ** 2 + (-0.10 - mean) ** 2 + (0.10 - mean) ** 2) / 2
    expected_volatility = math.sqrt(expected_sample_variance) * math.sqrt(252)
    assert annualized_volatility(returns) == pytest.approx(expected_volatility)


def test_drawdown_for_monotonic_series() -> None:
    increasing = pd.Series([100.0, 110.0, 120.0])
    decreasing = pd.Series([100.0, 90.0, 80.0])

    assert drawdown_series(increasing).tolist() == pytest.approx([0.0, 0.0, 0.0])
    assert max_drawdown(increasing) == pytest.approx(0.0)
    assert max_drawdown(decreasing) == pytest.approx(-0.20)


def test_constant_prices_have_zero_volatility() -> None:
    returns = simple_returns(pd.Series([10.0, 10.0, 10.0]))
    assert annualized_volatility(returns) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "prices, expected_code",
    [
        ([100.0], ErrorCode.INSUFFICIENT_DATA),
        ([100.0, 0.0], ErrorCode.INVALID_PRICE),
        ([100.0, -1.0], ErrorCode.INVALID_PRICE),
        ([100.0, float("nan")], ErrorCode.INVALID_ARGUMENT),
    ],
)
def test_invalid_price_inputs_raise_domain_errors(
    prices: list[float], expected_code: ErrorCode
) -> None:
    with pytest.raises(QuantLabError) as error:
        period_return(pd.Series(prices))

    assert error.value.code is expected_code


def test_volatility_requires_two_returns() -> None:
    with pytest.raises(QuantLabError) as error:
        annualized_volatility(pd.Series([0.01]))

    assert error.value.code is ErrorCode.INSUFFICIENT_DATA
