"""Load and validate YAML config. Keeps tunables out of code (design principle:
rules before discretion, everything auditable)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def _load(name: str) -> dict[str, Any]:
    path = os.path.join(CONFIG_DIR, name)
    with open(path, "r") as f:
        return yaml.safe_load(f)


@dataclass
class Config:
    universe: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    factors: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls(
            universe=_load("universe.yaml"),
            risk=_load("risk.yaml"),
            factors=_load("factors.yaml"),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        w = self.factors.get("weights", {})
        total = sum(w.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"factor weights must sum to 1.0, got {total}")
        sl = self.risk.get("sleeves", {})
        for name in ("core", "satellite", "tactical"):
            if name not in sl:
                raise ValueError(f"risk.yaml missing sleeve '{name}'")

    # --- convenience accessors ---
    def all_symbols(self) -> list[str]:
        out: list[str] = []
        for syms in self.universe.get("sleeves", {}).values():
            out.extend(syms)
        return out

    def sleeve_of(self, symbol: str) -> str | None:
        for sleeve, syms in self.universe.get("sleeves", {}).items():
            if symbol in syms:
                return sleeve
        return None
