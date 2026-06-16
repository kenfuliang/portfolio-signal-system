#!/usr/bin/env python3
"""Measure clean buy-and-hold baselines (SPY/QQQ/TQQQ) THROUGH LEAN, so they are
directly comparable to strategy backtests (same engine, same Sharpe formula).

Each baseline runs as a single-name universe, fully invested (equal_weight sizing,
diversification caps OFF, stop-loss OFF), monthly. Writes reports/baselines.json.

Restores config/universe.yaml, config/risk.yaml, config/strategies.yaml to their
committed state on exit.

Usage:  python3 scripts/benchmark.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIV = os.path.join(ROOT, "config", "universe.yaml")
STRAT = os.path.join(ROOT, "config", "strategies.yaml")
OUT = os.path.join(ROOT, "reports", "baselines.json")

ROLES = {"SPY": "market baseline", "QQQ": "growth/tech baseline", "TQQQ": "aggressive baseline"}


def env():
    e = dict(os.environ)
    e["PATH"] = os.path.expanduser("~/Library/Python/3.9/bin") + ":" + e.get("PATH", "")
    return e


def set_universe(ticker: str):
    open(UNIV, "w").write(
        'mode: watchlist\n\nsleeves:\n  core:\n    - "%s"\n  satellite: []\n  tactical: []\n\n'
        'screener:\n  sector: "Technology"\n  industry: "Semiconductors"\n'
        "  market_cap_min: 1000000000\n  min_avg_volume: 500000\n  actively_trading: true\n" % ticker
    )


def set_benchmark_mode():
    s = open(STRAT).read()
    s = re.sub(r"^active:.*$", "active: equal_weight_hold", s, count=1, flags=re.M)
    s = re.sub(r"^rebalance:.*$", "rebalance: monthly", s, count=1, flags=re.M)
    for key in ("sizing", "enforce_caps", "use_stops"):
        s = re.sub(rf"^{key}:.*\n", "", s, flags=re.M)
    s = s.rstrip() + "\nsizing: equal_weight\nenforce_caps: false\nuse_stops: false\n"
    open(STRAT, "w").write(s)


def latest_stats():
    fs = [p for p in glob.glob(os.path.join(ROOT, "backtests", "*", "*.json"))
          if not re.search("summary|order-events|monitor", p)]
    st = json.load(open(max(fs, key=os.path.getmtime))).get("statistics", {})

    def num(k):
        try:
            return round(float(str(st.get(k)).replace("%", "").replace("$", "")), 3)
        except (TypeError, ValueError):
            return None
    return {"cagr": num("Compounding Annual Return"), "sharpe": num("Sharpe Ratio"),
            "maxdd": num("Drawdown"), "net_profit": num("Net Profit")}


def main():
    baselines = {"_note": "Buy-and-hold baselines measured THROUGH LEAN (caps off, "
                          "stops off, fully invested, monthly, 2017->). Directly "
                          "comparable to strategy backtests."}
    set_benchmark_mode()
    try:
        for tkr in ("SPY", "QQQ", "TQQQ"):
            print(f"benchmarking {tkr} ...", flush=True)
            set_universe(tkr)
            subprocess.run(["lean", "backtest", "."], cwd=ROOT, env=env(),
                           capture_output=True, text=True, timeout=900)
            s = latest_stats()
            s["role"] = ROLES[tkr]
            baselines[tkr] = s
            print(f"  {tkr}: CAGR {s['cagr']} | Sharpe {s['sharpe']} | MaxDD {s['maxdd']}", flush=True)
            json.dump(baselines, open(OUT, "w"), indent=2)
    finally:
        subprocess.run(["git", "checkout", "--", "config/universe.yaml"], cwd=ROOT)
        s = open(STRAT).read()
        s = re.sub(r"^active:.*$", "active: trend_ma", s, count=1, flags=re.M)
        s = re.sub(r"^rebalance:.*$", "rebalance: daily", s, count=1, flags=re.M)
        for key in ("sizing", "enforce_caps", "use_stops"):
            s = re.sub(rf"^{key}:.*\n", "", s, flags=re.M)
        open(STRAT, "w").write(s)
        print("configs restored.")
    print(f"\nbaselines -> {OUT}")


if __name__ == "__main__":
    raise SystemExit(main())
