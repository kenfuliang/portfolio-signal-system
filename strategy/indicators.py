"""Reusable technical indicators — pure functions over a chronological price
Series (daily close). Kept dependency-light (pandas/numpy) so strategies stay
testable without LEAN. Functions return either a scalar (latest value) or a Series
where noted. All tolerate short histories by returning None when underdetermined.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def sma(prices: pd.Series, n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    return float(prices.tail(n).mean())


def ema_series(prices: pd.Series, n: int) -> pd.Series:
    return prices.ewm(span=n, adjust=False).mean()


def ema(prices: pd.Series, n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    return float(ema_series(prices, n).iloc[-1])


def rsi(prices: pd.Series, n: int = 14) -> Optional[float]:
    """Wilder's RSI, latest value in [0, 100]."""
    if len(prices) < n + 1:
        return None
    delta = prices.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, hist) latest values, or (None,)*3."""
    if len(prices) < slow + signal:
        return None, None, None
    macd_line = ema_series(prices, fast) - ema_series(prices, slow)
    sig = macd_line.ewm(span=signal, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(sig.iloc[-1]), float((macd_line - sig).iloc[-1])


def macd_cross_up(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[bool]:
    """True if MACD crossed above its signal line on the latest bar."""
    if len(prices) < slow + signal + 1:
        return None
    macd_line = ema_series(prices, fast) - ema_series(prices, slow)
    sig = macd_line.ewm(span=signal, adjust=False).mean()
    diff = macd_line - sig
    return bool(diff.iloc[-1] > 0 >= diff.iloc[-2])


def bollinger(prices: pd.Series, n: int = 20, k: float = 2.0):
    """Return (mid, upper, lower) latest band values, or (None,)*3."""
    if len(prices) < n:
        return None, None, None
    window = prices.tail(n)
    mid = float(window.mean())
    sd = float(window.std(ddof=0))
    return mid, mid + k * sd, mid - k * sd


def donchian_high(prices: pd.Series, n: int) -> Optional[float]:
    if len(prices) < n + 1:
        return None
    # highest close over the prior n bars (exclude today so a breakout is "new")
    return float(prices.iloc[-(n + 1):-1].max())


def roc(prices: pd.Series, n: int) -> Optional[float]:
    if len(prices) <= n:
        return None
    return float(prices.iloc[-1] / prices.iloc[-1 - n] - 1.0)


def momentum_12_1(prices: pd.Series) -> Optional[float]:
    """12-month minus 1-month return (skip the most recent ~21 sessions)."""
    if len(prices) < 252:
        return None
    return float(prices.iloc[-21] / prices.iloc[-252] - 1.0)


def dist_from_high(prices: pd.Series, n: int = 252) -> Optional[float]:
    if len(prices) < 2:
        return None
    hi = float(prices.tail(n).max())
    if hi <= 0:
        return None
    return float(prices.iloc[-1] / hi - 1.0)   # 0 at highs, negative below


def realized_vol(prices: pd.Series, n: int = 20) -> Optional[float]:
    """Annualized realized volatility from daily log returns."""
    if len(prices) < n + 1:
        return None
    rets = np.log(prices / prices.shift(1)).dropna().tail(n)
    if len(rets) < 2:
        return None
    return float(rets.std(ddof=0) * np.sqrt(252))


def atr_from_close(prices: pd.Series, n: int = 14) -> Optional[float]:
    """ATR proxy from close-to-close moves (no intraday H/L in daily close series)."""
    if len(prices) < n + 1:
        return None
    tr = prices.diff().abs()
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def adx(prices: pd.Series, n: int = 14) -> Optional[float]:
    """Simplified ADX from close-only data (directional strength proxy)."""
    if len(prices) < 2 * n + 1:
        return None
    up = prices.diff().clip(lower=0.0)
    dn = (-prices.diff()).clip(lower=0.0)
    tr = prices.diff().abs().ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * up.ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, np.nan)
    minus_di = 100 * dn.ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    val = dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return None if pd.isna(val) else float(val)


def zscore(prices: pd.Series, n: int = 20) -> Optional[float]:
    """Z-score of latest price vs its trailing n-bar mean/std."""
    if len(prices) < n:
        return None
    window = prices.tail(n)
    sd = float(window.std(ddof=0))
    if sd == 0:
        return None
    return float((prices.iloc[-1] - float(window.mean())) / sd)
