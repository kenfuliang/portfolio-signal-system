#!/usr/bin/env python3
"""Backtest every registered strategy on the same universe and collect stats.

For each strategy: rewrite config/strategies.yaml `active:`, run `lean backtest .`,
parse the result statistics, and generate a LEAN HTML report into reports/. Writes
reports/tournament.json (machine-readable) and reports/index.md (human index).

Usage:
    python3 scripts/run_tournament.py                 # all 20
    python3 scripts/run_tournament.py --only trend_ma,rsi_reversion
    python3 scripts/run_tournament.py --no-report      # skip HTML (faster)
Resumable: pass --resume to skip strategies already in tournament.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRAT_YAML = os.path.join(ROOT, "config", "strategies.yaml")
REPORTS = os.path.join(ROOT, "reports")
RESULTS_JSON = os.path.join(REPORTS, "tournament.json")

sys.path.insert(0, ROOT)
from strategy.registry import ALL_STRATEGIES  # noqa: E402
from strategy.experiment_log import append_experiment  # noqa: E402

from datetime import datetime, timezone


def num(x):
    try:
        return float(str(x).replace("%", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def active_universe() -> str:
    """Infer the universe name; default 'watchlist'."""
    try:
        text = open(STRAT_YAML).read()
        m = re.search(r"^universe:\s*(\S+)", text, flags=re.M)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return "watchlist"


def backtest_window():
    """Read backtest start/end from strategies.yaml; (None, None) if absent."""
    try:
        text = open(STRAT_YAML).read()
        s = re.search(r'^backtest_start:\s*"?([\d-]+)"?', text, flags=re.M)
        e = re.search(r'^backtest_end:\s*"?([\d-]+)"?', text, flags=re.M)
        return (s.group(1) if s else None, e.group(1) if e else None)
    except Exception:  # noqa: BLE001
        return (None, None)

WANT_STATS = [
    "Compounding Annual Return", "Net Profit", "Sharpe Ratio", "Sortino Ratio",
    "Drawdown", "Win Rate", "Loss Rate", "Profit-Loss Ratio", "Total Orders",
    "Portfolio Turnover", "Probabilistic Sharpe Ratio",
]


def set_active(name: str) -> None:
    with open(STRAT_YAML) as f:
        text = f.read()
    text = re.sub(r"^active:.*$", f"active: {name}", text, count=1, flags=re.M)
    with open(STRAT_YAML, "w") as f:
        f.write(text)


def latest_results_json() -> str | None:
    files = [p for p in glob.glob(os.path.join(ROOT, "backtests", "*", "*.json"))
             if not re.search(r"(summary|order-events|monitor)", p)]
    return max(files, key=os.path.getmtime) if files else None


def parse_stats(results_path: str) -> dict:
    d = json.load(open(results_path))
    stats = d.get("statistics") or d.get("Statistics") or {}
    # fall back to the sibling -summary.json
    if not stats:
        sib = results_path.replace(".json", "-summary.json")
        if os.path.exists(sib):
            sd = json.load(open(sib))
            stats = sd.get("statistics", sd)
    return {k: stats.get(k) for k in WANT_STATS}


def run_backtest() -> str | None:
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/Library/Python/3.9/bin") + ":" + env.get("PATH", "")
    proc = subprocess.run(
        ["lean", "backtest", "."], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=900,
    )
    if "Successfully ran" not in proc.stdout:
        # surface a short tail of the error
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-8:])
        print(f"    backtest did not report success:\n    {tail}")
    return latest_results_json()


def gen_report(name: str, results_path: str) -> str | None:
    os.makedirs(REPORTS, exist_ok=True)
    out = os.path.join(REPORTS, f"{name}.html")
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/Library/Python/3.9/bin") + ":" + env.get("PATH", "")
    proc = subprocess.run(
        ["lean", "report", "--backtest-results", results_path,
         "--report-destination", out, "--overwrite",
         "--strategy-name", f"Strategy: {name}"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )
    return out if os.path.exists(out) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=str, default=None, help="comma-separated subset")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    names = [s.strip() for s in args.only.split(",")] if args.only else list(ALL_STRATEGIES)

    os.makedirs(REPORTS, exist_ok=True)
    results = {}
    if args.resume and os.path.exists(RESULTS_JSON):
        results = json.load(open(RESULTS_JSON))

    for i, name in enumerate(names, 1):
        if args.resume and name in results and "error" not in results[name]:
            print(f"[{i}/{len(names)}] {name}: cached, skip")
            continue
        print(f"[{i}/{len(names)}] {name}: backtesting ...", flush=True)
        t0 = time.time()
        set_active(name)
        try:
            rj = run_backtest()
            if not rj:
                results[name] = {"error": "no results json"}
            else:
                stats = parse_stats(rj)
                report = None if args.no_report else gen_report(name, rj)
                results[name] = {"stats": stats, "results_json": rj, "report": report}
                cagr = stats.get("Compounding Annual Return")
                sharpe = stats.get("Sharpe Ratio")
                dd = stats.get("Drawdown")
                print(f"    done in {time.time()-t0:.0f}s | CAGR {cagr} | "
                      f"Sharpe {sharpe} | MaxDD {dd}", flush=True)
                # tournament.json kept for existing consumers; the experiment
                # ledger (reports/experiments.jsonl) is now authoritative.
                start, end = backtest_window()
                append_experiment({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "git_sha": git_sha(),
                    "source": "tournament",
                    "strategy": name,
                    "universe": active_universe(),
                    "splits": [{
                        "name": "FULL", "start": start, "end": end,
                        "sharpe": num(sharpe), "cagr": num(cagr), "max_dd": num(dd),
                    }],
                    "fitness": None,
                })
        except Exception as e:  # noqa: BLE001
            results[name] = {"error": str(e)}
            print(f"    ERROR: {e}", flush=True)
        json.dump(results, open(RESULTS_JSON, "w"), indent=2)

    # restore the committed default
    set_active("trend_ma")
    write_index(results)
    print(f"\nTournament complete. {RESULTS_JSON}")
    return 0


def write_index(results: dict) -> None:
    rows = []
    for name, r in results.items():
        if "stats" not in r:
            continue
        s = r["stats"]
        rows.append((name, s, r.get("report")))

    def num(x):
        try:
            return float(str(x).replace("%", "").replace("$", ""))
        except (TypeError, ValueError):
            return float("-inf")

    rows.sort(key=lambda x: num(x[1].get("Sharpe Ratio")), reverse=True)
    lines = ["# Strategy tournament — reports index", "",
             "Ranked by Sharpe ratio. Same universe, same risk layer, 2017→present.", "",
             "| Rank | Strategy | CAGR | Net Profit | Sharpe | MaxDD | Win% | Orders | Report |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, (name, s, report) in enumerate(rows, 1):
        rp = f"[{name}.html]({name}.html)" if report else "—"
        lines.append(
            f"| {i} | {name} | {s.get('Compounding Annual Return')} | "
            f"{s.get('Net Profit')} | {s.get('Sharpe Ratio')} | {s.get('Drawdown')} | "
            f"{s.get('Win Rate')} | {s.get('Total Orders')} | {rp} |"
        )
    with open(os.path.join(REPORTS, "index.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
