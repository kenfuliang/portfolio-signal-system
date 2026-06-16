"""All registered strategies run on synthetic data and return valid Decisions,
including when holdings have no stop (stop=None)."""
import numpy as np
import pandas as pd
import pytest

from strategy.registry import ALL_STRATEGIES, get_strategy
from strategy.base import SymbolContext
from strategy.signals import Decision
from strategy.config_loader import Config


def _contexts(n_syms=12, held_every=3):
    rng = np.random.default_rng(7)
    syms = [f"S{i}" for i in range(n_syms)]
    ctx = {}
    for i, s in enumerate(syms):
        steps = rng.normal((i - n_syms / 2) * 0.0008, 0.02, 320)
        prices = pd.Series(100 * np.exp(np.cumsum(steps)))
        ctx[s] = SymbolContext(
            symbol=s, prices=prices, held=(i % held_every == 0),
            price=float(prices.iloc[-1]), weight=0.05, target_weight=0.10,
            stop=None,                                   # exercises null-stop path
        )
    return ctx


@pytest.fixture(scope="module")
def cfg():
    return Config.load()


def test_registry_has_all_strategies():
    assert len(ALL_STRATEGIES) >= 20


@pytest.mark.parametrize("name", ALL_STRATEGIES)
def test_strategy_runs_and_returns_decisions(name, cfg):
    decs = get_strategy(name).generate(_contexts(), cfg)
    assert isinstance(decs, list)
    assert all(isinstance(d, Decision) for d in decs)
    # symbols referenced must exist in the context (no phantom orders)
    syms = set(_contexts().keys())
    assert all(d.symbol in syms for d in decs)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        get_strategy("does_not_exist")
