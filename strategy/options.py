"""Black-Scholes option pricing — pure, dependency-light, unit-testable.

Used for RESEARCH prototyping only: we price QQQ options analytically from the
underlying price + a volatility estimate, because we have no historical option
data. This is approximate — no IV skew/smile, no bid-ask, no early exercise, no
dividends. A strategy that looks good here must be re-validated on real option
data before it is trusted (see docs/rules/experiments.md).
"""
from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_price(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """European call price. S=spot, K=strike, T=years to expiry, sigma=annual vol."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)                      # intrinsic at/after expiry
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_put_price(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_call_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Call delta (∂price/∂S), in [0, 1]. Useful for sizing exposure."""
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1)
