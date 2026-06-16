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
from strategy.factors import FactorInputs, composite_scores
from strategy.signals import PositionState, Action, evaluate
from strategy.risk import position_size, enforce_caps, circuit_breaker_tripped


class PortfolioSignalSystem(QCAlgorithm):

    def initialize(self):
        self.cfg = Config.load()

        self.set_start_date(2023, 1, 1)
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

        # daily rebalance, before the close
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.before_market_close(list(self.symbols.values())[0], 15),
            self.rebalance,
        )

    # ---------- main daily loop ----------
    def rebalance(self):
        if self.is_warming_up:
            return

        equity = self.portfolio.total_portfolio_value
        self.peak_equity = max(self.peak_equity, equity)

        # circuit breaker: halt new buys on deep drawdown
        halt_buys = circuit_breaker_tripped(equity, self.peak_equity, self.cfg.risk)
        if halt_buys:
            self.debug(f"[circuit-breaker] drawdown limit hit; new buys paused")

        # 1. build factor inputs (price-only -> degraded trend mode for now)
        hist = self.history([s for s in self.symbols.values()], 260, Resolution.DAILY)
        inputs = {}
        for ticker, sym in self.symbols.items():
            prices = self._closes(hist, sym)
            if prices is None or len(prices) < 200:
                continue
            inputs[ticker] = FactorInputs(prices=prices, fundamentals=None, sentiment=None)
        if not inputs:
            return

        # 2. composite ranking
        composite, active = composite_scores(inputs, self.cfg.factors["weights"])

        # 3. build position states for the signal layer
        states = {}
        for ticker in inputs:
            sym = self.symbols[ticker]
            holding = self.portfolio[sym]
            prices = inputs[ticker].prices
            px = float(prices.iloc[-1])
            states[ticker] = PositionState(
                symbol=ticker,
                held=holding.invested,
                price=px,
                stop=self.stops.get(ticker),
                weight=(holding.holdings_value / equity) if equity else 0.0,
                target_weight=self.cfg.risk["diversification"]["max_per_name_pct"],
                above_sma50=px > float(prices.tail(50).mean()),
                above_sma200=px > float(prices.tail(200).mean()),
                earnings_in_days=None,        # wire from an earnings calendar later
                thesis_broken=False,          # wire from fundamentals/sentiment later
            )

        decisions = evaluate(composite, states, self.cfg.factors["buy"], self.cfg.factors["sell"])

        # 4. size the buys and enforce caps
        lev_syms = set(self.cfg.risk["leveraged"]["symbols"])
        raw_targets = {}
        for d in decisions:
            if d.action == Action.BUY and not halt_buys:
                atr_val = float(self.atr[d.symbol].current.value) if self.atr[d.symbol].is_ready else 0.0
                if atr_val <= 0:
                    continue
                res = position_size(
                    equity, states[d.symbol].price, atr_val,
                    sleeve=self.cfg.sleeve_of(d.symbol) or "satellite",
                    risk_cfg=self.cfg.risk,
                    is_leveraged=d.symbol in lev_syms,
                )
                raw_targets[d.symbol] = res.target_weight
                self.stops[d.symbol] = res.stop_price

        sleeve_of = {t: (self.cfg.sleeve_of(t) or "satellite") for t in raw_targets}
        sector_of = {t: "Technology" for t in raw_targets}   # refine with real sectors later
        targets, notes = enforce_caps(raw_targets, sleeve_of, sector_of, self.cfg.risk)
        if notes:
            self.debug(f"[caps] {', '.join(notes)}")

        # 5. execute: exits first, then entries
        for d in decisions:
            if d.action == Action.SELL:
                if self.portfolio[self.symbols[d.symbol]].invested:
                    self.liquidate(self.symbols[d.symbol])
                    self.stops.pop(d.symbol, None)
                    self.log(f"SELL {d.symbol} :: {d.reason}")
        for ticker, w in targets.items():
            self.set_holdings(self.symbols[ticker], w)
            self.log(f"BUY  {ticker} -> {w:.1%} :: stop {self.stops.get(ticker):.2f}")

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
        # intraday stop check (uses whatever resolution the data feed provides)
        for ticker, sym in self.symbols.items():
            if sym in data and self.portfolio[sym].invested:
                stop = self.stops.get(ticker)
                if stop and data[sym] and data[sym].price <= stop:
                    self.liquidate(sym)
                    self.stops.pop(ticker, None)
                    self.log(f"SELL {ticker} :: intraday stop {stop:.2f}")
