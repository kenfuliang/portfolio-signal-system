#!/usr/bin/env python3
"""RESEARCH prototype: long QQQ calls as convex leverage, priced with synthetic
Black-Scholes (no real option data). NOT the LEAN path — a standalone approximate
backtest to test the *idea* cheaply. Caveats: no IV skew/smile, flat vol = trailing
realized vol, no bid-ask/slippage, European exercise, r configurable.

Mechanics: monthly, spend the whole equity on QQQ calls at a chosen moneyness and
tenor (calls bought at price, held; cash earns r). At each month-end the position is
marked-to-model; at expiry it pays intrinsic and we re-buy. Compared to QQQ buy-hold.

Usage:
    python3 scripts/option_backtest.py --moneyness 1.0 --dte 30
    python3 scripts/option_backtest.py --moneyness 0.8 --dte 90   # deep-ITM ~ leverage
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.options import bs_call_price, bs_put_price  # noqa: E402

DAILY = "data/equity/usa/daily/qqq.zip"


def load_qqq(start="20170101", end="20260616"):
    raw = zipfile.ZipFile(DAILY).read("qqq.csv").decode()
    rows = []
    for ln in raw.splitlines():
        p = ln.split(",")
        if len(p) < 6:
            continue
        d = p[0][:8]
        if start <= d <= end:
            rows.append((pd.Timestamp(d), int(p[4]) / 10000.0))
    rows.sort()
    return pd.Series(dict(rows))


def realized_vol(prices: pd.Series, i: int, window: int = 20) -> float:
    seg = prices.iloc[max(0, i - window):i + 1]
    if len(seg) < 5:
        return 0.2
    rets = np.log(seg / seg.shift(1)).dropna()
    v = float(rets.std() * math.sqrt(252))
    return max(v, 0.05)


def stats(equity: pd.Series):
    rets = equity.pct_change().dropna()
    yrs = len(equity) / 252
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1
    sharpe = (rets.mean() / rets.std() * math.sqrt(252)) if rets.std() else 0.0
    peak, mdd = equity.iloc[0], 0.0
    for v in equity:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    return cagr * 100, sharpe, mdd * 100


def run(prices, moneyness, dte, r, budget):
    """Convex-leverage structure: each roll spend `budget` fraction of equity on
    calls, keep the rest in cash earning r. Max loss per cycle = the budget sleeve;
    upside is convex. budget=1.0 reproduces the ruinous all-in case."""
    days = list(prices.index)
    equity, eq = [], 1.0
    cash = 1.0                       # start with all capital in the cash sleeve
    contracts = 0.0
    strike = exp_i = sigma0 = None
    daily_r = r / 252.0

    for i, dt in enumerate(days):
        S = prices.iloc[i]
        cash *= (1.0 + daily_r)                          # cash earns interest
        if strike is None or i >= exp_i:
            if strike is not None:                       # settle expiring calls
                cash += contracts * max(S - strike, 0.0)
            eq = cash                                    # full equity = cash now
            sigma0 = realized_vol(prices, i)
            strike = S / moneyness
            exp_i = min(i + dte, len(days) - 1)
            prem = bs_call_price(S, strike, dte / 252, sigma0, r)
            spend = budget * eq
            contracts = spend / prem if prem > 0 else 0.0
            cash = eq - spend                            # rest stays in cash
        T_rem = max((exp_i - i) / 252, 0.0)
        opt_val = contracts * bs_call_price(S, strike, T_rem, sigma0, r)
        equity.append(cash + opt_val)
    return pd.Series(equity, index=days)


def covered_call(prices, otm, dte, iv_mult):
    """Own QQQ, sell an OTM call each cycle (strike = S*(1+otm)), collect premium.
    Caps upside above the strike; premium cushions flat/down months. Harvests the
    volatility risk premium. sigma = realized vol * iv_mult (real IV usually exceeds
    realized, so iv_mult=1.0 is CONSERVATIVE — real premium would be higher)."""
    days = list(prices.index)
    equity, eq = [], 1.0
    entry_i = strike = sigma0 = prem = None
    for i, dt in enumerate(days):
        S = prices.iloc[i]
        if strike is None or i >= entry_i + dte:
            if strike is not None:                       # settle the cycle
                S0 = prices.iloc[entry_i]
                stock_ret = S / S0 - 1.0
                short_call = -max(S - strike, 0.0) / S0  # we are short the call
                eq *= (1.0 + stock_ret + short_call + prem)
            sigma0 = realized_vol(prices, i) * iv_mult
            strike = S * (1.0 + otm)
            prem = bs_call_price(S, strike, dte / 252, sigma0) / S
            entry_i = i
        equity.append(eq)                                 # mark at cycle equity (coarse)
    return pd.Series(equity, index=days)


def collar(prices, otm_call, otm_put, dte, iv_mult):
    """Own QQQ + sell an OTM call to fund a protective OTM put (a collar). Caps
    upside above the call strike, FLOORS losses below the put strike — directly
    attacks drawdown (our recurring edge). Near zero-cost when call/put premia match.
    Caveat: synthetic BS ignores put skew, so the real protective put costs MORE
    than modeled => real collar slightly worse than shown."""
    days = list(prices.index)
    equity, eq = [], 1.0
    entry_i = Kc = Kp = sigma0 = net_prem = None
    for i, dt in enumerate(days):
        S = prices.iloc[i]
        if Kc is None or i >= entry_i + dte:
            if Kc is not None:                                   # settle cycle
                S0 = prices.iloc[entry_i]
                ret = (S / S0 - 1.0)
                ret += -max(S - Kc, 0.0) / S0                     # short call
                ret += max(Kp - S, 0.0) / S0                      # long put
                ret += net_prem                                   # net premium (call-put)/S0
                eq *= (1.0 + ret)
            sigma0 = realized_vol(prices, i) * iv_mult
            Kc, Kp = S * (1.0 + otm_call), S * (1.0 - otm_put)
            net_prem = (bs_call_price(S, Kc, dte / 252, sigma0)
                        - bs_put_price(S, Kp, dte / 252, sigma0)) / S
            entry_i = i
        equity.append(eq)
    return pd.Series(equity, index=days)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--moneyness", type=float, default=1.0, help=">1 = ITM (lower strike)")
    ap.add_argument("--dte", type=int, default=30, help="days to expiry per roll")
    ap.add_argument("--r", type=float, default=0.04, help="cash/risk-free rate")
    ap.add_argument("--budget", type=float, default=0.15, help="equity fraction spent on calls per roll")
    ap.add_argument("--start", default="20170101")
    ap.add_argument("--end", default="20260616")
    ap.add_argument("--strategy", choices=["calls", "covered_call", "collar"], default="calls")
    ap.add_argument("--otm", type=float, default=0.05, help="covered-call OTM strike offset")
    ap.add_argument("--otm-put", type=float, default=0.07, help="collar protective-put OTM offset")
    ap.add_argument("--iv-mult", type=float, default=1.0, help="IV / realized-vol multiple for sold premium")
    args = ap.parse_args()

    prices = load_qqq(args.start, args.end)
    bh = prices / prices.iloc[0]
    c, s, d = stats(bh)
    print(f"QQQ buy-hold                          CAGR {c:7.2f}% | Sharpe {s:6.3f} | MaxDD {d:6.2f}%")

    if args.strategy == "covered_call":
        opt = covered_call(prices, args.otm, args.dte, args.iv_mult)
        c, s, d = stats(opt)
        print(f"covered call otm={args.otm} {args.dte}DTE iv={args.iv_mult}  "
              f"CAGR {c:7.2f}% | Sharpe {s:6.3f} | MaxDD {d:6.2f}%")
    elif args.strategy == "collar":
        opt = collar(prices, args.otm, args.otm_put, args.dte, args.iv_mult)
        c, s, d = stats(opt)
        print(f"collar call+{args.otm}/put-{args.otm_put} {args.dte}DTE  "
              f"CAGR {c:7.2f}% | Sharpe {s:6.3f} | MaxDD {d:6.2f}%")
    else:
        opt = run(prices, args.moneyness, args.dte, args.r, args.budget)
        c, s, d = stats(opt)
        print(f"calls m={args.moneyness} {args.dte}DTE budget={args.budget}  "
              f"CAGR {c:7.2f}% | Sharpe {s:6.3f} | MaxDD {d:6.2f}%")


if __name__ == "__main__":
    raise SystemExit(main())
