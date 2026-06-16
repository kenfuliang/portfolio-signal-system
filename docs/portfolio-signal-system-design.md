# Personal Portfolio Signal System — Design

*Version 0.1 · Draft · June 15, 2026*

A system that ingests market, fundamental, and sentiment data, scores a defined
universe of stocks and ETFs, compares the result against your actual holdings,
and tells you **what to buy, what to sell, and what your portfolio should look
like** — delivered as Slack alerts and a logged record you can review and
backtest.

This document is the blueprint. It is data-source agnostic by design: the logic
below works whether prices come from IBKR (free with your account) or a paid FMP
tier. The one open decision is the data feed (see §7).

---

## 1. Design principles

- **Signals, not autopilot.** The system recommends; you execute. It never
  places trades or moves money.
- **Rules before discretion.** Every buy/sell is the output of a written rule,
  logged with its reason. No ad-hoc calls that can't be reviewed later.
- **Risk first.** Position sizing and stop discipline matter more than
  stock-picking. The system is built so a bad pick can't blow up the portfolio.
- **Evidence before trust.** No signal goes live until it's been backtested and
  paper-traded. The design assumes you'll distrust it until it earns trust.
- **Layered, not band-aid.** Each concern (data, scoring, risk, output) is a
  separate layer with a clean interface, so any one piece can be swapped without
  rewriting the rest.

---

## 2. Architecture

```
   DATA SOURCES                  ENGINE                       OUTPUT
 ┌──────────────┐
 │ IBKR*        │ prices,        ┌───────────────┐
 │ holdings     │──positions────▶│ 1. Ingest     │
 ├──────────────┤                │    & normalize│
 │ FMP          │ fundamentals,  └──────┬────────┘
 │ profiles     │──valuation────▶       │
 ├──────────────┤                ┌──────▼────────┐
 │ Bigdata      │ news,          │ 2. Factor     │
 │ sentiment    │──catalysts────▶│    scoring    │
 └──────────────┘                └──────┬────────┘
                                        │  composite rank
                                 ┌──────▼────────┐
                                 │ 3. Portfolio  │       ┌──────────┐
                                 │    & risk     │──────▶│ Slack    │ alerts
                                 │    rules      │       ├──────────┤
                                 └──────┬────────┘       │ BigQuery │ log +
                                        │                │          │ history
                                 ┌──────▼────────┐       └──────────┘
                                 │ 4. Decision   │            ▲
                                 │ buy/sell/hold │────────────┘
                                 └───────────────┘

 * IBKR connected later; until then prices come from your chosen feed (§7).
```

**The four engine stages:**

1. **Ingest & normalize** — pull holdings, prices, fundamentals, and news on a
   schedule; clean into a consistent table keyed by ticker and date; write to
   BigQuery so the system has memory and can backtest.
2. **Factor scoring** — score every name in the universe on four factor groups
   (§4) and combine into one composite rank.
3. **Portfolio & risk rules** — apply position sizing, diversification caps, and
   stop logic (§5) to turn rankings into *allowed* actions.
4. **Decision** — diff the target portfolio against your real holdings and emit
   buy / trim / sell / hold, each with a written reason, to Slack and BigQuery.

---

## 3. Connector layer

| Layer | Connector | Role | Status |
|---|---|---|---|
| Holdings + prices | **IBKR** (read-only) | Positions, cash, cost basis; free OHLCV history & snapshots | Connect later |
| Fundamentals | **FMP** | Company profiles, valuation, estimates, screener\* | Connected (free tier) |
| News / sentiment | **Bigdata** | Sector & company tearsheets, sentiment, events calendar | Connected |
| Storage | **BigQuery** | Price history, signals, portfolio state, backtests | Connected |
| Alerts | **Slack** | Push buy/sell notifications | Connected |

\* Screener, historical prices, and technicals require a paid FMP tier — see §7.

You already hold 4 of 5 layers. The decision logic does not care which connector
supplies prices, so connecting IBKR later is a drop-in, not a rebuild.

---

## 4. The buy/sell signal framework

The core idea: **rank the universe on a composite score, then act on the gap
between that ranking and what you own.** The composite is a weighted blend of
four factor groups — a standard multi-factor approach, chosen because no single
signal is reliable alone and the blend is far more robust than any one metric.

### 4.1 Factor groups

| Group | What it measures | Example inputs | Default weight |
|---|---|---|---|
| **Trend / Momentum** | Is the market already voting yes? | Price vs 50/200-day MA, 12-month-minus-1 return, distance from 52-wk high | 35% |
| **Quality** | Is the business sound? | Gross/operating margin, ROIC, revenue growth, debt/equity | 25% |
| **Valuation** | Am I overpaying? | P/E, EV/EBITDA, PEG vs sector median | 20% |
| **Sentiment / Catalyst** | Is something changing now? | Bigdata sentiment score, news flow, upcoming earnings/events | 20% |

Each name gets a 0–100 percentile score within its sector per group; the
composite is the weighted sum. Weights are tunable and should be **set by
backtest, not by gut** (§8). The split above is a sensible starting point biased
toward trend — appropriate for the swing/position style and the AI-semis theme
you're tracking.

### 4.2 Buy logic

A name becomes a **buy candidate** when **all** hold:

1. Composite score in the **top quintile** of its universe.
2. Trend filter passes — price above its 200-day MA (don't fight the primary
   trend) **and** above 50-day, or reclaiming it on rising volume.
3. No disqualifying catalyst — e.g. earnings inside the next 3 days (avoid
   binary events) unless the strategy explicitly targets them.
4. Passes risk/sizing rules in §5 (room in the sleeve, sector cap not breached).

Candidates are ranked; the system proposes the highest-scoring names that fit
the available cash and risk budget.

### 4.3 Sell logic — the discipline that matters most

A position is flagged to **trim or exit** when **any** trigger fires:

- **Stop-loss hit** — price closes below the position's stop (set at entry, §5).
  Non-negotiable, fires first.
- **Thesis break** — the reason you bought is gone: quality score collapses,
  valuation goes extreme, or a Bigdata catalyst (guidance cut, downgrade,
  regulatory hit) breaks the story.
- **Rank decay** — composite score falls out of the top half of the universe;
  capital is better deployed elsewhere.
- **Risk breach** — position has grown beyond its size cap (trim back to target)
  or portfolio-level limits are tripped (§5).
- **Time stop** (optional, for tactical/leveraged sleeve) — exit if the expected
  move hasn't played out within a set window.

Every sell logs *which* trigger fired, so you can audit whether the rules are
working.

---

## 5. Portfolio construction & risk rules

This answers "what should my portfolio be?" The structure is a **core-satellite-
tactical** model — standard for blending stability with higher-conviction bets,
and well suited to including leveraged names without letting them dominate.

### 5.1 Sleeves

| Sleeve | Target allocation | Holds | Purpose |
|---|---|---|---|
| **Core** | 50–70% | Broad/sector ETFs (e.g. SMH, SOXX, index ETFs) | Stable base, low turnover |
| **Satellite** | 20–40% | Individual stocks (e.g. AXTI, COHR, LITE) | Conviction theme bets |
| **Tactical** | 0–10% (hard cap) | Leveraged / single-stock ETFs (e.g. AXTX 2x) | High-risk, short-hold, tight leash |

Allocations are ranges; the system rebalances toward them and flags drift beyond
a band (e.g. ±5%).

### 5.2 Position sizing — risk-based, not equal-weight

Size each position by **how much you'd lose if the stop hits**, not by dollar
amount. Standard formula:

```
Position size ($) = (Account equity × Risk-per-trade %) ÷ (Entry − Stop) × Entry
```

- **Risk per trade:** 0.5–1.0% of equity. A higher-volatility name gets *fewer*
  shares for the same dollar risk — volatility is automatically accounted for.
- **Max single position:** e.g. 10% of equity (lower for the tactical sleeve).
- **Stops:** volatility-based (e.g. 2–3× ATR below entry) rather than a flat %,
  so the stop fits the stock's normal noise.

### 5.3 Diversification caps

- Max **per name**: 10% (core ETFs may run higher by design).
- Max **per sector**: e.g. 30% — prevents the whole book becoming an AI-semis
  bet even when every semi name scores well.
- Min **cash buffer**: e.g. 5% for flexibility.

### 5.4 Leveraged / single-stock ETF rules (AXTX-type)

These need their own guardrails because daily reset + volatility decay make them
unsuitable for passive holding:

- Hard **10% portfolio cap** across the whole tactical sleeve.
- **Daily** monitoring required (not weekly) — decay compounds.
- **Tighter stop** and a **time stop** — these are trades, not holdings.
- Never average down into one.

### 5.5 Portfolio-level circuit breaker

If total portfolio drawdown from peak exceeds a threshold (e.g. 15%), the system
raises a **risk-off alert**: pause new buys, review/cut the highest-volatility
sleeve first. This stops a bad streak from compounding.

---

## 6. Workflow & cadence

**Daily (after US close):**
1. Pull holdings (IBKR) + prices + fundamentals + sentiment.
2. Recompute factor scores and composite ranks.
3. Run sell triggers against current holdings → flag any exits.
4. Run buy logic against available cash/risk budget → propose entries.
5. Check sizing, diversification, and drawdown rules.
6. Post a **Slack digest**: today's buy / trim / sell / hold list, each with its
   one-line reason and suggested size; log everything to BigQuery.

**Weekly:** rebalance check vs sleeve targets; surface drift.
**Monthly:** review signal hit-rate from the BigQuery log; retune weights if warranted.

Intraday stop monitoring (especially the tactical sleeve) requires a real-time
feed — a paid FMP tier or IBKR streaming. On free/EOD data, stops are evaluated
on closing prices only (a real limitation to decide on in §7).

---

## 7. Data-tier decision (the one open item)

The design runs on any feed. What you pick sets what's possible:

| Capability | Free FMP | FMP Starter (~$22/mo) | FMP Premium | IBKR (free w/ acct) |
|---|---|---|---|---|
| Single-name price snapshot | ✅ (via profile) | ✅ | ✅ | ✅ |
| Historical OHLCV (for signals/backtest) | ❌ | ✅ EOD | ✅ | ✅ |
| Screener (universe scan) | ❌ | ✅ | ✅ | partial |
| Technical indicators | ❌ | ✅ | ✅ | build from history |
| Real-time quotes (intraday stops) | ❌ | ❌ | ✅ | ✅ streaming |
| Fundamentals / profiles | ✅ basic | ✅ | ✅ | limited |

**Recommendation:** connect **IBKR** when ready — it supplies free OHLCV history
and real-time snapshots, covering the signal and stop needs at no extra cost,
and brings your real holdings in. Keep FMP (even free) for company profiles and
add Bigdata for sentiment. Only upgrade FMP if you want its screener/estimates
before IBKR is connected. This avoids paying for data IBKR gives you free.

---

## 8. Validation before trust (do not skip)

1. **Backtest** the rules on historical data once a history feed is live: measure
   CAGR, max drawdown, Sharpe, hit-rate, and turnover. Tune factor weights here —
   not by intuition.
2. **Walk-forward / out-of-sample** test to avoid curve-fitting.
3. **Paper trade** the live signals for a few weeks; compare to backtest
   expectations.
4. **Go live small**, scaling size only as the system proves out.

A signal engine that hasn't been backtested is a guess with extra steps.

---

## 9. Phased build plan

| Phase | Deliverable | Needs |
|---|---|---|
| **0 — Design** *(this doc)* | Agreed architecture, rules, universe | — |
| **1 — Data layer** | BigQuery tables; daily ingest job pulling prices + fundamentals + sentiment | Data-tier decision (§7) |
| **2 — Scoring** | Factor scoring + composite rank over the universe | Phase 1 |
| **3 — Risk/portfolio** | Sizing, caps, stop logic; target-vs-actual diff | Phase 2 + IBKR holdings |
| **4 — Output** | Daily Slack digest + BigQuery signal log | Phase 3 |
| **5 — Validation** | Backtest + paper-trade results, weight tuning | history feed |
| **6 — Live (small)** | Run daily, scale as it proves out | Phase 5 |

---

## 10. Open decisions for you

1. **Data feed** (§7) — connect IBKR, or upgrade FMP now? *(Currently: design-only on free FMP.)*
2. **Universe** — define the starting watchlist (e.g. the AI-semis/optical names
   plus your core ETFs), or have the system screen a broad universe (needs paid tier).
3. **Risk appetite** — confirm risk-per-trade %, max position %, and the tactical
   sleeve cap. Defaults above are conservative starting points.
4. **Style confirmation** — swing/position with a small leveraged sleeve, as
   selected. Adjust if that's drifted.
```
