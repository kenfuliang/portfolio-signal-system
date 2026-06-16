"""Risk layer: sizing, caps, circuit breaker."""
from strategy.risk import position_size, enforce_caps, circuit_breaker_tripped


def test_position_size_respects_max_position(risk_cfg):
    res = position_size(100_000, 100.0, 1.0, "satellite", risk_cfg)
    assert 0 < res.target_weight <= risk_cfg["sizing"]["max_position_pct"] + 1e-9


def test_position_size_higher_atr_means_smaller_position(risk_cfg):
    low = position_size(100_000, 100.0, 0.5, "satellite", risk_cfg)
    high = position_size(100_000, 100.0, 5.0, "satellite", risk_cfg)
    assert high.target_weight <= low.target_weight


def test_per_name_cap_clamps(risk_cfg):
    adj, notes = enforce_caps({"AAA": 0.95}, {"AAA": "core"}, {}, risk_cfg)
    assert adj["AAA"] == risk_cfg["diversification"]["max_per_name_pct"]
    assert any("name cap" in n for n in notes)


def test_sleeve_cap_clamps(risk_cfg):
    # three names each at 10% in core (cap 0.70) is fine; push core over 0.70
    targets = {f"C{i}": 0.10 for i in range(8)}          # 0.80 total in core
    sleeves = {k: "core" for k in targets}
    adj, notes = enforce_caps(targets, sleeves, {}, risk_cfg)
    assert sum(adj.values()) <= risk_cfg["sleeves"]["core"]["max"] + 1e-9


def test_circuit_breaker_trips_on_deep_drawdown(risk_cfg):
    assert circuit_breaker_tripped(84_000, 100_000, risk_cfg) is True   # -16%
    assert circuit_breaker_tripped(90_000, 100_000, risk_cfg) is False  # -10%
