"""Shared helpers for the strategy zoo.

Every strategy decides *which names to hold long*; the shared risk layer
(`risk.position_size` / `enforce_caps`) does the sizing. So the tournament compares
selection signals under identical risk-based sizing — a fair, apples-to-apples test.
"""
from __future__ import annotations

from ..base import SymbolContext
from ..signals import Action, Decision


def stop_hit(ctx: SymbolContext) -> bool:
    return ctx.held and ctx.stop is not None and ctx.price <= ctx.stop


def build_decisions(
    contexts: dict[str, SymbolContext],
    want_held: set[str],
    reason: str = "signal",
    sell_reason: str = "exit signal",
) -> list[Decision]:
    """Turn a desired holding set into BUY/SELL/HOLD decisions.

    Stop-loss always fires first for held names (risk discipline is shared).
    """
    out: list[Decision] = []
    for sym, ctx in contexts.items():
        if stop_hit(ctx):
            out.append(Decision(sym, Action.SELL, "stop-loss hit", 0.0))
            continue
        if sym in want_held:
            out.append(Decision(sym, Action.HOLD if ctx.held else Action.BUY, reason, 0.0))
        elif ctx.held:
            out.append(Decision(sym, Action.SELL, sell_reason, 0.0))
    return out


def rank_top(scores: dict[str, float], n: int, ascending: bool = False) -> set[str]:
    """Top-n symbols by score (lowest-n if ascending)."""
    items = [(s, v) for s, v in scores.items() if v is not None]
    items.sort(key=lambda x: x[1], reverse=not ascending)
    return {s for s, _ in items[:n]}
