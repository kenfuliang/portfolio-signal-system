"""Experiment memory — an append-only ledger of backtest/walk-forward runs.

Pure Python (no LEAN, no engine) so it is fast and unit-testable. This is the ONLY
writer/reader of `reports/experiments.jsonl`, the durable source of truth that
replaces the fragmented, overwriting result files. A derived leaderboard view and
the CLI live in `scripts/experiments.py`; the harnesses and the /evolve-strategy
skill call the functions here.

Design: docs/superpowers/specs/2026-06-16-experiment-memory-design.md

Foundation goals:
  A. Negative-result memory — `find_matches` answers "has this been tried?" so the
     loop never silently repeats a backtest.
  B. Trustworthy leaderboard — every row carries full provenance (git sha, universe,
     split dates, params) and rows are APPENDED, never rewritten (kills the clobber
     bug that lost a 24-strategy walk-forward).
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

# Source of truth. Tracked in git (it is the memory; it travels with the repo).
DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reports", "experiments.jsonl",
)

REQUIRED_FIELDS = ("ts", "source", "strategy", "universe", "splits")
VALID_SOURCES = {"walk_forward", "tournament", "evolve-strategy", "legacy"}


def make_run_id(ts: str, strategy: str, record: dict) -> str:
    """Deterministic run id: ``<ts>-<strategy>-<4-char content hash>``.

    The hash is over the experiment's IDENTITY — (strategy, params, universe,
    split date boundaries) — NOT over metrics or notes. So two runs of the same
    config collide on the hash tail, which is what makes backfill and accidental
    re-append idempotent (callers can de-dupe on run_id). No randomness / wall
    clock is used beyond the supplied ``ts`` (keeps it reproducible).
    """
    ident = _identity_key(
        strategy,
        record.get("params") or {},
        record.get("universe") or "",
        record.get("splits") or [],
    )
    tail = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:4]
    return f"{ts}-{strategy}-{tail}"


def _identity_key(strategy: str, params: dict, universe: str, splits: list) -> str:
    """Canonical string for the run's identity (order-stable, metrics-free)."""
    params_canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    # only the date boundaries identify a split; metrics are deliberately excluded
    spans = sorted(
        (str(s.get("name", "")), str(s.get("start", "")), str(s.get("end", "")))
        for s in splits
    )
    return json.dumps([strategy, universe, params_canon, spans],
                      sort_keys=True, separators=(",", ":"))


def append_experiment(record: dict, path: str = DEFAULT_PATH) -> str:
    """Validate, stamp a run_id, and APPEND one row. Returns the run_id.

    Never rewrites existing rows — the only mutation is a single appended line.
    Raises ValueError if a required field is missing or `source` is unknown.
    """
    missing = [f for f in REQUIRED_FIELDS if not record.get(f)]
    if missing:
        raise ValueError(f"experiment record missing required fields: {missing}")
    if record["source"] not in VALID_SOURCES:
        raise ValueError(
            f"unknown source {record['source']!r}; expected one of {sorted(VALID_SOURCES)}"
        )

    row = dict(record)
    row.setdefault("run_id", make_run_id(row["ts"], row["strategy"], row))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row["run_id"]


def load_experiments(path: str = DEFAULT_PATH) -> list[dict]:
    """Read all rows. Missing file -> []. Malformed lines are skipped, not fatal.

    Tolerating a trailing partial line means a crash mid-append costs at most that
    one row, never the whole ledger.
    """
    if not os.path.exists(path):
        return []
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # skip corrupt/partial line; keep going
                print(f"experiment_log: skipping malformed line {i} in {path}")
    return rows


def find_matches(
    strategy: str,
    params: dict,
    universe: str,
    splits: list,
    path: str = DEFAULT_PATH,
) -> dict[str, list[dict]]:
    """Classify prior runs for the de-dup guard (foundation A).

    Returns:
      - "exact": rows with the SAME (strategy, params, universe, split dates).
        The enforced guard — callers must not silently re-run these.
      - "same_strategy_universe": all prior rows of this strategy x universe.
        The default report (the param landscape; useful for --mode tune).

    Prose-hypothesis similarity is intentionally NOT computed here; it is an
    advisory nudge the caller eyeballs, never a silent gate.
    """
    want_ident = _identity_key(strategy, params or {}, universe or "", splits or [])
    exact: list[dict] = []
    same: list[dict] = []
    for row in load_experiments(path):
        if row.get("strategy") != strategy or row.get("universe") != universe:
            continue
        same.append(row)
        row_ident = _identity_key(
            row.get("strategy", ""), row.get("params") or {},
            row.get("universe", ""), row.get("splits") or [],
        )
        if row_ident == want_ident:
            exact.append(row)
    return {"exact": exact, "same_strategy_universe": same}


def oos_split(record: dict) -> Optional[dict]:
    """Return the out-of-sample split (name=='OOS', else the last split), or None."""
    splits = record.get("splits") or []
    if not splits:
        return None
    for s in splits:
        if str(s.get("name", "")).upper() == "OOS":
            return s
    return splits[-1]


def best_per_group(
    rows: list[dict],
) -> dict[tuple[str, str], dict]:
    """Best row per (strategy, universe), ranked by fitness then lower decay.

    Rows with fitness == None (legacy) rank below any scored row. Used by the
    leaderboard view; kept here (pure) so it is unit-testable without the CLI.
    """
    def sort_key(r: dict):
        fit = r.get("fitness")
        has_fit = fit is not None
        decay = r.get("decay")
        # higher fitness first; among ties, lower decay first; scored beats legacy
        return (
            1 if has_fit else 0,
            fit if has_fit else float("-inf"),
            -(decay if decay is not None else float("inf")),
        )

    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r.get("strategy", ""), r.get("universe", ""))
        if key not in best or sort_key(r) > sort_key(best[key]):
            best[key] = r
    return best
