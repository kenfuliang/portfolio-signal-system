"""Trend / momentum family (6 algorithms)."""
from __future__ import annotations

from .. import indicators as ind
from ..base import Strategy, SymbolContext
from ..signals import Decision
from ._common import build_decisions, rank_top


class TrendMA(Strategy):
    """Baseline: hold names trading above both their 50- and 200-day MA."""
    name = "trend_ma"

    def generate(self, contexts: dict[str, SymbolContext], cfg) -> list[Decision]:
        want = set()
        for sym, c in contexts.items():
            s50, s200 = ind.sma(c.prices, 50), ind.sma(c.prices, 200)
            if s50 and s200 and c.price > s50 and c.price > s200:
                want.add(sym)
        return build_decisions(contexts, want, "above 50/200 MA", "lost trend")


class GoldenCross(Strategy):
    """Hold while 50-day MA is above 200-day MA (golden cross regime)."""
    name = "golden_cross"

    def generate(self, contexts, cfg):
        want = set()
        for sym, c in contexts.items():
            s50, s200 = ind.sma(c.prices, 50), ind.sma(c.prices, 200)
            if s50 and s200 and s50 > s200:
                want.add(sym)
        return build_decisions(contexts, want, "golden cross", "death cross")


class Momentum12_1(Strategy):
    """Hold the top-N names by classic 12-1 month momentum (positive only)."""
    name = "momentum_12_1"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        top_n = p.get("top_n", 5)
        scores = {s: ind.momentum_12_1(c.prices) for s, c in contexts.items()}
        scores = {s: v for s, v in scores.items() if v is not None and v > 0}
        want = rank_top(scores, top_n)
        return build_decisions(contexts, want, "top 12-1 momentum", "momentum decayed")


class RocMomentum(Strategy):
    """Hold the top-N names by 6-month rate-of-change."""
    name = "roc_momentum"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        top_n, lb = p.get("top_n", 5), p.get("lookback", 126)
        scores = {s: ind.roc(c.prices, lb) for s, c in contexts.items()}
        scores = {s: v for s, v in scores.items() if v is not None and v > 0}
        want = rank_top(scores, top_n)
        return build_decisions(contexts, want, "top ROC", "ROC decayed")


class Macd(Strategy):
    """Hold while the MACD line is above its signal line."""
    name = "macd"

    def generate(self, contexts, cfg):
        want = set()
        for sym, c in contexts.items():
            m, s, _ = ind.macd(c.prices)
            if m is not None and s is not None and m > s:
                want.add(sym)
        return build_decisions(contexts, want, "MACD>signal", "MACD<signal")


class AdxTrend(Strategy):
    """Hold names in a strong uptrend: ADX above threshold and price > 200-MA."""
    name = "adx_trend"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        thr = p.get("adx_min", 25)
        want = set()
        for sym, c in contexts.items():
            a, s200 = ind.adx(c.prices), ind.sma(c.prices, 200)
            if a is not None and s200 and a >= thr and c.price > s200:
                want.add(sym)
        return build_decisions(contexts, want, "strong ADX uptrend", "trend weakened")
