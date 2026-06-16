"""Black-Scholes pricer sanity (pure)."""
import math

from strategy.options import bs_call_price, bs_put_price, bs_call_delta


def test_intrinsic_at_expiry():
    assert bs_call_price(110, 100, 0.0, 0.2) == 10.0
    assert bs_call_price(90, 100, 0.0, 0.2) == 0.0
    assert bs_put_price(90, 100, 0.0, 0.2) == 10.0


def test_put_call_parity():
    # C - P = S - K e^{-rT}
    S, K, T, sig, r = 100, 100, 0.5, 0.25, 0.02
    c = bs_call_price(S, K, T, sig, r)
    p = bs_put_price(S, K, T, sig, r)
    assert abs((c - p) - (S - K * math.exp(-r * T))) < 1e-9


def test_atm_call_positive_and_monotonic_in_vol():
    low = bs_call_price(100, 100, 0.25, 0.10)
    high = bs_call_price(100, 100, 0.25, 0.40)
    assert 0 < low < high                      # more vol -> more premium


def test_delta_bounds_and_moneyness():
    deep_itm = bs_call_delta(150, 100, 0.5, 0.2)
    deep_otm = bs_call_delta(60, 100, 0.5, 0.2)
    assert deep_itm > 0.9 and deep_otm < 0.1   # ITM ~1, OTM ~0
    assert 0.0 <= deep_otm <= deep_itm <= 1.0
