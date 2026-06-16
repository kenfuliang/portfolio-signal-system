"""Strategy interface (design: pluggable algorithms, one engine path).

A Strategy turns per-symbol context (prices + current holding state) into a list
of Decisions. It is pure Python — no LEAN types — so every algorithm is unit-
testable and runs identically in backtest and live. `main.py` builds the contexts,
calls the active strategy, then sizes/caps/executes the decisions through the shared
risk layer. Only the *signal* differs between strategies; risk is non-negotiable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .signals import Decision  # reused decision type (Action/Decision)


@dataclass
class SymbolContext:
    """Everything a strategy needs for one symbol on the current bar."""
    symbol: str
    prices: pd.Series                      # daily close, chronological
    held: bool                             # currently invested?
    price: float                           # latest close
    weight: float = 0.0                    # current portfolio weight
    target_weight: float = 0.0             # allowed per-name target (risk layer)
    stop: Optional[float] = None           # current stop level, if any
    fundamentals: Optional[dict] = None    # for future factor strategies
    sentiment: Optional[float] = None
    earnings_in_days: Optional[int] = None
    thesis_broken: bool = False


class Strategy:
    """Base class. Subclasses implement `generate`. `name` is the registry key."""

    name: str = "base"

    def generate(self, contexts: dict[str, "SymbolContext"], cfg) -> list[Decision]:
        raise NotImplementedError

    # convenience: per-strategy params block from config/strategies.yaml
    def params(self, cfg) -> dict:
        return (cfg.strategies or {}).get(self.name, {}) or {}
