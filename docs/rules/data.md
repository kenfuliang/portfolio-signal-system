# Rule: Data

- **Never trust stale data.** Before backtesting, confirm each symbol's last bar
  reaches the backtest end date. The original demo symbols (SPY/AAPL/…) silently
  ended 2021-03-31 and corrupted the SPY baseline — `ingest_data.py` skips existing
  zips, so refresh with `--force` when in doubt.
- **Adjusted prices, identity factors.** We ingest split/dividend-adjusted OHLCV
  (yfinance `auto_adjust`) and write identity factor files (1,1) — a continuous
  research series. Note it is NOT broker-exact for live.
- **State survivorship bias.** Universes built from currently-liquid names
  (`build_universe.py`) exclude delisted names — research-grade only. Say so in any
  report using them.
- **Validate, don't assume.** A symbol with too few rows or gaps is dropped, and the
  drop is logged — never silently traded on partial data.
- **Data stays gitignored** (`data/`, `backtests/`, `reports/` outputs). Never commit
  data or secrets.
