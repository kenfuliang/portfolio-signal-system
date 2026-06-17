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


def symbol_liquidity(zip_path: str, start_year: int, asof_window=None):
    """Return (median_dollar_volume, n_rows, first_year) or None on failure.

    CSV rows: YYYYMMDD 00:00, O, H, L, C(x10000), Volume. Dollar volume = C/10000 * V.

    asof_window: optional (lo_yyyymmdd, hi_yyyymmdd) ints. When given, liquidity is
    measured ONLY over rows in [lo, hi] — the trailing window observable AT the backtest
    start — so selection uses no future data (point-in-time, removes selection
    look-ahead). The symbol must have its first bar on/before `lo` (it must already
    exist at the window start) and enough rows inside the window.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            name = zf.namelist()[0]
            raw = zf.read(name).decode()
    except Exception:
        return None
    dvs = []
    first_year = None
    first_ymd = None
    rows = 0
    for line in raw.splitlines():
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            ymd = int(parts[0][:8])
            yr = int(parts[0][:4])
            close = int(parts[4]) / 10000.0
            vol = int(parts[5])
        except ValueError:
            continue
        if first_year is None:
            first_year = yr
            first_ymd = ymd
        if asof_window is not None:
            lo, hi = asof_window
            if ymd < lo or ymd > hi:
                continue          # point-in-time: ignore data outside the trailing window
        rows += 1
        dvs.append(close * vol)
    if first_year is None:
        return None
    if asof_window is not None:
        _, hi = asof_window
        # must already exist BEFORE the as-of date (no IPO-after-start look-ahead).
        # We don't require existence at window start — local history may begin
        # mid-window — only that liquidity is measured with no future data.
        if first_ymd is None or first_ymd >= hi:
            return None
    elif first_year > start_year:
        return None
    return median(dvs), rows, first_year


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--start-year", type=int, default=2017)
    ap.add_argument("--min-rows", type=int, default=500)
    ap.add_argument("--asof", type=str, default=None,
                    help="YYYY-MM-DD: point-in-time selection — rank liquidity using ONLY "
                         "the trailing year before this date (removes selection look-ahead). "
                         "Without it, liquidity is ranked over the full history (look-ahead).")
    ap.add_argument("--asof-lookback-days", type=int, default=365,
                    help="calendar-days trailing window for --asof liquidity (default 365)")
    args = ap.parse_args()

    asof_window = None
    min_rows = args.min_rows
    if args.asof:
        y, m, d = map(int, args.asof.split("-"))
        hi = y * 10000 + m * 100 + d
        # trailing calendar window ending the day before asof (no same-day/future data)
        from datetime import date, timedelta
        lo_date = date(y, m, d) - timedelta(days=args.asof_lookback_days)
        lo = lo_date.year * 10000 + lo_date.month * 100 + lo_date.day
        asof_window = (lo, hi)
        # require enough in-window bars to rank liquidity; kept modest because local
        # history may cover only part of the trailing window (data starts mid-2016).
        min_rows = max(60, int(args.asof_lookback_days * 252 / 365 * 0.4))
        print(f"POINT-IN-TIME selection: ranking liquidity over [{lo}..{hi}] only "
              f"(>= {min_rows} bars in window).", flush=True)

    ranked = []
    files = glob.glob(os.path.join(DAILY, "*.zip"))
    print(f"scanning {len(files)} symbols for liquidity ...", flush=True)
    for p in files:
        sym = os.path.splitext(os.path.basename(p))[0]
        if "." in sym:                       # skip class-share dotted tickers
            continue
        res = symbol_liquidity(p, args.start_year, asof_window=asof_window)
        if res is None:
            continue
        mdv, rows, _ = res
        if rows < min_rows:
            continue
        ranked.append((sym.upper(), mdv))

    ranked.sort(key=lambda x: x[1], reverse=True)
    picked = [s for s, _ in ranked[: args.n]]
    if "SPY" not in picked:
        picked.append("SPY")
    picked = sorted(set(picked))
    print(f"qualified {len(ranked)} symbols; selected top {len(picked)} by dollar volume")

    pit = f"point-in-time as of {args.asof}" if args.asof else "FULL-HISTORY (has selection look-ahead)"
    lines = [
        "# Broad liquidity-ranked universe (build_universe.py) — dynamic selection.",
        f"# Top ~{args.n} US names by median dollar volume; ranking: {pit}.",
        "# SURVIVORSHIP CAVEAT: built from currently-ingested (yfinance) names only, so",
        "#   names DELISTED before today are absent (coverage survivorship remains).",
        f"#   --asof removes SELECTION look-ahead but NOT coverage survivorship — research-grade.",
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
