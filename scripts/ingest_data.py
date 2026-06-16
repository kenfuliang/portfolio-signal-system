#!/usr/bin/env python3
"""Bulk price-history ingest: yfinance -> LEAN local daily data.

Downloads daily OHLCV for liquid US equities and writes them in the on-disk
format LEAN reads for local backtests:

    data/equity/usa/daily/{sym}.zip   (contains {sym}.csv, no header)
    data/equity/usa/map_files/{sym}.csv
    data/equity/usa/factor_files/{sym}.csv

CSV schema (no header), chronological:
    YYYYMMDD 00:00, Open, High, Low, Close, Volume
where OHLC are multiplied by 10000 and rounded to int (LEAN's deci-cent scale)
and Volume is the raw share count.

This is a research-data tool. It pulls split/dividend-adjusted prices and writes
identity factor files (1,1) so the series is continuous with no double-adjustment.
It is NOT broker-exact and is deliberately kept out of strategy/ (it touches the
network; strategy/ stays pure).

Usage:
    python3 scripts/ingest_data.py                 # full liquid universe
    python3 scripts/ingest_data.py --limit 50      # smoke test (first 50 symbols)
    python3 scripts/ingest_data.py --watchlist-only
    python3 scripts/ingest_data.py --symbols AXTI,COHR,SMH
    python3 scripts/ingest_data.py --force         # re-download existing zips
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta

import pandas as pd
import requests
import yaml

# --- paths -----------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data", "equity", "usa")
DAILY_DIR = os.path.join(DATA_DIR, "daily")
MAP_DIR = os.path.join(DATA_DIR, "map_files")
FACTOR_DIR = os.path.join(DATA_DIR, "factor_files")

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

PRICE_SCALE = 10000


# --- config ----------------------------------------------------------------
def load_cfg() -> dict:
    with open(os.path.join(CONFIG_DIR, "data.yaml")) as f:
        return yaml.safe_load(f)


def universe_symbols() -> list[str]:
    """The watchlist from config/universe.yaml (via the project's loader)."""
    sys.path.insert(0, ROOT)
    from strategy.config_loader import Config

    return Config.load().all_symbols()


# --- symbol universe -------------------------------------------------------
def fetch_all_us_symbols() -> list[str]:
    """Canonical free US listing files from Nasdaq Trader (pipe-delimited).

    nasdaqlisted: Symbol|Security Name|Market Category|Test Issue|...|ETF|...
    otherlisted:  ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|...|Test Issue|NASDAQ Symbol
    """
    symbols: set[str] = set()

    def _pull(url: str, symbol_col: str, test_col: str):
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        lines = resp.text.splitlines()
        # last line is a "File Creation Time..." footer
        rows = [ln for ln in lines if ln and not ln.startswith("File Creation")]
        header = rows[0].split("|")
        si, ti = header.index(symbol_col), header.index(test_col)
        for ln in rows[1:]:
            parts = ln.split("|")
            if len(parts) <= max(si, ti):
                continue
            if parts[ti].strip() == "Y":          # drop test issues
                continue
            sym = parts[si].strip()
            if sym:
                symbols.add(sym)

    _pull(NASDAQ_LISTED, "Symbol", "Test Issue")
    _pull(OTHER_LISTED, "ACT Symbol", "Test Issue")
    return sorted(symbols)


# --- symbol normalization --------------------------------------------------
def to_yahoo(sym: str) -> str:
    """Listing ticker -> yfinance ticker (class shares use '-')."""
    return sym.replace(".", "-").replace("$", "-").upper()


def to_lean(sym: str) -> str:
    """Listing ticker -> LEAN filename stem (lowercase, dot-form preserved)."""
    return sym.replace("$", ".").lower()


def looks_ingestible(sym: str) -> bool:
    # skip warrants/units/rights and obvious oddballs we don't want as equities
    bad_suffixes = ("W", "R", "U")  # heuristic; many class shares are fine
    if any(c in sym for c in (" ", "/")):
        return False
    return True


# --- LEAN writers ----------------------------------------------------------
def write_daily_zip(lean_sym: str, df: pd.DataFrame) -> None:
    """df indexed by date with columns Open/High/Low/Close/Volume."""
    lines = []
    for ts, row in df.iterrows():
        d = ts.strftime("%Y%m%d 00:00")
        o = int(round(row["Open"] * PRICE_SCALE))
        h = int(round(row["High"] * PRICE_SCALE))
        lo = int(round(row["Low"] * PRICE_SCALE))
        c = int(round(row["Close"] * PRICE_SCALE))
        v = int(row["Volume"])
        lines.append(f"{d},{o},{h},{lo},{c},{v}")
    csv_bytes = ("\n".join(lines) + "\n").encode()

    os.makedirs(DAILY_DIR, exist_ok=True)
    zip_path = os.path.join(DAILY_DIR, f"{lean_sym}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{lean_sym}.csv", csv_bytes)


def write_map_factor(lean_sym: str, first_date: str) -> None:
    os.makedirs(MAP_DIR, exist_ok=True)
    os.makedirs(FACTOR_DIR, exist_ok=True)
    # minimal map file: <first>,<ticker>,Q  /  20501231,<ticker>,Q
    with open(os.path.join(MAP_DIR, f"{lean_sym}.csv"), "w") as f:
        f.write(f"{first_date},{lean_sym},Q\n20501231,{lean_sym},Q\n")
    # identity factor file (adjusted prices => no further adjustment)
    with open(os.path.join(FACTOR_DIR, f"{lean_sym}.csv"), "w") as f:
        f.write(f"{first_date},1,1\n20501231,1,1\n")


# --- per-symbol frame extraction -------------------------------------------
def extract_frame(batch_df: pd.DataFrame, yahoo_sym: str, single: bool) -> pd.DataFrame | None:
    """Pull one symbol's OHLCV frame out of a (possibly multi-index) download."""
    try:
        if single:
            df = batch_df
        else:
            # group_by="ticker" => columns are a MultiIndex (ticker, field)
            df = batch_df.xs(yahoo_sym, axis=1, level=0)
    except (KeyError, IndexError):
        return None
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(col in df.columns for col in needed):
        return None
    df = df[needed].dropna()
    df = df[df["Volume"] > 0]
    if df.empty:
        return None
    return df.sort_index()


def passes_liquidity(df: pd.DataFrame, cfg: dict) -> bool:
    liq = cfg["liquidity"]
    if len(df) < liq["min_rows"]:
        return False
    median_dollar = float((df["Close"] * df["Volume"]).median())
    return median_dollar >= liq["min_median_dollar_volume"]


# --- main ------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest yfinance daily data into LEAN format.")
    ap.add_argument("--limit", type=int, default=None, help="cap number of symbols (smoke test)")
    ap.add_argument("--force", action="store_true", help="re-download symbols that already have a zip")
    ap.add_argument("--watchlist-only", action="store_true", help="only config/universe.yaml symbols")
    ap.add_argument("--symbols", type=str, default=None, help="comma-separated explicit symbol list")
    args = ap.parse_args()

    import yfinance as yf

    cfg = load_cfg()
    start = (datetime.utcnow() - timedelta(days=365 * cfg["lookback_years"] + 5)).strftime("%Y-%m-%d")
    uni = set(universe_symbols())
    always_keep = cfg["universe"].get("always_include_universe", True)

    # ---- build the symbol list ----
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.watchlist_only or cfg["universe"]["mode"] == "watchlist_only":
        symbols = sorted(uni)
    else:
        print("Fetching US listings from Nasdaq Trader ...", flush=True)
        listed = fetch_all_us_symbols()
        symbols = sorted(set(listed) | uni)
        symbols = [s for s in symbols if looks_ingestible(s)]
    if args.limit:
        # keep universe names visible in smoke tests
        head = [s for s in symbols if s in uni][: args.limit]
        rest = [s for s in symbols if s not in uni]
        symbols = (head + rest)[: args.limit]

    print(f"Universe to process: {len(symbols)} symbols "
          f"(history from {start}, batch {cfg['download']['batch_size']})", flush=True)

    dl = cfg["download"]
    bs = dl["batch_size"]
    stats = {"written": 0, "filtered": 0, "failed": 0, "skipped_existing": 0}
    processed = 0

    for i in range(0, len(symbols), bs):
        batch = symbols[i : i + bs]
        # resumability: drop already-present unless --force
        if not args.force:
            pending = [s for s in batch if not os.path.exists(os.path.join(DAILY_DIR, f"{to_lean(s)}.zip"))]
            stats["skipped_existing"] += len(batch) - len(pending)
            batch = pending
        if not batch:
            processed += bs
            continue

        ymap = {s: to_yahoo(s) for s in batch}
        tickers = list(ymap.values())

        data = None
        for attempt in range(dl["max_retries"]):
            try:
                data = yf.download(
                    tickers, start=start, interval="1d",
                    auto_adjust=cfg["adjust"], group_by="ticker",
                    threads=True, progress=False,
                )
                break
            except Exception as e:  # noqa: BLE001 - best-effort bulk pull
                if attempt == dl["max_retries"] - 1:
                    print(f"  batch failed after retries: {e}", flush=True)
                else:
                    time.sleep(2 * (attempt + 1))
        if data is None or data.empty:
            stats["failed"] += len(batch)
            processed += len(batch)
            continue

        single = len(tickers) == 1
        for listing_sym in batch:
            ysym = ymap[listing_sym]
            lean_sym = to_lean(listing_sym)
            try:
                df = extract_frame(data, ysym, single)
                if df is None:
                    stats["failed"] += 1
                    continue
                keep = (listing_sym in uni and always_keep) or passes_liquidity(df, cfg)
                if not keep:
                    stats["filtered"] += 1
                    continue
                write_daily_zip(lean_sym, df)
                write_map_factor(lean_sym, df.index[0].strftime("%Y%m%d"))
                stats["written"] += 1
            except Exception as e:  # noqa: BLE001 - never let one symbol abort the run
                stats["failed"] += 1
                if processed < 5:  # surface early errors for debugging
                    print(f"  {listing_sym}: {e}", flush=True)

        processed += len(batch)
        if processed // dl["progress_every"] != (processed - len(batch)) // dl["progress_every"]:
            print(f"  ...{processed}/{len(symbols)} processed | "
                  f"written {stats['written']}, filtered {stats['filtered']}, "
                  f"failed {stats['failed']}", flush=True)
        time.sleep(dl["sleep_between_batches_s"])

    print("\n=== ingest complete ===")
    print(f"  written (zips):    {stats['written']}")
    print(f"  filtered (illiquid): {stats['filtered']}")
    print(f"  failed/no-data:    {stats['failed']}")
    print(f"  skipped (existing): {stats['skipped_existing']}")
    # confirm universe coverage
    missing = [s for s in sorted(uni) if not os.path.exists(os.path.join(DAILY_DIR, f"{to_lean(s)}.zip"))]
    if missing:
        print(f"  WARNING: universe symbols still missing data: {missing}")
    else:
        print("  all config/universe.yaml symbols have data ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
