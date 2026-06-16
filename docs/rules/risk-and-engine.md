# Rule: Risk & engine

- **Risk rules are non-negotiable** (golden rule #4). Live strategies respect
  `config/risk.yaml`: per-name cap, sleeve caps, leveraged cap, circuit breaker.
- **A cap requires real data to mean anything.** The per-sector cap
  (`max_per_sector_pct`) is `null`/disabled until real sector data is wired — a
  synthetic "each name is its own sector" mapping silently turned it into a 30%
  per-name clamp. Don't re-enable it without real sectors.
- **Caps and stops are explicit, opt-in switches**, not accidental behavior:
  - `enforce_caps: true|false` (strategies.yaml) — false only for benchmarks /
    intentionally-concentrated runs that must be fully invested.
  - `use_stops: true|false` — false for buy-hold/benchmark runs so normal dips don't
    liquidate them.
- **`main.py` is the only engine-coupled file** (golden rule #1). All LEAN types,
  scheduling, ordering live there; everything it calls in `strategy/` stays pure.
- **No order path bypasses `strategy/risk.py`** for live trading. The assistant never
  arms live execution (golden rule #6).
