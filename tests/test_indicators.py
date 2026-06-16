"""Indicator sanity + short-history guards."""
import numpy as np
import pandas as pd

from strategy import indicators as ind


def test_sma_and_short_history():
    p = pd.Series(range(1, 61), dtype=float)
    assert ind.sma(p, 10) == sum(range(51, 61)) / 10
    assert ind.sma(p, 100) is None            # underdetermined -> None


def test_rsi_bounds(uptrend_prices):
    r = ind.rsi(uptrend_prices, 14)
    assert r is not None and 0.0 <= r <= 100.0


def test_rsi_all_up_is_high():
    p = pd.Series(np.cumsum(np.ones(50)) + 100)   # strictly rising
    assert ind.rsi(p, 14) > 70


def test_realized_vol_positive(uptrend_prices):
    v = ind.realized_vol(uptrend_prices, 20)
    assert v is not None and v > 0


def test_macd_returns_triplet(uptrend_prices):
    m, s, h = ind.macd(uptrend_prices)
    assert all(x is not None for x in (m, s, h))


def test_indicators_none_on_tiny_series():
    p = pd.Series([100.0, 101.0])
    assert ind.rsi(p, 14) is None
    assert ind.realized_vol(p, 20) is None
    assert ind.momentum_12_1(p) is None
