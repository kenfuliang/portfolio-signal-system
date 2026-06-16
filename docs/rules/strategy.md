# Rule: Strategy development

- **Implement the `Strategy` interface** (`strategy/base.py`): `generate(contexts,
  cfg) -> list[Decision]`. Decide *which names to hold*; the risk layer sizes them.
- **Stay pure.** No `AlgorithmImports`, no LEAN types in `strategy/`. Engine coupling
  lives only in `main.py` (golden rules #1, #2).
- **Register + configure.** Add the class to `strategy/registry.py`
  (`STRATEGY_CLASSES`); put all tunables in `config/strategies.yaml` (config over
  code, golden rule #3). No hardcoded thresholds.
- **Reuse indicators.** Compute signals from `strategy/indicators.py` (RSI, MACD,
  Bollinger, ADX, realized_vol, …); add new indicators there with a test.
- **Document the thesis** in the docstring (see documentation rule).
- **"Good" requires validation, not a pretty backtest.** A strategy is not
  trustworthy until backtested **and walk-forward validated** out-of-sample. High
  in-sample Sharpe is a warning sign, not proof (the MACD overfit lesson).
- **The lever is usually sizing/exposure, not selection.** Remember the study:
  25 selection strategies lagged; volatility-targeted sizing beat the baselines.
