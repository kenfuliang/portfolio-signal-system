"""Allocation / rotation family + benchmark (6 algorithms).

Note: all strategies select *which* names to hold; the shared risk layer sizes
them. Because `risk.position_size` already scales inversely with volatility (ATR),
holding a basket approximates risk-parity weighting automatically — so the
allocation strategies differ mainly in *selection*, not bespoke weighting.
"""
from __future__ import annotations

from .. import indicators as ind
from ..base import Strategy, SymbolContext
from ..signals import Decision
from ._common import build_decisions, rank_top


class DualMomentum(Strategy):
    """Absolute + relative momentum: hold top-N by 12-1 momentum, but only names
    with positive absolute momentum (else stay in cash)."""
    name = "dual_momentum"

    def generate(self, contexts: dict[str, SymbolContext], cfg) -> list[Decision]:
        p = self.params(cfg)
        top_n = p.get("top_n", 4)
        mom = {s: ind.momentum_12_1(c.prices) for s, c in contexts.items()}
        positive = {s: v for s, v in mom.items() if v is not None and v > 0}
        want = rank_top(positive, top_n)
        return build_decisions(contexts, want, "dual momentum", "neg/low momentum")


class SectorRotation(Strategy):
    """Rotate among the CORE ETFs only: hold the top-N by 6-month ROC."""
    name = "sector_rotation"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        top_n, lb = p.get("top_n", 2), p.get("lookback", 126)
        core = {s for s in contexts if (cfg.sleeve_of(s) == "core")}
        scores = {s: ind.roc(contexts[s].prices, lb) for s in core}
        scores = {s: v for s, v in scores.items() if v is not None and v > 0}
        want = rank_top(scores, top_n)
        # only act on core names; ignore non-core (leave to no position)
        sub = {s: c for s, c in contexts.items() if s in core}
        return build_decisions(sub, want, "top sector ETF", "rotated out")


class LowVolatility(Strategy):
    """Hold the N lowest-volatility names that are in an uptrend."""
    name = "low_volatility"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        top_n, n = p.get("top_n", 5), p.get("vol_window", 60)
        scores = {}
        for s, c in contexts.items():
            s200 = ind.sma(c.prices, 200)
            v = ind.realized_vol(c.prices, n)
            if v is not None and s200 and c.price > s200:
                scores[s] = v
        want = rank_top(scores, top_n, ascending=True)   # lowest vol
        return build_decisions(contexts, want, "low volatility", "exited low-vol set")


class RiskParity(Strategy):
    """Hold the whole investable universe; the ATR-based sizer assigns inverse-vol
    weights, approximating a risk-parity book."""
    name = "risk_parity"

    def generate(self, contexts, cfg):
        want = {s for s, c in contexts.items() if len(c.prices) >= 200}
        return build_decisions(contexts, want, "risk-parity basket", "insufficient history")


class RelativeStrength(Strategy):
    """Hold names whose 6-month ROC beats the universe median (top-half RS)."""
    name = "relative_strength"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        lb = p.get("lookback", 126)
        rocs = {s: ind.roc(c.prices, lb) for s, c in contexts.items()}
        vals = [v for v in rocs.values() if v is not None]
        if not vals:
            return build_decisions(contexts, set(), "rs", "rs")
        med = sorted(vals)[len(vals) // 2]
        want = {s for s, v in rocs.items() if v is not None and v > med}
        return build_decisions(contexts, want, "above-median RS", "below-median RS")


class VolAdjustedMomentum(Strategy):
    """Risk-adjusted momentum: hold the top-N names by (6-month ROC / realized
    volatility), restricted to names in a long-term uptrend. Favors steady
    winners over volatile spikes — a Sharpe-style take on momentum."""
    name = "vol_adjusted_momentum"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        top_n, lb, vw = p.get("top_n", 5), p.get("lookback", 126), p.get("vol_window", 60)
        scores = {}
        for s, c in contexts.items():
            r = ind.roc(c.prices, lb)
            v = ind.realized_vol(c.prices, vw)
            s200 = ind.sma(c.prices, 200)
            if r is not None and v and v > 0 and s200 and c.price > s200 and r > 0:
                scores[s] = r / v
        want = rank_top(scores, top_n)
        return build_decisions(contexts, want, "top risk-adj momentum", "decayed/risky")


_HAVEN = {"TLT", "IEF", "GLD", "LQD"}   # defensive assets for risk-off rotation


class ChampionTrendHaven(Strategy):
    """Hybrid of the tournament's diversified winners: hold trending equity ETFs
    (MACD line above signal AND price above 200-MA); separately hold defensive
    assets (bonds/gold) whenever THEY are trending up. When equities break down
    they're sold and capital rotates to whichever havens are rising — an automatic
    risk-off switch layered on a MACD trend engine."""
    name = "champion_trend_haven"

    def generate(self, contexts, cfg):
        want = set()
        for s, c in contexts.items():
            s200 = ind.sma(c.prices, 200)
            if s in _HAVEN:
                if s200 and c.price > s200:        # hold havens only while rising
                    want.add(s)
                continue
            m, sig, _ = ind.macd(c.prices)
            if m is not None and sig is not None and s200 and m > sig and c.price > s200:
                want.add(s)
        return build_decisions(contexts, want, "trend-on / haven rotation", "risk-off")


class AsymmetricTrend(Strategy):
    """Asymmetric hysteresis overlay to cut whipsaw (GEM/200-MA strategies missed
    the 2019 & 2020 V-recoveries by rotating out on every dip). Stay in growth
    (QQQ>SPY) until price falls a confirmed `band` BELOW its 200-MA, then rotate to
    a rising safe asset; re-enter as soon as price reclaims the 200-MA. The gap
    between exit (200MA - band) and entry (200MA) is the hysteresis that avoids
    flip-flopping around the average."""
    name = "asymmetric_trend"
    GROWTH = ["QQQ", "SPY"]
    SAFE = ["IEF", "TLT"]

    def generate(self, contexts, cfg):
        band = self.params(cfg).get("breakdown_band", 0.05)
        want, risk_on = set(), False
        for g in self.GROWTH:
            c = contexts.get(g)
            if c is None:
                continue
            s200 = ind.sma(c.prices, 200)
            if s200 is None:
                continue
            keep = c.price > s200 * (1 - band) if c.held else c.price > s200
            if keep:
                want.add(g)
                risk_on = True
                break
        if not risk_on:
            for s in self.SAFE:
                c = contexts.get(s)
                if c is None:
                    continue
                s200 = ind.sma(c.prices, 200)
                if s200 and c.price > s200:
                    want.add(s)
                    break
        return build_decisions(contexts, want, "growth (hysteresis) / safe", "confirmed breakdown")


class RiskManagedGrowth(Strategy):
    """Exposure-management (not selection): hold a growth index (QQQ, else SPY)
    while it's above its 200-day MA; when it breaks down, rotate to a rising safe
    asset (IEF/TLT) or cash. A Faber-style timing overlay aimed at capturing most
    of the growth index's return while cutting its drawdown — the lever our
    selection strategies never pulled. (Needs a growth+bonds universe to be
    meaningful; per-name sizing cap currently limits full exposure — see notes.)"""
    name = "risk_managed_growth"
    GROWTH = ["QQQ", "SPY"]
    SAFE = ["IEF", "TLT"]

    def generate(self, contexts, cfg):
        want = set()
        risk_on = False
        for g in self.GROWTH:
            c = contexts.get(g)
            if c is None:
                continue
            s200 = ind.sma(c.prices, 200)
            if s200 and c.price > s200:
                want.add(g)
                risk_on = True
                break                      # hold the top-preference growth only
        if not risk_on:                    # risk-off: rotate to a rising safe asset
            for s in self.SAFE:
                c = contexts.get(s)
                if c is None:
                    continue
                s200 = ind.sma(c.prices, 200)
                if s200 and c.price > s200:
                    want.add(s)
                    break
        return build_decisions(contexts, want, "risk-on growth / safe rotation", "rotate out")


class MomentumRunner(Strategy):
    """Let winners run: hold the top-N by 12-1 momentum, but once a name is held,
    keep it while it stays above its 200-day MA — no rank-decay selling, no churn.
    Fills empty slots with the highest-momentum names in an uptrend. Designed to
    capture buy-and-hold's compounding while exiting only on a real trend break."""
    name = "momentum_runner"

    def generate(self, contexts, cfg):
        p = self.params(cfg)
        max_pos = p.get("max_positions", 8)
        want = set()
        # 1. keep every held name that's still in its uptrend (let it compound)
        for s, c in contexts.items():
            s200 = ind.sma(c.prices, 200)
            if c.held and s200 and c.price > s200:
                want.add(s)
        # 2. fill remaining slots with top-momentum uptrending names
        slots = max_pos - len(want)
        if slots > 0:
            cand = {}
            for s, c in contexts.items():
                if s in want:
                    continue
                m, s200 = ind.momentum_12_1(c.prices), ind.sma(c.prices, 200)
                if m is not None and m > 0 and s200 and c.price > s200:
                    cand[s] = m
            want |= rank_top(cand, slots)
        return build_decisions(contexts, want, "momentum (let it run)", "trend broke")


class TrendFilteredHold(Strategy):
    """Buy-and-hold with a trend overlay: hold each name while it trades above its
    200-day MA, step to cash when it drops below. Aims to keep most of buy-and-hold's
    upside while cutting its drawdown (the gap the tournament exposed)."""
    name = "trend_filtered_hold"

    def generate(self, contexts, cfg):
        want = set()
        for s, c in contexts.items():
            s200 = ind.sma(c.prices, 200)
            if s200 and c.price > s200:
                want.add(s)
        return build_decisions(contexts, want, "above 200-MA (hold)", "below 200-MA (cash)")


class EqualWeightHold(Strategy):
    """Benchmark: hold every universe name continuously (buy once, never rotate)."""
    name = "equal_weight_hold"

    def generate(self, contexts, cfg):
        want = {s for s, c in contexts.items() if len(c.prices) >= 200}
        return build_decisions(contexts, want, "buy & hold", "n/a")
