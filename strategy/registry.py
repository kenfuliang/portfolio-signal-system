"""Strategy registry — map config names to Strategy instances."""
from __future__ import annotations

from .base import Strategy
from .strategies import STRATEGY_CLASSES

_INSTANCES: dict[str, Strategy] = {cls.name: cls() for cls in STRATEGY_CLASSES}

ALL_STRATEGIES: list[str] = list(_INSTANCES.keys())


def get_strategy(name: str) -> Strategy:
    try:
        return _INSTANCES[name]
    except KeyError:
        raise ValueError(
            f"unknown strategy '{name}'. Available: {', '.join(ALL_STRATEGIES)}"
        )
