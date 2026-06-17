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


def test_gross_exposure_cap_scales_down(risk_cfg):
    # 20 names at the 10% per-name cap = 200% gross -> must be scaled to the gross cap.
    cfg = {**risk_cfg, "diversification": {**risk_cfg["diversification"],
                                           "max_gross_exposure_pct": 0.95}}
    # spread across sleeves so per-sleeve caps don't bind first: 7 core (0.70) +
    # 4 satellite (0.40) = 1.10 gross, each sleeve within its cap.
    targets = {f"C{i}": 0.10 for i in range(7)}
    targets.update({f"S{i}": 0.10 for i in range(4)})
    sleeves = {k: ("core" if k.startswith("C") else "satellite") for k in targets}
    adj, notes = enforce_caps(targets, sleeves, {}, cfg)
    assert sum(adj.values()) <= 0.95 + 1e-9
    assert any("gross-exposure cap" in n for n in notes)


def test_gross_exposure_cap_disabled_when_null(risk_cfg):
    # null/absent gross cap must NOT scale a modest book (no phantom clamp).
    cfg = {**risk_cfg, "diversification": {**risk_cfg["diversification"],
                                           "max_gross_exposure_pct": None}}
    adj, notes = enforce_caps({"A": 0.10, "B": 0.10}, {"A": "core", "B": "core"}, {}, cfg)
    assert adj == {"A": 0.10, "B": 0.10}
    assert not any("gross" in n for n in notes)


def test_sleeve_cap_clamps(risk_cfg):
    # three names each at 10% in core (cap 0.70) is fine; push core over 0.70
    targets = {f"C{i}": 0.10 for i in range(8)}          # 0.80 total in core
    sleeves = {k: "core" for k in targets}
    adj, notes = enforce_caps(targets, sleeves, {}, risk_cfg)
    assert sum(adj.values()) <= risk_cfg["sleeves"]["core"]["max"] + 1e-9


def test_circuit_breaker_trips_on_deep_drawdown(risk_cfg):
    assert circuit_breaker_tripped(84_000, 100_000, risk_cfg) is True   # -16%
    assert circuit_breaker_tripped(90_000, 100_000, risk_cfg) is False  # -10%
