# CLAUDE.md — project guide for Claude Code

Rules-based, multi-factor signal & (eventually) auto-trading system for US
stocks/ETFs, built on **QuantConnect LEAN**. Full design in
`docs/portfolio-signal-system-design.md` — read it before non-trivial changes.

## Golden rules

1. **Backtest == live: one code path.** `main.py` is the only engine-coupled
   file and runs identically in backtest and live. Never fork strategy logic
   between the two. If you can't backtest it, it doesn't ship.
2. **Strategy logic stays pure and engine-agnostic.** Everything in `strategy/`
   (`factors.py`, `signals.py`, `risk.py`) must be plain Python over
   pandas/dicts — no `AlgorithmImports`, no LEAN types. This keeps it unit-
   testable and reusable. `main.py` is the *only* adapter that touches LEAN.
3. **Config over code.** Tunables (universe, risk limits, factor weights) live in
   `config/*.yaml`, not in code. Add a parameter to YAML + loader, don't hardcode.
4. **Risk rules are non-negotiable.** Every order must respect `config/risk.yaml`
   (sizing, per-name/sector/sleeve caps, leveraged cap, circuit breaker). Don't
   add an order path that bypasses `strategy/risk.py`.
5. **Tune weights by backtest, not by gut.** Factor weights in `factors.yaml` are
   hypotheses to be validated (design §8), not settled truth.
6. **No live trading by the assistant.** Claude helps design, write, test, and
   backtest. The human connects the broker and arms live execution. Never place
   real orders, move money, or commit broker credentials.

## Rules (read these — they encode lessons paid for in bugs)

@docs/rules/documentation.md
@docs/rules/testing.md
@docs/rules/strategy.md
@docs/rules/data.md
@docs/rules/experiments.md
@docs/rules/risk-and-engine.md

## Layout

```
main.py              LEAN adapter (only engine-coupled file; sizing modes, schedule)
strategy/            pure logic — base, registry, indicators, factors, signals, risk
strategy/strategies/ the strategy zoo (trend, breakout, reversion, allocation)
config/              universe.yaml, risk.yaml, factors.yaml, strategies.yaml, data.yaml
scripts/             ingest_data, build_universe, run_tournament, walk_forward, benchmark
docs/                design doc, strategy-study.md, rules/
reports/ backtests/ data/   engine outputs & cached pulls (gitignored)
```

## Architecture flow

`config + data → factors.composite_scores → signals.evaluate →
risk.position_size/enforce_caps → main.py places orders → Slack/BigQuery log`

## Current state

- **Local data ingested:** ~4,300 liquid US daily symbols via `scripts/ingest_data.py`
  (yfinance → LEAN format). LEAN workspace is initialized; backtests run locally.
- **Pluggable strategies + tournament:** 25 strategies behind a `Strategy` interface
  (`strategy/registry.py`), selected by `config/strategies.yaml: active`; sweep and
  walk-forward harnesses in `scripts/`. Findings in `docs/strategy-study.md`.
- **Degraded mode still:** price-only ⇒ factor model runs trend-only;
  quality/valuation/sentiment activate once their inputs are fed in `main.py`.
- **Three harness bugs found & fixed** (phantom 30% sector cap, stale benchmark data,
  null-stop crash). See `docs/strategy-study.md` measurement-correction note.
- **No pytest suite yet** — the #1 next step; the testing rule governs it.
- Headline finding: volatility-targeted sizing (the "percentage" lever) beat the
  SPY/QQQ/TQQQ baselines where 25 selection strategies could not — pending walk-forward.

## Commands

```bash
pip install -r requirements.txt
export PATH="$HOME/Library/Python/3.9/bin:$PATH"   # lean CLI install location
lean backtest .                              # backtest active strategy (== live path)
python3 scripts/ingest_data.py [--force]     # refresh local price data
python3 scripts/build_universe.py --n 500    # build a broad universe into universe.yaml
python3 scripts/run_tournament.py            # backtest all strategies + reports
python3 scripts/walk_forward.py --strategies a,b,c   # in-sample vs out-of-sample
python3 scripts/benchmark.py                 # SPY/QQQ/TQQQ baselines -> reports/baselines.json
# quick logic check without LEAN:
python3 -c "from strategy.config_loader import Config; Config.load().validate(); print('config OK')"
```

## Conventions

- Python 3.9+, snake_case, type hints, dataclasses for structured state.
- LEAN Python API uses snake_case (`self.set_holdings`, `self.history`).
- Keep `strategy/` free of side effects; pass data in, return decisions out.
- Secrets never committed — see `.gitignore` (`*.env`, `config/secrets.yaml`, credentials).

## Suggested next steps

1. Add `tests/` (pytest) for `factors`/`signals`/`risk` + a GitHub Actions CI.
2. Resolve the data-tier decision, then run the first backtest.
3. Wire fundamentals + Bigdata sentiment adapters to exit degraded mode.
4. Add the Slack daily-digest output and BigQuery signal log (design §6).
