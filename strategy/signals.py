"""Turn composite scores + current holdings into buy/sell/hold decisions
(design doc §4.2, §4.3). Pure logic — no engine dependency."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Action(Enum):
    BUY = "buy"
    TRIM = "trim"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Decision:
    symbol: str
    action: Action
    reason: str
    composite: float


@dataclass
class PositionState:
    symbol: str
    held: bool
    price: float
    stop: Optional[float] = None          # current stop level
    weight: float = 0.0                   # current portfolio weight
    target_weight: float = 0.0            # allowed target from risk layer
    above_sma50: bool = False
    above_sma200: bool = False
    earnings_in_days: Optional[int] = None
    thesis_broken: bool = False           # set by fundamentals/sentiment layer


def evaluate(
    composite: pd.Series,
    states: dict[str, PositionState],
    buy_cfg: dict,
    sell_cfg: dict,
) -> list[Decision]:
    """Produce one Decision per symbol. Sell triggers are checked before buys."""
    decisions: list[Decision] = []
    n = len(composite)
    buy_cut = composite.quantile(buy_cfg["min_composite_percentile"]) if n else 1.0
    sell_pct = sell_cfg.get("rank_decay_below_percentile", 0.5)
    sell_cut = composite.quantile(sell_pct) if n else 0.0

    for sym, score in composite.items():
        st = states.get(sym)
        if st is None:
            continue

        # ---- SELL / TRIM (any trigger; stop first) ----
        if st.held:
            if sell_cfg.get("stop_loss") and st.stop is not None and st.price <= st.stop:
                decisions.append(Decision(sym, Action.SELL, "stop-loss hit", score)); continue
            if sell_cfg.get("thesis_break") and st.thesis_broken:
                decisions.append(Decision(sym, Action.SELL, "thesis break", score)); continue
            if score < sell_cut:
                decisions.append(Decision(sym, Action.SELL, f"rank decay <{sell_pct:.0%}", score)); continue
            if sell_cfg.get("risk_breach") and st.weight > st.target_weight * 1.25:
                decisions.append(Decision(sym, Action.TRIM, "over size cap", score)); continue
            decisions.append(Decision(sym, Action.HOLD, "in trend, rank intact", score)); continue

        # ---- BUY (all gates must pass) ----
        if score < buy_cut:
            continue
        if buy_cfg.get("require_above_sma200") and not st.above_sma200:
            continue
        if buy_cfg.get("require_above_sma50") and not st.above_sma50:
            continue
        blk = buy_cfg.get("block_days_before_earnings", 0)
        if st.earnings_in_days is not None and 0 <= st.earnings_in_days <= blk:
            continue
        decisions.append(Decision(sym, Action.BUY, "top-quintile + trend OK", score))

    return decisions
