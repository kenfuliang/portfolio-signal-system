#!/usr/bin/env python3
"""Build a broad, liquidity-ranked universe from already-ingested local data and
write it into config/universe.yaml (no network).

Picks the top-N symbols by median daily dollar volume that have history reaching
back to the requested start year — an S&P-500-style liquid proxy for dynamic
portfolio selection. SPY is always included as a benchmark reference.

The original (AI-semis) universe.yaml is git-tracked; restore it with:
    git checkout config/universe.yaml

Usage:
    python3 scripts/build_universe.py --n 500 --start-year 2017
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, "data", "equity", "usa", "daily")
UNIV = os.path.join(ROOT, "config", "universe.yaml")


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return 0.0
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def symbol_liquidity(zip_path: str, start_year: int):
    """Return (median_dollar_volume, n_rows, first_year) or None on failure.

    CSV rows: YYYYMMDD 00:00, O, H, L, C(x10000), Volume. Dollar volume = C/10000 * V.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            name = zf.namelist()[0]
            raw = zf.read(name).decode()
    except Exception:
        return None
    dvs = []
    first_year = None
    rows = 0
    for line in raw.splitlines():
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            yr = int(parts[0][:4])
            close = int(parts[4]) / 10000.0
            vol = int(parts[5])
        except ValueError:
            continue
        if first_year is None:
            first_year = yr
        rows += 1
        dvs.append(close * vol)
    if first_year is None or first_year > start_year:
        return None
    return median(dvs), rows, first_year


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--start-year", type=int, default=2017)
    ap.add_argument("--min-rows", type=int, default=500)
    args = ap.parse_args()

    ranked = []
    files = glob.glob(os.path.join(DAILY, "*.zip"))
    print(f"scanning {len(files)} symbols for liquidity ...", flush=True)
    for p in files:
        sym = os.path.splitext(os.path.basename(p))[0]
        if "." in sym:                       # skip class-share dotted tickers
            continue
        res = symbol_liquidity(p, args.start_year)
        if res is None:
            continue
        mdv, rows, _ = res
        if rows < args.min_rows:
            continue
        ranked.append((sym.upper(), mdv))

    ranked.sort(key=lambda x: x[1], reverse=True)
    picked = [s for s, _ in ranked[: args.n]]
    if "SPY" not in picked:
        picked.append("SPY")
    picked = sorted(set(picked))
    print(f"qualified {len(ranked)} symbols; selected top {len(picked)} by dollar volume")

    lines = [
        "# Broad liquidity-ranked universe (build_universe.py) — dynamic selection.",
        f"# Top ~{args.n} US names by median dollar volume with history from <= {args.start_year}.",
        "# Restore the AI-semis universe with: git checkout config/universe.yaml",
        "",
        "mode: watchlist",
        "",
        "sleeves:",
        "  core:",
    ]
    # quote tickers so YAML never coerces names like ON/NO/TRUE to booleans
    lines += [f'    - "{s}"' for s in picked]
    lines += [
        "  satellite: []",
        "  tactical: []",
        "",
        "screener:",
        '  sector: "Technology"',
        '  industry: "Semiconductors"',
        "  market_cap_min: 1000000000",
        "  min_avg_volume: 500000",
        "  actively_trading: true",
        "",
    ]
    with open(UNIV, "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {len(picked)} symbols to {UNIV}")


if __name__ == "__main__":
    raise SystemExit(main())
