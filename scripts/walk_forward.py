#!/usr/bin/env python3
"""Walk-forward validation: backtest strategies on an in-sample and an
out-of-sample window, then rank by robustness (how little the Sharpe decays).

Runs on the diversified universe (where timing strategies are meaningful). Writes
reports/walkforward.json. Restores config/universe.yaml and config/strategies.yaml
to their committed state on completion.

Usage:
    python3 scripts/walk_forward.py --strategies macd,donchian,...
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, ROOT)
from strategy.experiment_log import append_experiment  # noqa: E402
STRAT = os.path.join(ROOT, "config", "strategies.yaml")
UNIV = os.path.join(ROOT, "config", "universe.yaml")
OUT = os.path.join(ROOT, "reports", "walkforward.json")

IS = ("2017-01-01", "2021-06-30")        # in-sample
OOS = ("2021-07-01", "2026-06-16")       # out-of-sample

DIVERSIFIED = """sleeves:
  core:
    - XLK
    - XLF
    - XLE
    - XLV
    - XLI
    - XLY
    - XLP
    - XLU
    - XLB
    - XLRE
    - XLC
  satellite:
    - SPY
    - QQQ
    - IWM
    - TLT
    - IEF
    - GLD
    - EEM
    - EFA
    - HYG
    - LQD
  tactical: []
"""


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def env():
    e = dict(os.environ)
    e["PATH"] = os.path.expanduser("~/Library/Python/3.9/bin") + ":" + e.get("PATH", "")
    return e


def set_universe_diversified():
    s = open(UNIV).read()
    s = re.sub(r"sleeves:\n(?:.*\n)*?(?=\n# Screener|\nscreener)", DIVERSIFIED + "\n", s, count=1)
    open(UNIV, "w").write(s)


def set_run(strategy, start, end):
    s = open(STRAT).read()
    s = re.sub(r"^active:.*$", f"active: {strategy}", s, count=1, flags=re.M)
    s = re.sub(r"^backtest_start:.*\n", "", s, flags=re.M)
    s = re.sub(r"^backtest_end:.*\n", "", s, flags=re.M)
    s = s.rstrip() + f'\nbacktest_start: "{start}"\nbacktest_end: "{end}"\n'
    open(STRAT, "w").write(s)


def latest_stats():
    fs = [p for p in glob.glob(os.path.join(ROOT, "backtests", "*", "*.json"))
          if not re.search("summary|order-events|monitor", p)]
    d = json.load(open(max(fs, key=os.path.getmtime)))
    st = d.get("statistics", {})

    def num(k):
        try:
            return float(str(st.get(k)).replace("%", "").replace("$", ""))
        except (TypeError, ValueError):
            return None
    return {"cagr": num("Compounding Annual Return"),
            "sharpe": num("Sharpe Ratio"), "dd": num("Drawdown")}


def run(strategy, window):
    set_run(strategy, *window)
    subprocess.run(["lean", "backtest", "."], cwd=ROOT, env=env(),
                   capture_output=True, text=True, timeout=900)
    return latest_stats()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", required=True)
    ap.add_argument("--universe", default="diversified",
                    help="diversified (default, ETF sleeves) | watchlist (committed production universe)")
    ap.add_argument("--split", default=None,
                    help="IS/OOS boundary YYYY-MM-DD (default 2021-06-30). Use several "
                         "values across runs to build a multi-split robustness picture.")
    args = ap.parse_args()
    names = [s.strip() for s in args.strategies.split(",") if s.strip()]

    # optional alternate split boundary (for multi-split robustness / deflated Sharpe)
    global IS, OOS
    if args.split:
        from datetime import date, timedelta
        y, m, d = map(int, args.split.split("-"))
        IS = (IS[0], args.split)
        OOS = ((date(y, m, d) + timedelta(days=1)).isoformat(), OOS[1])

    # watchlist = the committed config/universe.yaml as-is; diversified = override it.
    if args.universe == "diversified":
        set_universe_diversified()
    results = {}
    try:
        for i, name in enumerate(names, 1):
            print(f"[{i}/{len(names)}] {name}: in-sample ...", flush=True)
            ins = run(name, IS)
            print(f"    OOS ...", flush=True)
            oos = run(name, OOS)
            decay = None
            if ins["sharpe"] is not None and oos["sharpe"] is not None:
                decay = round(ins["sharpe"] - oos["sharpe"], 3)
            results[name] = {"in_sample": ins, "out_sample": oos, "sharpe_decay": decay}
            print(f"    IS Sharpe {ins['sharpe']} -> OOS {oos['sharpe']} (decay {decay})", flush=True)
            # walkforward.json kept for existing consumers, but the experiment
            # ledger (reports/experiments.jsonl) is now authoritative.
            json.dump(results, open(OUT, "w"), indent=2)
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "git_sha": git_sha(),
                "source": "walk_forward",
                "strategy": name,
                "universe": args.universe,
                "baseline": None,
                "splits": [
                    {"name": "IS", "start": IS[0], "end": IS[1],
                     "sharpe": ins["sharpe"], "cagr": ins["cagr"], "max_dd": ins["dd"]},
                    {"name": "OOS", "start": OOS[0], "end": OOS[1],
                     "sharpe": oos["sharpe"], "cagr": oos["cagr"], "max_dd": oos["dd"]},
                ],
                "decay": decay,
                "fitness": None,
                "gate": None,
            }
            append_experiment(record)
    finally:
        # restore committed configs no matter what
        subprocess.run(["git", "checkout", "--", "config/universe.yaml"], cwd=ROOT)
        s = open(STRAT).read()
        s = re.sub(r"^active:.*$", "active: trend_ma", s, count=1, flags=re.M)
        s = re.sub(r"^backtest_start:.*\n", "", s, flags=re.M)
        s = re.sub(r"^backtest_end:.*\n", "", s, flags=re.M)
        open(STRAT, "w").write(s)
        print("configs restored.")
    print(f"\nwalk-forward complete -> {OUT}")


if __name__ == "__main__":
    raise SystemExit(main())
