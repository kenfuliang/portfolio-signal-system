"""Mean-reversion family (4 algorithms). All buy dips *within a long uptrend*
(price > 200-MA) to avoid catching falling knives."""
from __future__ import annotations

from .. import indicators as ind
from ..base import Strategy, SymbolContext
from ..signals import Decision
from ._common import build_decisions


def _uptrend(c: SymbolContext):
    s200 = ind.sma(c.prices, 200)
    return s200 is not None and c.price > s200


class RsiReversion(Strategy):
    """Buy oversold (RSI<lo) in an uptrend; exit when RSI recovers (>hi)."""
    name = "rsi_reversion"

    def generate(self, contexts: dict[str, SymbolContext], cfg) -> list[Decision]:
        p = self.params(cfg)
        lo, hi, n = p.get("rsi_below", 35), p.get("rsi_above", 55), p.get("rsi_period", 14)
        want = set()
        for sym, c in contexts.items():
            r = ind.rsi(c.prices, n)
            if r is None:
                continue
            if not c.held and _uptrend(c) and r <= lo:
                want.add(sym)
            elif c.held and r < hi and _uptrend(c):
                want.add(sym)   # still oversold/recovering and trend intact
        return build_decisions(contexts, want, "oversold dip", "reverted / trend break")


class BollingerReversion(Strategy):
    """Buy below the lower Bollinger band in an uptrend; exit at the mid band."""
    name = "bollinger_reversion"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        n, k = p.get("period", 20), p.get("k", 2.0)
        want = set()
        for sym, c in contexts.items():
            mid, _, lower = ind.bollinger(c.prices, n, k)
            if mid is None:
                continue
            if not c.held and _uptrend(c) and c.price < lower:
                want.add(sym)
            elif c.held and c.price < mid and _uptrend(c):
                want.add(sym)
        return build_decisions(contexts, want, "below lower band", "back to mid band")


class MaEnvelopeDip(Strategy):
    """Buy a dip to a lower envelope under the 50-MA; exit when it reclaims 50-MA."""
    name = "ma_envelope_dip"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        env = p.get("envelope_pct", 0.05)
        want = set()
        for sym, c in contexts.items():
            s50 = ind.sma(c.prices, 50)
            if s50 is None:
                continue
            if not c.held and _uptrend(c) and c.price < s50 * (1 - env):
                want.add(sym)
            elif c.held and c.price < s50 and _uptrend(c):
                want.add(sym)
        return build_decisions(contexts, want, "dip below envelope", "reclaimed 50-MA")


class ZscoreReversion(Strategy):
    """Buy when price z-score < -z_in (statistically stretched) in an uptrend."""
    name = "zscore_reversion"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        n, z_in, z_out = p.get("period", 20), p.get("z_enter", 1.5), p.get("z_exit", 0.0)
        want = set()
        for sym, c in contexts.items():
            z = ind.zscore(c.prices, n)
            if z is None:
                continue
            if not c.held and _uptrend(c) and z <= -z_in:
                want.add(sym)
            elif c.held and z < z_out and _uptrend(c):
                want.add(sym)
        return build_decisions(contexts, want, "low z-score", "mean-reverted")
