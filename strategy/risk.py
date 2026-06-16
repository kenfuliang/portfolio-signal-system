"""Position sizing, diversification caps, stops, and the portfolio circuit
breaker (design doc §5). Pure functions — testable without an engine."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SizingResult:
    symbol: str
    target_weight: float      # fraction of equity
    shares_value: float       # dollar value to hold
    stop_price: float
    note: str = ""


def position_size(
    equity: float,
    price: float,
    atr: float,
    sleeve: str,
    risk_cfg: dict,
    is_leveraged: bool = False,
) -> SizingResult:
    """Risk-based sizing: dollars at risk = equity * risk_per_trade, with the
    stop set at N*ATR below entry. Size is capped by max_position_pct."""
    s = risk_cfg["sizing"]
    atr_mult = (
        risk_cfg["leveraged"]["tighter_stop_atr_multiple"]
        if is_leveraged
        else s["atr_stop_multiple"]
    )
    stop_distance = atr_mult * atr
    stop_price = max(price - stop_distance, 0.01)

    dollars_at_risk = equity * s["risk_per_trade_pct"]
    if stop_distance <= 0:
        return SizingResult(symbol="", target_weight=0.0, shares_value=0.0,
                            stop_price=stop_price, note="invalid ATR")

    value = dollars_at_risk / stop_distance * price          # risk-based notional
    max_value = equity * s["max_position_pct"]
    note = ""
    if value > max_value:
        value, note = max_value, "capped at max_position_pct"

    return SizingResult(
        symbol="", target_weight=value / equity, shares_value=value,
        stop_price=stop_price, note=note,
    )


def enforce_caps(
    targets: dict[str, float],
    sleeve_of: dict[str, str],
    sector_of: dict[str, str],
    risk_cfg: dict,
) -> tuple[dict[str, float], list[str]]:
    """Scale targets down so per-name, per-sector, sleeve, and leveraged caps all
    hold. Returns (adjusted_targets, list_of_violations_fixed)."""
    div = risk_cfg["diversification"]
    sleeves = risk_cfg["sleeves"]
    lev_cap = risk_cfg["leveraged"]["portfolio_cap_pct"]
    lev_syms = set(risk_cfg["leveraged"]["symbols"])
    notes: list[str] = []
    adj = dict(targets)

    # per-name cap
    for sym, w in adj.items():
        if w > div["max_per_name_pct"]:
            adj[sym] = div["max_per_name_pct"]; notes.append(f"{sym}: name cap")

    # per-sector cap — skipped when max_per_sector_pct is null/0 (no real sector
    # data: a synthetic per-name=sector mapping must not masquerade as a limit).
    sector_cap = div.get("max_per_sector_pct")
    by_sector: dict[str, float] = {}
    for sym, w in adj.items():
        by_sector.setdefault(sector_of.get(sym, "?"), 0.0)
        by_sector[sector_of.get(sym, "?")] += w
    for sector, total in (by_sector.items() if sector_cap else []):
        if total > sector_cap and total > 0:
            scale = sector_cap / total
            for sym in adj:
                if sector_of.get(sym) == sector:
                    adj[sym] *= scale
            notes.append(f"{sector}: sector cap")

    # sleeve caps (esp. tactical / leveraged)
    by_sleeve: dict[str, float] = {}
    for sym, w in adj.items():
        sl = sleeve_of.get(sym, "satellite")
        by_sleeve[sl] = by_sleeve.get(sl, 0.0) + w
    for sl, total in by_sleeve.items():
        cap = sleeves.get(sl, {}).get("max", 1.0)
        if total > cap and total > 0:
            scale = cap / total
            for sym in adj:
                if sleeve_of.get(sym) == sl:
                    adj[sym] *= scale
            notes.append(f"{sl} sleeve cap")

    # leveraged combined cap
    lev_total = sum(w for sym, w in adj.items() if sym in lev_syms)
    if lev_total > lev_cap and lev_total > 0:
        scale = lev_cap / lev_total
        for sym in adj:
            if sym in lev_syms:
                adj[sym] *= scale
        notes.append("leveraged cap")

    return adj, notes


def circuit_breaker_tripped(equity: float, peak_equity: float, risk_cfg: dict) -> bool:
    cb = risk_cfg["circuit_breaker"]
    if peak_equity <= 0:
        return False
    drawdown = 1.0 - equity / peak_equity
    return drawdown >= cb["max_drawdown_pct"]
