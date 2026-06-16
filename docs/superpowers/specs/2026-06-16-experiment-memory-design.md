# Spec: Experiment Memory — durable, queryable record of experiments

**Date:** 2026-06-16
**Status:** Approved (design), pending implementation plan
**Topic:** Turn prior experiments into durable memory that improves future
algorithm development and feeds the `/evolve-strategy` loop.

## Problem

Experiment results are stored in fragmented, overwriting files:

- `reports/tournament*.json` — overwritten each run; the `_diversified` / `_aisemis`
  / `_broad` variants exist only because files were hand-renamed to avoid clobbering.
- `reports/walkforward.json` — overwritten; a 24-strategy walk-forward was lost this
  way when a 2-strategy run clobbered it.
- `reports/*.html` — heavy, not queryable.
- `docs/strategy-study.md` — prose findings, not joined to the numbers.

Consequences: no history, no run metadata (universe / date range / git sha / config),
no link between a result and the hypothesis that produced it. The `/evolve-strategy`
skill assumes a queryable memory that does not yet exist.

## Goals

Foundation (this spec):

- **A. Negative-result memory** — answer "has this been tried?" before spending a
  backtest, so the loop never silently repeats work.
- **B. Trustworthy leaderboard** — always know the current best strategy per universe,
  with full provenance, so baselines/promotions are picked from solid data. Structurally
  eliminate the clobbering bug.

Deferred (future specs, build on the foundation):

- C. Surface patterns that suggest the next hypothesis.
- D. Track a strategy's trajectory (OOS Sharpe / decay) over iterations.

## Non-goals

- No database server, no web UI, no analytics dashboards.
- No semantic-search index. Prose-hypothesis similarity is an advisory nudge the
  caller eyeballs, not an enforced gate or an ML system.
- No change to how backtests themselves run (LEAN, `walk_forward.py` internals).

## Architecture

File-based, pure-Python. Four components, each one job:

```
strategy/experiment_log.py   PURE core (no LEAN). Only writer/reader of the ledger.
reports/experiments.jsonl    SOURCE OF TRUTH. Append-only, one JSON row per run. Git-tracked.
reports/leaderboard.md       DERIVED VIEW. Pure function over the ledger; regenerated, never edited.
scripts/experiments.py       CLI: --append, --leaderboard, --query, --check, --backfill.
```

- `experiments.jsonl` is **appended, never rewritten** — this structurally kills the
  clobbering bug (foundation B's root cause).
- `leaderboard.md` is a rollup; deleting it loses nothing. Source of truth stays singular.
- `experiment_log.py` is the testable heart — pure dict/JSONL ops. Everything else calls it.

### Component interfaces

`strategy/experiment_log.py` (pure):

- `append_experiment(record: dict, path=DEFAULT) -> str` — validates required fields,
  computes `run_id`, appends one line, returns `run_id`. Never rewrites existing lines.
- `load_experiments(path=DEFAULT) -> list[dict]` — read all rows (tolerates a missing
  file → `[]`; skips malformed lines with a logged warning).
- `find_matches(strategy, params, universe, splits, path=DEFAULT) -> dict` — returns
  `{"exact": [...], "same_strategy_universe": [...]}`.
- `make_run_id(ts, strategy, record) -> str` — `ts + strategy + 4-char content hash`.
  Deterministic (no `random`/wall-clock beyond the passed `ts`), so backfill is idempotent.

`scripts/experiments.py` (thin CLI over the core; may touch files/argv, not LEAN):

- `--append <json>` — append a row (used by harnesses).
- `--leaderboard` — regenerate `reports/leaderboard.md`.
- `--query --strategy X [--universe Y]` — print matching rows.
- `--check --strategy X --params '{...}' --universe Y` — exit non-zero if an exact
  match exists (the de-dup guard, scriptable).
- `--backfill` — one-time idempotent migration of legacy files.

## Record schema (one JSONL row)

```json
{
  "run_id": "2026-06-16T16:48:03Z-vol_target_momentum-7a3c",
  "ts": "2026-06-16T16:48:03Z",
  "git_sha": "65d61c3",
  "source": "walk_forward",
  "mode": "hypothesis",
  "strategy": "vol_target_momentum",
  "baseline": "momentum_12_1",
  "universe": "diversified",
  "params": {"target_vol": 0.30, "regime_ma": 200, "vol_window": 20, "top_n": 20},
  "splits": [
    {"name": "IS",  "start": "2017-01-01", "end": "2021-06-30", "sharpe": -0.285, "cagr": -0.16, "max_dd": 15.1, "turnover": 0.04},
    {"name": "OOS", "start": "2021-07-01", "end": "2026-06-16", "sharpe": 0.321,  "cagr": 10.5,  "max_dd": 18.7, "turnover": 0.05}
  ],
  "decay": -0.606,
  "fitness": 0.93,
  "gate": "satellite",
  "hypothesis": "200d regime gate + vol targeting lifts OOS Sharpe without added decay",
  "notes": "diversified only; needs watchlist re-run"
}
```

Field rules:

- **Required:** `run_id`, `ts`, `source`, `strategy`, `universe`, `splits`. Others optional.
- `source` ∈ `walk_forward | tournament | evolve-strategy | legacy`.
- `mode` ∈ `hypothesis | tune | null`. `gate` ∈ `reject | tactical | satellite | core | null`.
- `universe` ∈ `watchlist | diversified | aisemis | broad` (string; not enumerated-enforced
  so new universes don't break appends).
- Legacy rows: fill what's knowable, set `source:"legacy"`, `git_sha:null`, `fitness:null`,
  and a single-split or best-effort `splits` entry.
- `run_id` content hash is over `(strategy, params, universe, split-dates)` so identical
  configs collide deterministically — backfill and accidental re-append are idempotent.

## De-dup logic (foundation A)

`find_matches` classifies prior runs:

- **exact** — same `(strategy, params, universe, split-dates)`. The **enforced guard**:
  `/evolve-strategy` and `experiments.py --check` must not silently re-run these.
- **same_strategy_universe** — all prior runs of that strategy×universe. The **default
  report** (param landscape; valuable for `--mode tune`).
- The caller additionally eyeballs prose `hypothesis` for a soft "looks similar to run
  X — proceed?" nudge. Advisory only, never a silent gate.

## Leaderboard view (foundation B)

`experiments.py --leaderboard` regenerates `reports/leaderboard.md`:

- Best run per `strategy × universe`, ranked by `fitness` (tie-break: lower `decay`).
- Columns: rank, strategy, universe, OOS Sharpe, OOS CAGR, OOS MaxDD, decay, fitness,
  run_id, git_sha.
- Includes the three buy-and-hold baselines (SPY/QQQ/TQQQ) as reference rows.
- Rows with `fitness:null` (legacy) rank below scored rows, shown for reference.
- Pure function over the ledger; idempotent; never hand-edited.

## Backfill (decision C — clean legacy only)

`experiments.py --backfill` (one-time, idempotent):

- Parse `tournament_diversified.json` (→ universe `diversified`),
  `tournament_aisemis.json` (→ `aisemis`), `tournament_broad.json` (→ `broad`),
  `walkforward.json` (→ universe from its diversified harness), `baselines.json`
  (→ the three baseline reference rows).
- **Skip** ambiguous `tournament.json` (unknown universe).
- Set `source:"legacy"`, infer universe from filename, fill known metrics, leave
  unknown metadata null.
- Idempotent: deterministic `run_id` means re-running appends nothing new.

## Integration points

- `scripts/walk_forward.py` — at the end of a run, build a record and call
  `append_experiment` instead of overwriting `walkforward.json`. (Keep writing the
  JSON too during a transition if desired, but the ledger is authoritative.)
- `scripts/run_tournament.py` — append one row per strategy backtested.
- `.claude/skills/evolve-strategy/SKILL.md` — step "Read first" calls `find_matches`
  (the guard + param landscape); final "Record honestly" step appends the result row
  and points `strategy-study.md` entries at the new `run_id`.

## Error handling

- Missing ledger file → treated as empty (`[]`), not an error.
- Malformed JSONL line → skipped with a logged warning; never aborts a read.
- Append is the only mutation; no in-place edits, so a crash mid-write at worst leaves
  one trailing partial line (tolerated by the malformed-line skip).
- `--check` exits non-zero on an exact match so callers can branch in shell.

## Testing (per docs/rules/testing.md — pure, no LEAN/Docker)

`tests/test_experiment_log.py`:

1. append → load round-trip preserves the record.
2. **Clobber regression:** appending a second row leaves the first row intact (the bug
   that lost the 24-strategy walk-forward).
3. `find_matches` returns exact for identical config; same_strategy_universe ignores params.
4. `make_run_id` is deterministic for identical `(strategy, params, universe, splits)`.
5. Leaderboard picks the highest-fitness run per strategy×universe; legacy (null fitness)
   ranks below scored rows.
6. Backfill is idempotent (run twice → same row count).
7. Malformed line is skipped, not fatal.

## Open questions / future work (out of scope here)

- C: pattern-mining over the ledger to propose hypotheses.
- D: per-strategy trajectory plots/queries across iterations.
- Whether to gitignore `experiments.jsonl` or track it. Default: **track it** — it is
  the memory; it must travel with the repo. (Heavy HTML stays gitignored as today.)
