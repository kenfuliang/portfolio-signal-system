"""Regression tests — one per real bug that survived dozens of backtests.
Each FAILS on the old behavior and PASSES on the fix. Per the testing rule:
every fixed bug gets a regression test."""
from strategy.risk import enforce_caps
from strategy.config_loader import Config
from strategy.datacheck import is_stale


def test_regression_sector_cap_disabled_does_not_clamp(risk_cfg):
    """BUG: main.py mapped each name to its own 'sector'; the 30% per-sector cap
    then clamped every concentrated position to 30% (e.g. 'BUY SPY -> 30.0%').
    FIX: max_per_sector_pct=None disables the sector cap entirely."""
    risk_cfg["diversification"]["max_per_sector_pct"] = None
    risk_cfg["diversification"]["max_per_name_pct"] = 1.0      # isolate sector cap
    risk_cfg["sleeves"]["core"]["max"] = 1.0                   # isolate from sleeve cap
    adj, notes = enforce_caps({"SPY": 0.95}, {"SPY": "core"}, {"SPY": "SPY"}, risk_cfg)
    assert adj["SPY"] == 0.95              # NOT clamped to the phantom 0.30
    assert not any("sector" in n for n in notes)


def test_regression_sector_cap_still_works_when_set(risk_cfg):
    """Guard: when a real cap is set, it must still bind (don't over-correct)."""
    risk_cfg["diversification"]["max_per_sector_pct"] = 0.30
    risk_cfg["diversification"]["max_per_name_pct"] = 1.0
    adj, _ = enforce_caps({"A": 0.5, "B": 0.5}, {"A": "core", "B": "core"},
                          {"A": "Tech", "B": "Tech"}, risk_cfg)
    assert sum(adj.values()) <= 0.30 + 1e-9


def test_regression_yaml_boolean_ticker_coerced_to_string():
    """BUG: ticker 'ON' (ON Semiconductor) parsed by YAML as boolean True, so
    add_equity(True) crashed. FIX: all_symbols coerces bools back to strings."""
    c = Config(universe={"sleeves": {"core": [True, "AAPL"]}},
               strategies={"active": "trend_ma"})
    syms = c.all_symbols()
    assert all(isinstance(s, str) for s in syms)


def test_regression_data_freshness_detects_stale():
    """BUG: SPY data silently ended 2021-03-31 while backtesting to 2026.
    FIX: is_stale() flags a last bar far before the required end date."""
    assert is_stale("20210331", "20260616") is True
    assert is_stale("20260615", "20260616") is False
