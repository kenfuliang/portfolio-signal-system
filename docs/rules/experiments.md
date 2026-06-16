# Rule: Experiments & measurement

- **Measure baselines the same way as strategies.** Run SPY/QQQ/TQQQ buy-and-hold
  through the *same engine* (`scripts/benchmark.py` → `reports/baselines.json`), never
  a separate raw-price formula. Mixing measurement methods produced an
  apples-to-oranges comparison that wasted an iteration.
- **Always compare against the three baselines:** SPY (market), QQQ (growth), TQQQ
  (aggressive). The bar is risk-adjusted: beating TQQQ means matching its return at
  far less drawdown, not exceeding 3× in a bull run.
- **Assert sanity invariants.** Check deployed capital is what you intended (a
  `BUY -> 30%` when you meant ~100% is a bug — it's how the sector-cap bug hid). Log
  any silent caps, drops, or truncation. A backtest that looks too good/bad is a
  measurement bug until proven otherwise.
- **Walk-forward before trusting.** Split in-sample vs out-of-sample
  (`scripts/walk_forward.py`); rank by OOS robustness (low IS→OOS decay), not peak
  in-sample Sharpe.
- **Record honestly** in `docs/strategy-study.md`: negative results and corrections
  included.
