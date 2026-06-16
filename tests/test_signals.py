"""Buy/sell gate logic in signals.evaluate (the original factor-signal path)."""
import pandas as pd

from strategy.signals import evaluate, PositionState, Action


BUY = {"min_composite_percentile": 0.80, "require_above_sma200": True,
       "require_above_sma50": True, "block_days_before_earnings": 3}
SELL = {"stop_loss": True, "thesis_break": True,
        "rank_decay_below_percentile": 0.50, "risk_breach": True}


def _state(**kw):
    base = dict(symbol="X", held=False, price=100.0, above_sma50=True, above_sma200=True)
    base.update(kw)
    return PositionState(**base)


def test_top_quintile_uptrend_buys():
    comp = pd.Series({"A": 0.95, "B": 0.5, "C": 0.1})
    states = {s: _state(symbol=s) for s in comp.index}
    decs = {d.symbol: d.action for d in evaluate(comp, states, BUY, SELL)}
    assert decs["A"] == Action.BUY


def test_below_sma200_blocks_buy():
    comp = pd.Series({"A": 0.95})
    states = {"A": _state(symbol="A", above_sma200=False)}
    decs = [d for d in evaluate(comp, states, BUY, SELL) if d.action == Action.BUY]
    assert decs == []


def test_stop_loss_fires_first():
    comp = pd.Series({"A": 0.95})
    states = {"A": _state(symbol="A", held=True, price=80.0, stop=85.0)}
    d = evaluate(comp, states, BUY, SELL)[0]
    assert d.action == Action.SELL and "stop" in d.reason.lower()


def test_rank_decay_sells_held_loser():
    comp = pd.Series({"A": 0.95, "B": 0.6, "C": 0.05})
    states = {s: _state(symbol=s, held=True) for s in comp.index}
    decs = {d.symbol: d.action for d in evaluate(comp, states, BUY, SELL)}
    assert decs["C"] == Action.SELL
