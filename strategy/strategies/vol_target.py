"""Volatility-targeted momentum (research-driven enhancement of the baseline).

Same selection signal as `momentum_12_1` (top-N by positive 12-1 momentum), but
overlaid with the two most robustly-evidenced risk overlays from the literature:

  1. Trend regime gate (Faber 200-day / dual-momentum): only deploy risk while a
     market proxy is above its long-term moving average; otherwise step fully to
     cash. Cuts the deep equity-style drawdowns.
  2. Time-series volatility targeting (Barroso & Santa-Clara; Daniel & Moskowitz):
     scale *gross exposure* by target_vol / recent_realized_vol of the proxy. When
     the regime gets volatile, hold fewer names; when calm, hold the full top-N.

Because strategies only *select* names (the shared ATR risk layer sizes them),
"exposure scaling" is implemented as scaling the *number of names held*: fewer
names ⇒ less gross exposure. This keeps the one-engine-path contract and stays
price-only, so it runs in the current degraded (price-only) mode.

Compare against `momentum_12_1` in the tournament to test the overlay in isolation
— identical base signal, identical risk layer, only the regime/vol overlay differs.
"""
from __future__ import annotations

from .. import indicators as ind
from ..base import Strategy, SymbolContext
from ..signals import Decision
from ._common import build_decisions, rank_top


class VolTargetMomentum(Strategy):
    """12-1 momentum with a trend-regime gate and time-series vol targeting."""
    name = "vol_target_momentum"

    def _proxy_prices(self, contexts, preferred):
        """Pick the market-regime proxy: first preferred symbol present, else the
        longest-history name available (a reasonable broad-market stand-in)."""
        for sym in preferred:
            if sym in contexts and len(contexts[sym].prices) >= 200:
                return contexts[sym].prices
        usable = [c.prices for c in contexts.values() if len(c.prices) >= 200]
        return max(usable, key=len) if usable else None

    def generate(self, contexts: dict[str, SymbolContext], cfg) -> list[Decision]:
        p = self.params(cfg)
        top_n = p.get("top_n", 20)
        target_vol = p.get("target_vol", 0.30)     # annualized exposure target
        vol_window = p.get("vol_window", 20)        # realized-vol lookback (days)
        ma_window = p.get("regime_ma", 200)         # trend-gate MA length
        preferred = p.get("benchmark", ["QQQ", "VTI", "SMH", "SOXX"])

        proxy = self._proxy_prices(contexts, preferred)

        # --- 1. Trend regime gate: proxy must be above its long-term MA ---
        if proxy is not None:
            ma = ind.sma(proxy, ma_window)
            if ma is not None and float(proxy.iloc[-1]) < ma:
                return build_decisions(contexts, set(), "risk-off (below trend)",
                                       "regime risk-off")

        # --- 2. Volatility targeting: scale name count by target/realized vol ---
        n_hold = top_n
        if proxy is not None:
            rv = ind.realized_vol(proxy, vol_window)
            if rv and rv > 0:
                scale = min(1.0, target_vol / rv)   # de-risk only; never lever up
                n_hold = max(0, round(top_n * scale))

        # --- 3. Base signal: top-N by positive 12-1 momentum (== baseline) ---
        scores = {s: ind.momentum_12_1(c.prices) for s, c in contexts.items()}
        scores = {s: v for s, v in scores.items() if v is not None and v > 0}
        want = rank_top(scores, n_hold)
        return build_decisions(contexts, want, "vol-targeted momentum",
                               "trimmed (vol target)")
