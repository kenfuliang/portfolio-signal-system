#!/usr/bin/env python3
"""CLI over the pure experiment ledger (`strategy/experiment_log.py`).

Subcommands (argparse):
  --append '<json>'   parse a JSON record (or '-' for stdin) and append it; print run_id.
  --query             print ledger rows matching --strategy [--universe].
  --check             find_matches-based de-dup guard; exit 1 if an exact match exists.
  --leaderboard       regenerate reports/leaderboard.md from the ledger.
  --backfill          one-time idempotent migration of clean legacy result files.

This is a THIN adapter: ledger I/O lives only in strategy/experiment_log.py and is
reused here, never reimplemented (golden rule: one source of truth for the ledger).
Core logic (build_leaderboard_md, backfill_records, coerce_pct) is importable for tests.

Design: docs/superpowers/specs/2026-06-16-experiment-memory-design.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Any, Optional

# Make `strategy` importable when run as a script.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from strategy.experiment_log import (  # noqa: E402
    DEFAULT_PATH,
    append_experiment,
    best_per_group,
    find_matches,
    load_experiments,
    make_run_id,
    oos_split,
)

REPORTS_DIR = os.path.join(_REPO, "reports")
LEADERBOARD_PATH = os.path.join(REPORTS_DIR, "leaderboard.md")

# Backtest window used by the harnesses (main.py default: 2017-01-01 -> today).
_FULL_START = "2017-01-01"
_FULL_END = "2026-06-16"
# Walk-forward harness IS/OOS boundary (matches the schema example in the spec).
_IS_START, _IS_END = "2017-01-01", "2021-06-30"
_OOS_START, _OOS_END = "2021-07-01", "2026-06-16"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def coerce_pct(value: Any) -> Optional[float]:
    """Coerce a metric to float. '15.657%' -> 15.657; '' / None -> None.

    Tournament stats store numbers as strings, some with a trailing '%'. This
    strips the percent sign and parses; non-numeric / missing values become None
    so downstream rendering can leave the cell blank rather than crash.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        return float(s)
    except ValueError:
        return None


def _mtime_iso(path: str) -> str:
    """Stable ISO timestamp from a file's mtime (deterministic, never now())."""
    return (
        datetime.datetime.utcfromtimestamp(os.path.getmtime(path))
        .isoformat()
        + "Z"
    )


def _fmt(value: Optional[float], nd: int = 3) -> str:
    return "" if value is None else f"{value:.{nd}f}"


# --------------------------------------------------------------------------- #
# Backfill (pure: takes file paths, returns records; does not append)
# --------------------------------------------------------------------------- #
def _backfill_tournament(path: str, universe: str) -> list[dict]:
    """One legacy row per strategy in a tournament_*.json file.

    Tournament has no IS/OOS split, so the metrics land in a single best-effort
    full-window split; fitness/decay/git_sha unknown -> null.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ts = _mtime_iso(path)
    rows: list[dict] = []
    for strategy, entry in data.items():
        stats = (entry or {}).get("stats") or {}
        split = {
            "name": "FULL",
            "start": _FULL_START,
            "end": _FULL_END,
            "sharpe": coerce_pct(stats.get("Sharpe Ratio")),
            "cagr": coerce_pct(stats.get("Compounding Annual Return")),
            "max_dd": coerce_pct(stats.get("Drawdown")),
            "turnover": coerce_pct(stats.get("Portfolio Turnover")),
        }
        rows.append({
            "ts": ts,
            "source": "legacy",
            "git_sha": None,
            "strategy": strategy,
            "universe": universe,
            "params": {},
            "splits": [split],
            "decay": None,
            "fitness": None,
            "notes": f"backfilled from {os.path.basename(path)}",
        })
    return rows


def _backfill_walkforward(path: str, universe: str) -> list[dict]:
    """One legacy row per strategy with IS + OOS splits and sharpe decay."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ts = _mtime_iso(path)
    rows: list[dict] = []
    for strategy, entry in data.items():
        ins = (entry or {}).get("in_sample") or {}
        oos = (entry or {}).get("out_sample") or {}
        splits = [
            {
                "name": "IS", "start": _IS_START, "end": _IS_END,
                "sharpe": coerce_pct(ins.get("sharpe")),
                "cagr": coerce_pct(ins.get("cagr")),
                "max_dd": coerce_pct(ins.get("dd")),
                "turnover": None,
            },
            {
                "name": "OOS", "start": _OOS_START, "end": _OOS_END,
                "sharpe": coerce_pct(oos.get("sharpe")),
                "cagr": coerce_pct(oos.get("cagr")),
                "max_dd": coerce_pct(oos.get("dd")),
                "turnover": None,
            },
        ]
        rows.append({
            "ts": ts,
            "source": "legacy",
            "git_sha": None,
            "strategy": strategy,
            "universe": universe,
            "params": {},
            "splits": splits,
            "decay": coerce_pct(entry.get("sharpe_decay")),
            "fitness": None,
            "notes": f"backfilled from {os.path.basename(path)}",
        })
    return rows


def _backfill_baselines(path: str) -> list[dict]:
    """The three buy-and-hold baseline reference rows (SPY/QQQ/TQQQ)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ts = _mtime_iso(path)
    rows: list[dict] = []
    for symbol in ("SPY", "QQQ", "TQQQ"):
        entry = data.get(symbol)
        if not entry:
            continue
        split = {
            "name": "FULL",
            "start": _FULL_START,
            "end": _FULL_END,
            "sharpe": coerce_pct(entry.get("sharpe")),
            "cagr": coerce_pct(entry.get("cagr")),
            "max_dd": coerce_pct(entry.get("maxdd")),
            "turnover": None,
        }
        rows.append({
            "ts": ts,
            "source": "legacy",
            "git_sha": None,
            "strategy": f"baseline_{symbol}",
            "universe": "baseline",
            "params": {},
            "splits": [split],
            "decay": None,
            "fitness": None,
            "notes": entry.get("role") or "buy-and-hold baseline",
        })
    return rows


# filename -> (parser, universe). Ambiguous tournament.json is intentionally absent.
def _legacy_specs(reports_dir: str) -> list[tuple[str, Any]]:
    return [
        (os.path.join(reports_dir, "tournament_diversified.json"),
         lambda p: _backfill_tournament(p, "diversified")),
        (os.path.join(reports_dir, "tournament_aisemis.json"),
         lambda p: _backfill_tournament(p, "aisemis")),
        (os.path.join(reports_dir, "tournament_broad.json"),
         lambda p: _backfill_tournament(p, "broad")),
        (os.path.join(reports_dir, "walkforward.json"),
         lambda p: _backfill_walkforward(p, "diversified")),
        (os.path.join(reports_dir, "baselines.json"),
         _backfill_baselines),
    ]


def backfill_records(files: list[tuple[str, Any]]) -> list[dict]:
    """Build all legacy records from (path, parser) specs. Missing files skipped."""
    out: list[dict] = []
    for path, parser in files:
        if not os.path.exists(path):
            continue
        out.extend(parser(path))
    return out


def run_backfill(reports_dir: str = REPORTS_DIR, path: str = DEFAULT_PATH) -> int:
    """Append legacy records not already present (idempotent via deterministic run_id)."""
    existing = {r.get("run_id") for r in load_experiments(path)}
    records = backfill_records(_legacy_specs(reports_dir))
    appended = 0
    for rec in records:
        rid = make_run_id(rec["ts"], rec["strategy"], rec)
        if rid in existing:
            continue
        append_experiment(rec, path=path)
        existing.add(rid)
        appended += 1
    return appended


# --------------------------------------------------------------------------- #
# Leaderboard
# --------------------------------------------------------------------------- #
def _load_baseline_refs(reports_dir: str) -> list[dict]:
    """Baseline reference rows from baselines.json (if present)."""
    path = os.path.join(reports_dir, "baselines.json")
    if not os.path.exists(path):
        return []
    return _backfill_baselines(path)


def build_leaderboard_md(rows: list[dict], baselines: Optional[list[dict]] = None) -> str:
    """Render the leaderboard markdown from ledger rows (pure).

    Best run per (strategy x universe) via best_per_group, ranked by fitness then
    lower decay; legacy (null-fitness) rows listed below scored rows. OOS metrics
    pulled via oos_split. The three buy-and-hold baselines append as reference rows.
    """
    # Exclude any baseline-universe rows from the competitive table; they are refs.
    scored_rows = [r for r in rows if r.get("universe") != "baseline"]
    best = best_per_group(scored_rows)
    entries = list(best.values())

    def sort_key(r: dict):
        fit = r.get("fitness")
        has_fit = fit is not None
        decay = r.get("decay")
        return (
            0 if has_fit else 1,            # scored rows first
            -(fit if has_fit else 0.0),     # higher fitness first
            (decay if decay is not None else float("inf")),  # lower decay first
        )

    entries.sort(key=sort_key)

    header = (
        "| rank | strategy | universe | OOS Sharpe | OOS CAGR | OOS MaxDD | "
        "decay | fitness | run_id | git_sha |\n"
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    lines = [
        "# Leaderboard",
        "",
        "Derived view over `reports/experiments.jsonl` — regenerated by "
        "`scripts/experiments.py --leaderboard`. Do not hand-edit.",
        "",
        "Best run per strategy x universe, ranked by fitness then lower decay. "
        "Legacy rows (no fitness) listed below scored rows.",
        "",
        header,
    ]
    for i, r in enumerate(entries, 1):
        oos = oos_split(r) or {}
        lines.append(
            f"| {i} | {r.get('strategy','')} | {r.get('universe','')} | "
            f"{_fmt(coerce_pct(oos.get('sharpe')))} | "
            f"{_fmt(coerce_pct(oos.get('cagr')))} | "
            f"{_fmt(coerce_pct(oos.get('max_dd')))} | "
            f"{_fmt(r.get('decay'))} | {_fmt(r.get('fitness'))} | "
            f"{r.get('run_id','')} | {r.get('git_sha') or ''} |"
        )

    if baselines:
        lines += ["", "## Baselines (buy-and-hold reference)", "",
                  "| symbol | Sharpe | CAGR | MaxDD |", "|---|---|---|---|"]
        for b in baselines:
            s = (oos_split(b) or {})
            sym = b.get("strategy", "").replace("baseline_", "")
            lines.append(
                f"| {sym} | {_fmt(coerce_pct(s.get('sharpe')))} | "
                f"{_fmt(coerce_pct(s.get('cagr')))} | "
                f"{_fmt(coerce_pct(s.get('max_dd')))} |"
            )

    return "\n".join(lines) + "\n"


def run_leaderboard(path: str = DEFAULT_PATH, out_path: str = LEADERBOARD_PATH) -> str:
    rows = load_experiments(path)
    baselines = _load_baseline_refs(REPORTS_DIR)
    # If the ledger already holds baseline rows, prefer those.
    ledger_bl = [r for r in rows if r.get("universe") == "baseline"]
    md = build_leaderboard_md(rows, ledger_bl or baselines)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return md


# --------------------------------------------------------------------------- #
# Query / check / append
# --------------------------------------------------------------------------- #
def run_query(strategy: str, universe: Optional[str], as_json: bool,
              path: str = DEFAULT_PATH) -> list[dict]:
    rows = [
        r for r in load_experiments(path)
        if r.get("strategy") == strategy
        and (universe is None or r.get("universe") == universe)
    ]
    if as_json:
        for r in rows:
            print(json.dumps(r, separators=(",", ":")))
    else:
        print(f"{'universe':<14} {'source':<12} {'decay':>8} {'fitness':>8}  run_id")
        for r in rows:
            print(f"{r.get('universe',''):<14} {r.get('source',''):<12} "
                  f"{_fmt(r.get('decay')):>8} {_fmt(r.get('fitness')):>8}  "
                  f"{r.get('run_id','')}")
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--append", metavar="JSON",
                   help="append a JSON record ('-' reads stdin); prints run_id")
    p.add_argument("--query", action="store_true", help="print matching ledger rows")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if an exact (strategy,params,universe,splits) match exists")
    p.add_argument("--leaderboard", action="store_true",
                   help="regenerate reports/leaderboard.md")
    p.add_argument("--backfill", action="store_true",
                   help="one-time idempotent migration of legacy result files")
    p.add_argument("--strategy")
    p.add_argument("--universe")
    p.add_argument("--params", help="JSON params dict (for --check)")
    p.add_argument("--splits", help="JSON splits list (for --check)")
    p.add_argument("--json", action="store_true", help="--query: emit json lines")
    args = p.parse_args(argv)

    if args.append is not None:
        raw = sys.stdin.read() if args.append == "-" else args.append
        record = json.loads(raw)
        print(append_experiment(record))
        return 0

    if args.backfill:
        n = run_backfill()
        print(f"backfill: appended {n} new legacy row(s) to {DEFAULT_PATH}")
        return 0

    if args.leaderboard:
        run_leaderboard()
        print(f"leaderboard: wrote {LEADERBOARD_PATH}")
        return 0

    if args.query:
        if not args.strategy:
            p.error("--query requires --strategy")
        run_query(args.strategy, args.universe, args.json)
        return 0

    if args.check:
        if not args.strategy:
            p.error("--check requires --strategy")
        params = json.loads(args.params) if args.params else {}
        splits = json.loads(args.splits) if args.splits else []
        matches = find_matches(args.strategy, params, args.universe or "", splits)
        exact = matches["exact"]
        if exact:
            print(f"EXACT MATCH ({len(exact)}): already tried — skip.")
            for r in exact:
                print(f"  {r.get('run_id','')}  fitness={_fmt(r.get('fitness'))}")
            return 1
        print("no exact match — safe to run.")
        return 0

    p.error("no subcommand given (use --append/--query/--check/--leaderboard/--backfill)")


if __name__ == "__main__":
    raise SystemExit(main())
