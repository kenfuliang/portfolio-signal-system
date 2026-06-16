"""Breakout family (4 algorithms)."""
from __future__ import annotations

from .. import indicators as ind
from ..base import Strategy, SymbolContext
from ..signals import Decision
from ._common import build_decisions


class Breakout52w(Strategy):
    """Buy at/near 52-week highs; hold while within a band of the high."""
    name = "breakout_52w"

    def generate(self, contexts: dict[str, SymbolContext], cfg) -> list[Decision]:
        p = self.params(cfg)
        enter, exit_band = p.get("enter_within", 0.01), p.get("exit_below", 0.12)
        want = set()
        for sym, c in contexts.items():
            d = ind.dist_from_high(c.prices, 252)
            if d is None:
                continue
            # enter when near the high; keep holding until it falls exit_band below
            if d >= -enter or (c.held and d >= -exit_band):
                want.add(sym)
        return build_decisions(contexts, want, "near 52wk high", "fell off the high")


class Donchian(Strategy):
    """Turtle-style: buy a new N-day high, exit on an M-day low."""
    name = "donchian"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        n_in, n_out = p.get("entry_lookback", 20), p.get("exit_lookback", 10)
        want = set()
        for sym, c in contexts.items():
            hi = ind.donchian_high(c.prices, n_in)
            if hi is not None and c.price > hi:
                want.add(sym)
            elif c.held:
                # stay in unless price breaks the M-day low
                if len(c.prices) > n_out and c.price > float(c.prices.iloc[-(n_out + 1):-1].min()):
                    want.add(sym)
        return build_decisions(contexts, want, "N-day high breakout", "M-day low exit")


class VolatilityBreakout(Strategy):
    """Buy on an outsized up-move (return > k x daily vol) in an uptrend."""
    name = "volatility_breakout"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        k = p.get("k", 1.5)
        want = set()
        for sym, c in contexts.items():
            if len(c.prices) < 21:
                continue
            ret1 = float(c.prices.iloc[-1] / c.prices.iloc[-2] - 1.0)
            vol = ind.realized_vol(c.prices, 20)
            s50 = ind.sma(c.prices, 50)
            daily_vol = (vol / (252 ** 0.5)) if vol else None
            if daily_vol and s50 and ret1 > k * daily_vol and c.price > s50:
                want.add(sym)
            elif c.held and s50 and c.price > s50:
                want.add(sym)   # hold while above 50-MA
        return build_decisions(contexts, want, "volatility breakout", "below 50-MA")


class KeltnerBreakout(Strategy):
    """Buy above the upper Keltner channel (EMA20 + k*ATR); hold above EMA20."""
    name = "keltner_breakout"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        k, span = p.get("k", 1.5), p.get("ema", 20)
        want = set()
        for sym, c in contexts.items():
            e = ind.ema(c.prices, span)
            atr = ind.atr_from_close(c.prices, 14)
            if e is None or atr is None:
                continue
            if c.price > e + k * atr:
                want.add(sym)
            elif c.held and c.price > e:
                want.add(sym)
        return build_decisions(contexts, want, "upper Keltner breakout", "below EMA")
