# Rule: Testing

- **pytest is required.** Every pure module has unit tests: `strategy/factors.py`,
  `signals.py`, `risk.py`, `indicators.py`, `config_loader.py`.
- **Pure tests must not need LEAN/Docker.** They run on plain Python over
  pandas/dicts — fast, runnable via `pytest` with no engine. (This is why
  `strategy/` stays engine-agnostic — golden rule #2.)
- **Every fixed bug gets a regression test** that fails on the old code and passes on
  the fix. Seed set (all real, all cost us debugging time):
  1. `enforce_caps` with `max_per_sector_pct=None` must NOT shrink a single 0.95
     target (the phantom 30% sector-cap bug).
  2. Data-freshness check: a symbol's last bar must reach the backtest end (the
     SPY-ended-2021 stale-data bug).
  3. Sizing/exec path must tolerate `stop=None` without crashing (the null-stop bug).
- **CI runs tests on every push** (GitHub Actions). Red tests block merge.
- **No "smoke-tested" hand-waving.** If it matters, it has an automated test.
