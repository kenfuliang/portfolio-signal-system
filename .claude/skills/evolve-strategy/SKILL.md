---
name: evolve-strategy
description: Iteratively develop a better trading algorithm for the portfolio-signal-system. One run = one disciplined loop (hypothesis → implement → unit test → multi-split walk-forward vs baseline → robustness-gated promote/reject → honest log). Use when the user wants to improve, discover, tune, or evolve a strategy. Two modes — `hypothesis` (new strategy from evidence) and `tune` (robustness-penalized param search on an existing one).
---

# evolve-strategy — disciplined, iterative algorithm development

This skill runs **one iteration** of strategy improvement and stops for review.
Run it repeatedly to build up better algorithms over time. Each run produces
exactly one validated (or rejected) candidate and an honest log entry.

The non-negotiable principle, from this project's own research and rules:
**select for out-of-sample robustness, not peak backtest Sharpe.** An iteration
that maximizes in-sample return is manufacturing overfit. The walk-forward gate —
not a pretty backtest — decides whether a candidate ships.

## Modes

Parse args for `--mode`. Default to `hypothesis` if absent.

- `--mode hypothesis` — invent ONE new strategy from evidence (default).
- `--mode tune` — robustness-penalized parameter search on an existing strategy.
  Requires `--strategy <name>`.

Other args: `--baseline <name>` (default `momentum_12_1`), `--universe <watchlist|diversified>`
(default `watchlist` — the real production universe).

## Read first (every run)

1. `docs/rules/strategy.md`, `docs/rules/experiments.md`, `docs/rules/testing.md`.
2. `docs/strategy-study.md` — **what has already been tried and rejected.** Never
   re-propose a logged failure. Build on logged learnings.
3. **Query the experiment ledger BEFORE proposing or running anything.** The
   canonical memory is `reports/experiments.jsonl` (append-only, git-tracked);
   `reports/leaderboard.md` is the current-best view per strategy×universe (this
   replaces reliance on `reports/walkforward.json`, which gets overwritten). Call
   `find_matches(strategy, params, universe, splits)` from
   `strategy/experiment_log.py` (or `python3 scripts/experiments.py --check
   --strategy X --params '{...}' --universe Y` / `--query --strategy X
   [--universe Y]`) and use the result to:
   - **(a) HARD-reject** silently re-running an exact prior config — if `--check`
     exits non-zero / `exact` is non-empty, do NOT run it again; pick a different
     config or stop.
   - **(b)** read the strategy×universe **param landscape**
     (`same_strategy_universe`, the default `--query` report) to see what's been
     swept — especially valuable in `--mode tune`.
   - **(c)** eyeball prior prose `hypothesis` text as an advisory "looks similar?"
     nudge — soft signal only, never a silent gate.
4. `reports/baselines.json` — the buy-and-hold bar to beat.
5. The baseline strategy's source so the new idea changes ONE thing vs it.

## Mode: hypothesis (build one new strategy)

1. **Form ONE hypothesis, grounded in evidence.** Draw from: prior research
   findings (residual momentum, vol targeting, regime gates — see study log),
   `docs/rules/strategy.md` ("the lever is usually sizing/exposure, not selection"),
   and gaps in the study log. State it as a falsifiable sentence:
   *"Adding X to the baseline will raise OOS Sharpe without raising IS→OOS decay,
   because <mechanism>."* If you cannot cite a reason, do not propose it.

2. **Change ONE variable vs the baseline.** Reuse the baseline's core signal;
   add only the one mechanism under test, so any result is attributable to it.
   This is the single most important rule — resist bundling improvements.

3. **Implement** per `docs/rules/strategy.md`:
   - New `Strategy` subclass in `strategy/strategies/`, pure Python, no LEAN types.
   - Reuse `strategy/indicators.py`; add new indicators there *with a test*.
   - Register in `strategy/strategies/__init__.py` (BOTH the import AND the
     `STRATEGY_CLASSES` list — a missing list entry passes unit tests but fails
     the backtest at init).
   - All tunables in `config/strategies.yaml`. No hardcoded thresholds.
   - Docstring states the thesis and its evidence.

4. **Unit test** in `tests/` (pytest): assert the *logic* (e.g. risk-off when the
   regime gate trips; exposure scales down in high vol). Run `python3 -m pytest`.
   Logic tests are necessary but NOT sufficient — they don't prove edge.

5. Go to **Validate** (shared section below).

## Mode: tune (robustness-penalized param search)

1. Identify the param space from the strategy's block in `config/strategies.yaml`
   (e.g. `target_vol`, `regime_ma`, `vol_window`, `top_n`). Keep it small (≤4 dims).
2. Search **sample-efficiently** — backtests are expensive. Prefer Bayesian
   optimization (e.g. a small `scipy`/`optuna` loop) over grid; if unavailable,
   a coarse grid of ≤12 points. The acquisition objective is the **penalized
   fitness** below, evaluated on MULTIPLE splits — never single-split IS Sharpe.
3. For each candidate param set, run the Validate section and score with the
   penalized fitness. Keep only sets that beat baseline on ALL splits.
4. Report the ranked survivors; recommend the most robust (not the highest-Sharpe).

## Validate (shared — the gate that actually decides)

Use `scripts/walk_forward.py` as the engine. Evaluate the candidate AND the
baseline on the SAME splits and the SAME universe (default the real watchlist).

- **Multi-split, not one.** Run at least the committed IS/OOS split plus one or
  two alternate boundaries (e.g. shift the split ±1 year). A single split that
  flips negative-IS → positive-OOS may be regime luck — demand consistency.
- **Compare against all three baselines** (SPY/QQQ/TQQQ from `baselines.json`)
  AND the strategy baseline. The bar is risk-adjusted (beating TQQQ = matching
  return at far less drawdown).
- **Sanity invariants** (`docs/rules/experiments.md`): check deployed capital is
  what you intended (a silent `BUY→30%` is a bug); log any caps/drops/truncation.
  A result that looks too good/bad is a measurement bug until proven otherwise.

### Penalized fitness (how to score, never raw Sharpe)

```
fitness = mean_OOS_Sharpe
          − w_decay   · max(0, IS_Sharpe − OOS_Sharpe)   # punish overfit
          − w_complex · (param_count / 10)               # punish complexity
          − w_turn    · turnover_fraction                # punish cost
hard reject if the candidate loses to baseline on ANY split.
```
Defaults: `w_decay=1.0, w_complex=0.5, w_turn=0.5`. Tune only with reason.

### Promotion gate (explore → exploit, tied to the sleeves)

A candidate graduates only by *earning* it:

- **Reject** → loses to baseline on any split, or fitness < baseline fitness.
- **Tactical (explore, ≤10% cap)** → beats baseline OOS on the primary split but
  not all; worth paper-watching under the hard cap that bounds downside.
- **Satellite** → beats baseline on ALL splits with non-worse decay.
- **Core (exploit)** → consistently beats on all splits AND ≥1 buy-and-hold
  baseline risk-adjusted, across multiple iterations. Never promote to core on
  one run.

## Record honestly (always, including failures)

Record in TWO joined places — the structured ledger AND the human narrative:

1. **Append a structured row to the ledger** via `append_experiment(record)`
   (or `python3 scripts/experiments.py --append '<json>'`). Fill the schema
   fields: `source="evolve-strategy"`, `mode`, `strategy`, `baseline`,
   `universe`, `params`, `splits` (each with start/end + IS/OOS Sharpe, CAGR,
   MaxDD, turnover), `decay`, `fitness`, `gate`, `hypothesis`, `notes`. The call
   returns a **`run_id`** — capture it.
2. **Append the human narrative to `docs/strategy-study.md`:** the hypothesis,
   the one variable changed, the multi-split numbers (IS/OOS Sharpe, CAGR, MaxDD,
   decay), the fitness, the gate decision, and *why* — and **reference the
   returned `run_id`** so the prose and the numbers are joined.

**Negative results are logged, not discarded** — they stop the next iteration
repeating the mistake. The ledger is the system's queryable memory; the narrative
is the why. Together they make the loop cumulative rather than random.

## Stop and report

End the run with: the hypothesis, the gate decision (reject / tactical /
satellite), the key numbers vs baseline, and a one-line suggested next hypothesis
for the following iteration. Do not start the next iteration — the human reviews
between runs. Do not arm live trading (golden rule #6).
