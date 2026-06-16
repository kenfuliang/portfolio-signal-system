"""Config loading, validation, and accessors."""
import pytest

from strategy.config_loader import Config


def test_real_config_loads_and_validates():
    c = Config.load()
    c.validate()
    assert c.all_symbols()
    assert c.active_strategy()


def test_factor_weights_must_sum_to_one():
    c = Config(factors={"weights": {"trend": 0.5, "quality": 0.2}},
               risk={"sleeves": {"core": {}, "satellite": {}, "tactical": {}}},
               strategies={"active": "trend_ma"})
    with pytest.raises(ValueError):
        c.validate()


def test_sleeve_of_resolves():
    c = Config.load()
    syms = c.all_symbols()
    # every symbol resolves to a sleeve or None, never raises
    for s in syms[:20]:
        _ = c.sleeve_of(s)
