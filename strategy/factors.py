"""Factor scoring (design doc §4).

Pure functions over price/fundamental/sentiment inputs so they are unit-testable
without LEAN. Each factor returns a raw score; `composite_scores` ranks names
into per-universe percentiles and blends them by configured weight.

Honesty about data tiers: only `trend` needs price (always available). quality,
valuation, sentiment need fundamentals/Bigdata; when those inputs are missing the
factor is skipped and its weight is redistributed, with a degraded-mode flag set.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class FactorInputs:
    """Per-symbol inputs. Fields may be None when a data tier isn't connected."""
    prices: pd.Series                      # daily close, chronological (>= 252 rows ideal)
    fundamentals: Optional[dict] = None    # margins, roic, rev_growth, debt_equity, pe, ev_ebitda, peg
    sentiment: Optional[float] = None      # Bigdata sentiment score, normalized [-1, 1]


# --- individual factor raw scores (higher = better) ---

def trend_score(prices: pd.Series) -> Optional[float]:
    if prices is None or len(prices) < 200:
        return None
    px = float(prices.iloc[-1])
    sma50 = float(prices.tail(50).mean())
    sma200 = float(prices.tail(200).mean())
    # 12-1 momentum: return from ~12mo ago to ~1mo ago (skip most recent month)
    if len(prices) >= 252:
        mom = float(prices.iloc[-21] / prices.iloc[-252] - 1.0)
    else:
        mom = float(prices.iloc[-1] / prices.iloc[0] - 1.0)
    hi_52w = float(prices.tail(252).max()) if len(prices) >= 252 else float(prices.max())
    dist_from_high = px / hi_52w - 1.0   # closer to 0 (near highs) is stronger
    # blend the trend sub-signals into one raw number
    above_50 = (px / sma50 - 1.0)
    above_200 = (px / sma200 - 1.0)
    return 0.4 * mom + 0.25 * above_200 + 0.2 * above_50 + 0.15 * dist_from_high


def quality_score(f: Optional[dict]) -> Optional[float]:
    if not f:
        return None
    return (
        0.30 * f.get("operating_margin", 0.0)
        + 0.30 * f.get("roic", 0.0)
        + 0.25 * f.get("rev_growth", 0.0)
        - 0.15 * f.get("debt_equity", 0.0)
    )


def valuation_score(f: Optional[dict]) -> Optional[float]:
    if not f:
        return None
    # cheaper = better -> negate the multiples
    pe = f.get("pe")
    ev_ebitda = f.get("ev_ebitda")
    peg = f.get("peg")
    parts, weights = [], []
    if pe and pe > 0:
        parts.append(-pe); weights.append(0.4)
    if ev_ebitda and ev_ebitda > 0:
        parts.append(-ev_ebitda); weights.append(0.35)
    if peg and peg > 0:
        parts.append(-peg); weights.append(0.25)
    if not parts:
        return None
    return float(np.average(parts, weights=weights))


def sentiment_score(s: Optional[float]) -> Optional[float]:
    return None if s is None else float(s)


_FACTOR_FNS = {
    "trend": lambda i: trend_score(i.prices),
    "quality": lambda i: quality_score(i.fundamentals),
    "valuation": lambda i: valuation_score(i.fundamentals),
    "sentiment": lambda i: sentiment_score(i.sentiment),
}


def _percentile_rank(values: pd.Series) -> pd.Series:
    """Map raw scores to [0,1] percentiles within the universe."""
    return values.rank(pct=True)


def composite_scores(
    inputs: dict[str, FactorInputs],
    weights: dict[str, float],
) -> tuple[pd.Series, list[str]]:
    """Return (composite_score_per_symbol in [0,1], list_of_active_factors).

    Factors with no data for *any* symbol are dropped and their weight is
    redistributed proportionally across the remaining factors (degraded mode).
    """
    raw: dict[str, dict[str, float]] = {fac: {} for fac in weights}
    for sym, inp in inputs.items():
        for fac in weights:
            val = _FACTOR_FNS[fac](inp)
            if val is not None:
                raw[fac][sym] = val

    active = [fac for fac in weights if raw[fac]]
    if not active:
        raise ValueError("no factor produced any score — check data inputs")

    # redistribute weight across active factors
    w_active = {fac: weights[fac] for fac in active}
    total = sum(w_active.values())
    w_active = {fac: w / total for fac, w in w_active.items()}

    symbols = list(inputs.keys())
    composite = pd.Series(0.0, index=symbols)
    for fac in active:
        s = pd.Series(raw[fac]).reindex(symbols)
        pct = _percentile_rank(s)
        composite = composite.add(pct.fillna(pct.median()) * w_active[fac], fill_value=0.0)

    return composite.sort_values(ascending=False), active
