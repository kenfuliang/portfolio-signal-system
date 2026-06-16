"""Unit tests for the experiment ledger core (pure, no LEAN)."""
from __future__ import annotations

import json

import pytest

from strategy import experiment_log as el


def _rec(strategy="vol_target_momentum", universe="diversified", params=None,
         is_sharpe=-0.285, oos_sharpe=0.321, fitness=0.93, decay=-0.606,
         source="walk_forward", ts="2026-06-16T16:48:03Z"):
    return {
        "ts": ts, "source": source, "strategy": strategy, "universe": universe,
        "baseline": "momentum_12_1", "params": params or {"target_vol": 0.30, "regime_ma": 200},
        "splits": [
            {"name": "IS", "start": "2017-01-01", "end": "2021-06-30", "sharpe": is_sharpe},
            {"name": "OOS", "start": "2021-07-01", "end": "2026-06-16", "sharpe": oos_sharpe},
        ],
        "decay": decay, "fitness": fitness, "gate": "satellite",
        "hypothesis": "regime gate + vol targeting", "notes": "",
    }


def test_append_load_roundtrip(tmp_path):
    p = str(tmp_path / "experiments.jsonl")
    rid = el.append_experiment(_rec(), path=p)
    rows = el.load_experiments(path=p)
    assert len(rows) == 1
    assert rows[0]["run_id"] == rid
    assert rows[0]["strategy"] == "vol_target_momentum"
    assert rows[0]["splits"][1]["sharpe"] == 0.321


def test_append_never_clobbers_prior_rows(tmp_path):
    """The bug that lost the 24-strategy walk-forward: a new write must not
    overwrite earlier rows."""
    p = str(tmp_path / "experiments.jsonl")
    el.append_experiment(_rec(strategy="a", params={"x": 1}), path=p)
    el.append_experiment(_rec(strategy="b", params={"x": 2}), path=p)
    el.append_experiment(_rec(strategy="c", params={"x": 3}), path=p)
    rows = el.load_experiments(path=p)
    assert [r["strategy"] for r in rows] == ["a", "b", "c"]


def test_missing_required_field_raises(tmp_path):
    p = str(tmp_path / "experiments.jsonl")
    bad = _rec()
    del bad["strategy"]
    with pytest.raises(ValueError):
        el.append_experiment(bad, path=p)


def test_unknown_source_raises(tmp_path):
    p = str(tmp_path / "experiments.jsonl")
    with pytest.raises(ValueError):
        el.append_experiment(_rec(source="bogus"), path=p)


def test_run_id_is_deterministic_for_same_identity():
    a = _rec(ts="2026-01-01T00:00:00Z")
    b = _rec(ts="2026-01-01T00:00:00Z")
    b["fitness"] = 0.10            # metrics differ
    b["notes"] = "changed"
    assert el.make_run_id(a["ts"], a["strategy"], a) == el.make_run_id(b["ts"], b["strategy"], b)


def test_run_id_changes_with_params():
    a = _rec(params={"target_vol": 0.30}, ts="2026-01-01T00:00:00Z")
    b = _rec(params={"target_vol": 0.40}, ts="2026-01-01T00:00:00Z")
    assert el.make_run_id(a["ts"], a["strategy"], a) != el.make_run_id(b["ts"], b["strategy"], b)


def test_find_matches_exact_vs_strategy_universe(tmp_path):
    p = str(tmp_path / "experiments.jsonl")
    el.append_experiment(_rec(params={"target_vol": 0.30}), path=p)
    el.append_experiment(_rec(params={"target_vol": 0.40}), path=p)
    el.append_experiment(_rec(strategy="other", params={"target_vol": 0.30}), path=p)

    m = el.find_matches("vol_target_momentum", {"target_vol": 0.30}, "diversified", _rec()["splits"], path=p)
    assert len(m["exact"]) == 1
    assert len(m["same_strategy_universe"]) == 2   # both vol_target rows, ignoring params


def test_find_matches_respects_universe(tmp_path):
    p = str(tmp_path / "experiments.jsonl")
    el.append_experiment(_rec(universe="diversified"), path=p)
    el.append_experiment(_rec(universe="watchlist"), path=p)
    m = el.find_matches("vol_target_momentum", _rec()["params"], "watchlist", _rec()["splits"], path=p)
    assert len(m["same_strategy_universe"]) == 1
    assert m["same_strategy_universe"][0]["universe"] == "watchlist"


def test_load_skips_malformed_lines(tmp_path):
    p = tmp_path / "experiments.jsonl"
    p.write_text(json.dumps(_rec(strategy="ok")) + "\n" + "{ this is not json\n")
    rows = el.load_experiments(path=str(p))
    assert len(rows) == 1
    assert rows[0]["strategy"] == "ok"


def test_load_missing_file_returns_empty(tmp_path):
    assert el.load_experiments(path=str(tmp_path / "nope.jsonl")) == []


def test_best_per_group_ranks_fitness_then_decay(tmp_path):
    rows = [
        _rec(strategy="s", params={"x": 1}, fitness=0.5, decay=0.1),
        _rec(strategy="s", params={"x": 2}, fitness=0.9, decay=0.2),   # best fitness
        _rec(strategy="s", params={"x": 3}, fitness=0.9, decay=0.1),   # ties fitness, lower decay -> winner
    ]
    best = el.best_per_group(rows)
    winner = best[("s", "diversified")]
    assert winner["fitness"] == 0.9 and winner["decay"] == 0.1


def test_best_per_group_legacy_ranks_below_scored():
    rows = [
        _rec(strategy="s", params={"x": 1}, fitness=None, decay=None, source="legacy"),
        _rec(strategy="s", params={"x": 2}, fitness=0.1, decay=0.5),
    ]
    best = el.best_per_group(rows)
    assert best[("s", "diversified")]["fitness"] == 0.1   # scored beats legacy even at low fitness
