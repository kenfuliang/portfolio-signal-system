# Portfolio Signal System

A rules-based, multi-factor signal and (eventually) auto-trading system for US
stocks and ETFs, built on the **QuantConnect LEAN** engine so that backtest and
live trading run the *same code*.

> ⚠️ **Status: scaffold / not live.** No real orders are placed. The engine must
> be installed, a data feed chosen, and the strategy backtested + paper-traded
> before anything goes live. See `docs/portfolio-signal-system-design.md` for the
> full design and `docs/` §7 for the open data-tier decision.

## What you build vs. what you leverage

| Built here (your edge) | Leveraged (don't build) |
|---|---|
| `strategy/` factor, signal, risk logic | LEAN engine (backtest + live) |
| `config/` universe, risk, factor weights | IBKR / Alpaca (data + execution) |
| | BigQuery (storage), Slack (alerts) |

## Layout

```
config/      universe.yaml, risk.yaml, factors.yaml   — tunable parameters
strategy/    factors.py, signals.py, risk.py          — the decision logic
main.py      LEAN QCAlgorithm wiring it together
backtest/    backtest outputs
data/        cached pulls
notebooks/   research & validation
docs/        design document
```

## Setup

1. **Install the LEAN CLI** (requires Docker + Python 3.9+):
   ```bash
   pip install lean
   lean init                 # creates the LEAN workspace / data folder
   ```
2. **Run a backtest** locally:
   ```bash
   lean backtest "Portfolio Signal System"
   ```
3. **Paper trade**, then live, with the *same* `main.py`:
   ```bash
   lean live "Portfolio Signal System" --brokerage "Paper Trading"
   # later: --brokerage "Interactive Brokers" (or Alpaca), under your control
   ```

## Build phases (see design doc §9)

0. Design ✅ → 1. Data layer → 2. Scoring → 3. Risk/portfolio →
4. Output (Slack/BigQuery) → 5. Validation (backtest + paper) → 6. Live (small).

## Hard rules

- The system **recommends and, when authorized by you, executes** — but a human
  (you) connects the broker and arms live trading. This assistant does not place
  trades or move money on your behalf.
- Every buy/sell is the output of a written rule in `strategy/`, logged with its
  reason.
- Nothing goes live before it is backtested and paper-traded.
