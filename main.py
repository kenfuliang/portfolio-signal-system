"""LEAN algorithm — thin adapter.

This file is the ONLY engine-coupled code. It feeds LEAN's data into the pure
functions in `strategy/` and turns their decisions into orders. Because backtest
and live use this same file, what you test is what you trade.

Run:
    lean backtest "portfolio-signal-system"
    lean live   "portfolio-signal-system" --brokerage "Paper Trading"

Degraded mode: with price-only data, the factor model runs trend-only (see
factors.py). Connect fundamentals (LEAN/paid FMP) and Bigdata sentiment to enable
the full 4-factor blend; no code change needed beyond populating the inputs below.
"""
from datetime import timedelta

import pandas as pd
from AlgorithmImports import *  # LEAN runtime provides this

from strategy.config_loader import Config
from strategy.base import SymbolContext
from strategy.indicators import realized_vol
from strategy.registry import get_strategy
from strategy.signals import Action
from strategy.risk import position_size, enforce_caps, circuit_breaker_tripped


class PortfolioSignalSystem(QCAlgorithm):

    def initialize(self):
        self.cfg = Config.load()
        self.strategy = get_strategy(self.cfg.active_strategy())
        self.use_stops = self.cfg.strategies.get("use_stops", True)

        # backtest window: optional override from config/strategies.yaml
        # (backtest_start / backtest_end as "YYYY-MM-DD") for walk-forward splits.
        start = self.cfg.strategies.get("backtest_start")
        end = self.cfg.strategies.get("backtest_end")
        if start:
            self.set_start_date(*[int(x) for x in start.split("-")])
        else:
            self.set_start_date(2017, 1, 1)   # use most of the local ~10y history
        if end:
            self.set_end_date(*[int(x) for x in end.split("-")])
        self.set_cash(100_000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)

        # add the universe
        self.symbols = {}
        for ticker in self.cfg.all_symbols():
            sec = self.add_equity(ticker, Resolution.DAILY)
            self.symbols[ticker] = sec.symbol

        # indicators for ATR-based stops
        self.atr = {t: self.atr(s, self.cfg.risk["sizing"]["atr_period"], MovingAverageType.WILDERS, Resolution.DAILY)
                    for t, s in self.symbols.items()}

        self.stops = {}            # symbol -> stop price
        self.peak_equity = self.portfolio.total_portfolio_value

        # warm up enough history for the 200-day trend factor
        self.set_warm_up(timedelta(days=400))

        # rebalance cadence from config (daily | weekly | monthly); default daily.
        cadence = self.cfg.strategies.get("rebalance", "daily")
        anchor = list(self.symbols.values())[0]
        if cadence == "monthly":
            date_rule = self.date_rules.month_start(anchor)
        elif cadence == "weekly":
            date_rule = self.date_rules.week_start(anchor)
        else:
            date_rule = self.date_rules.every_day()
        self.schedule.on(
            date_rule,
            self.time_rules.before_market_close(anchor, 15),
            self.rebalance,
        )

    # ---------- main daily loop ----------
    def rebalance(self):
        if self.is_warming_up:
            return

        equity = self.portfolio.total_portfolio_value
        self.peak_equity = max(self.peak_equity, equity)

        # circuit breaker: halt new buys on deep drawdown. Opt-in (use_circuit_breaker,
        # default True): it traps go-to-cash timing strategies, because a cashed-out
        # book can't climb back above its peak, so the halt never lifts and re-entry
        # is blocked forever. Such strategies set use_circuit_breaker: false.
        halt_buys = (self.cfg.strategies.get("use_circuit_breaker", True)
                     and circuit_breaker_tripped(equity, self.peak_equity, self.cfg.risk))
        if halt_buys:
            self.debug(f"[circuit-breaker] drawdown limit hit; new buys paused")

        # 1. build per-symbol context for the active strategy
        hist = self.history([s for s in self.symbols.values()], 260, Resolution.DAILY)
        contexts = {}
        for ticker, sym in self.symbols.items():
            prices = self._closes(hist, sym)
            if prices is None or len(prices) < 200:
                continue
            holding = self.portfolio[sym]
            contexts[ticker] = SymbolContext(
                symbol=ticker,
                prices=prices,
                held=holding.invested,
                price=float(prices.iloc[-1]),
                weight=(holding.holdings_value / equity) if equity else 0.0,
                target_weight=self.cfg.risk["diversification"]["max_per_name_pct"],
                stop=self.stops.get(ticker),
            )
        if not contexts:
            return

        # 2. the active strategy decides buy/sell/hold (shared risk layer sizes them)
        decisions = self.strategy.generate(contexts, self.cfg)

        # 3. size the buys and enforce caps
        # sizing mode: risk_based (ATR risk per trade, default) | equal_weight
        # (fully-invested: split (1 - cash buffer) equally across buys). ATR stops
        # are always set so stop-loss exits still fire.
        lev_syms = set(self.cfg.risk["leveraged"]["symbols"])
        sizing_mode = self.cfg.strategies.get("sizing", "risk_based")
        buys = [d for d in decisions if d.action == Action.BUY and not halt_buys]
        raw_targets = {}

        if sizing_mode == "equal_weight" and buys:
            buffer = self.cfg.risk["diversification"]["min_cash_buffer_pct"]
            ew = (1.0 - buffer) / len(buys)
            for d in buys:
                raw_targets[d.symbol] = ew
                if self.use_stops:
                    atr_val = float(self.atr[d.symbol].current.value) if self.atr[d.symbol].is_ready else 0.0
                    mult = self.cfg.risk["sizing"]["atr_stop_multiple"]
                    self.stops[d.symbol] = max(contexts[d.symbol].price - mult * atr_val, 0.01) if atr_val > 0 else None
                else:
                    self.stops[d.symbol] = None
        elif sizing_mode == "vol_target" and buys:
            # "percentage" lever: scale each holding's weight inversely to its
            # realized volatility toward a target annual vol (volatility-managed
            # portfolio). Leans in when calm, pulls back when stormy. max_leverage
            # caps total exposure (>1 permits margin).
            vt = self.cfg.strategies.get("vol_target_cfg", {}) or {}
            target = vt.get("target_vol", 0.15)
            max_lev = vt.get("max_leverage", 1.0)
            window = vt.get("vol_window", 20)
            weights = {}
            for d in buys:
                v = realized_vol(contexts[d.symbol].prices, window)
                weights[d.symbol] = (target / v) if v and v > 0 else 0.0
            gross = sum(weights.values())
            if gross > max_lev and gross > 0:           # scale down to leverage cap
                weights = {s: w * max_lev / gross for s, w in weights.items()}
            for d in buys:
                raw_targets[d.symbol] = min(weights[d.symbol], max_lev)
                self.stops[d.symbol] = None
        else:
            for d in buys:
                atr_val = float(self.atr[d.symbol].current.value) if self.atr[d.symbol].is_ready else 0.0
                if atr_val <= 0:
                    continue
                res = position_size(
                    equity, contexts[d.symbol].price, atr_val,
                    sleeve=self.cfg.sleeve_of(d.symbol) or "satellite",
                    risk_cfg=self.cfg.risk,
                    is_leveraged=d.symbol in lev_syms,
                )
                raw_targets[d.symbol] = res.target_weight
                self.stops[d.symbol] = res.stop_price if self.use_stops else None

        # enforce diversification caps unless this run opts out (benchmarks /
        # intentionally-concentrated strategies set enforce_caps: false).
        if self.cfg.strategies.get("enforce_caps", True):
            sleeve_of = {t: (self.cfg.sleeve_of(t) or "satellite") for t in raw_targets}
            # no real sector data -> empty sector map; per-sector cap is null/disabled
            # in risk.yaml so it can't bind. Per-name + sleeve caps still apply.
            sector_of = {}
            targets, notes = enforce_caps(raw_targets, sleeve_of, sector_of, self.cfg.risk)
            if notes:
                self.debug(f"[caps] {', '.join(notes)}")
        else:
            targets = raw_targets

        # 5. execute: exits first, then entries
        for d in decisions:
            if d.action == Action.SELL:
                if self.portfolio[self.symbols[d.symbol]].invested:
                    self.liquidate(self.symbols[d.symbol])
                    self.stops.pop(d.symbol, None)
                    self.log(f"SELL {d.symbol} :: {d.reason}")
        for ticker, w in targets.items():
            self.set_holdings(self.symbols[ticker], w)
            stop = self.stops.get(ticker)
            stop_txt = f"stop {stop:.2f}" if stop else "no stop"
            self.log(f"BUY  {ticker} -> {w:.1%} :: {stop_txt}")

    # ---------- helpers ----------
    @staticmethod
    def _closes(hist, symbol):
        if hist is None or hist.empty or "close" not in hist.columns:
            return None
        try:
            s = hist.loc[symbol]["close"]
            return s.reset_index(drop=True)
        except (KeyError, TypeError):
            return None

    def on_data(self, data: Slice):
        # intraday stop check (opt-in: buy-hold / benchmark runs set use_stops: false)
        if not self.use_stops:
            return
        for ticker, sym in self.symbols.items():
            if sym in data and self.portfolio[sym].invested:
                stop = self.stops.get(ticker)
                if stop and data[sym] and data[sym].price <= stop:
                    self.liquidate(sym)
                    self.stops.pop(ticker, None)
                    self.log(f"SELL {ticker} :: intraday stop {stop:.2f}")
