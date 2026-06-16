"""Shared fixtures. Pure-Python only — no LEAN, no Docker, no network."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def uptrend_prices():
    """300 chronological daily closes in a steady uptrend."""
    steps = np.linspace(0.0003, 0.0009, 300) + np.sin(np.linspace(0, 12, 300)) * 0.001
    return pd.Series(100 * np.exp(np.cumsum(steps)))


@pytest.fixture
def risk_cfg():
    """A representative risk config (mirrors config/risk.yaml shape)."""
    return {
        "sizing": {"risk_per_trade_pct": 0.0075, "max_position_pct": 0.10,
                   "atr_stop_multiple": 2.5, "atr_period": 14},
        "sleeves": {"core": {"min": 0.50, "max": 0.70},
                    "satellite": {"min": 0.20, "max": 0.40},
                    "tactical": {"min": 0.0, "max": 0.10}},
        "diversification": {"max_per_name_pct": 0.10, "max_per_sector_pct": None,
                            "min_cash_buffer_pct": 0.05},
        "leveraged": {"symbols": ["AXTX"], "portfolio_cap_pct": 0.10,
                      "tighter_stop_atr_multiple": 1.5},
        "circuit_breaker": {"max_drawdown_pct": 0.15},
    }
