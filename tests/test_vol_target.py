"""Unit tests for the vol_target_momentum strategy overlay (pure, no LEAN)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.base import SymbolContext
from strategy.signals import Action
from strategy.strategies.vol_target import VolTargetMomentum


class _Cfg:
    """Minimal cfg stub exposing the params() lookup the strategy needs."""
    def __init__(self, params):
        self.strategies = {"vol_target_momentum": params}


def _series(values):
    return pd.Series(values, index=pd.RangeIndex(len(values)))


def _trend(start, daily_ret, n, noise=0.0, seed=0):
    """Geometric price path with optional daily gaussian noise (for vol)."""
    rng = np.random.default_rng(seed)
    rets = np.full(n, daily_ret) + rng.normal(0, noise, n)
    return _series(start * np.cumprod(1.0 + rets))


def _ctx(prices, held=False):
    p = _series(prices) if not isinstance(prices, pd.Series) else prices
    return SymbolContext(symbol="X", prices=p, held=held, price=float(p.iloc[-1]))


def _make_universe(proxy_prices, names, seed=1):
    ctxs = {"QQQ": _ctx(proxy_prices)}
    for i, nm in enumerate(names):
        # each name a calm uptrend with positive 12-1 momentum
        ctxs[nm] = _ctx(_trend(100, 0.0008, 300, noise=0.005, seed=seed + i))
    return ctxs


def _wants(decisions):
    return {d.symbol for d in decisions if d.action in (Action.BUY, Action.HOLD)}


def test_risk_off_when_below_trend_ma():
    """Proxy below its 200-day MA => go fully to cash (no holds)."""
    # rises then crashes hard so latest price is below the 200d MA
    up = _trend(100, 0.001, 220, seed=2)
    down = _series(np.linspace(float(up.iloc[-1]), float(up.iloc[-1]) * 0.6, 90))
    proxy = pd.concat([up, down], ignore_index=True)
    ctxs = _make_universe(proxy, ["FN", "MRVL", "CIEN"])
    cfg = _Cfg({"top_n": 3, "target_vol": 0.30, "vol_window": 20, "regime_ma": 200})
    out = VolTargetMomentum().generate(ctxs, cfg)
    assert _wants(out) == set(), "should hold nothing below the trend gate"


def test_vol_targeting_trims_in_high_vol_regime():
    """Calm uptrend holds more names than an otherwise-identical high-vol uptrend."""
    names = ["FN", "MRVL", "CIEN", "GLW", "COHR"]
    cfg = _Cfg({"top_n": 5, "target_vol": 0.30, "vol_window": 20, "regime_ma": 200})

    calm = _make_universe(_trend(100, 0.001, 300, noise=0.005, seed=10), names)
    choppy = _make_universe(_trend(100, 0.001, 300, noise=0.05, seed=10), names)

    n_calm = len(_wants(VolTargetMomentum().generate(calm, cfg)))
    n_choppy = len(_wants(VolTargetMomentum().generate(choppy, cfg)))
    assert n_calm > n_choppy, f"high vol should trim exposure: {n_calm} vs {n_choppy}"
    assert n_choppy >= 0


def test_calm_uptrend_holds_full_top_n():
    """Low-vol uptrend with a calm proxy deploys the full top_n."""
    names = ["FN", "MRVL", "CIEN"]
    proxy = _trend(100, 0.001, 300, noise=0.003, seed=20)
    ctxs = _make_universe(proxy, names, seed=5)
    cfg = _Cfg({"top_n": 3, "target_vol": 0.60, "vol_window": 20, "regime_ma": 200})
    out = VolTargetMomentum().generate(ctxs, cfg)
    assert len(_wants(out)) == 3
