"""Pure tests for scripts/experiments.py (no LEAN/Docker).

Covers: percent coercion, leaderboard ranking, backfill idempotency.
"""
import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import experiments as ex  # noqa: E402
from strategy.experiment_log import load_experiments  # noqa: E402


def test_coerce_pct():
    assert ex.coerce_pct("15.657%") == pytest.approx(15.657)
    assert ex.coerce_pct("0.237") == pytest.approx(0.237)
    assert ex.coerce_pct(0.32) == pytest.approx(0.32)
    assert ex.coerce_pct(None) is None
    assert ex.coerce_pct("") is None
    assert ex.coerce_pct("n/a") is None
    assert ex.coerce_pct("28%") == pytest.approx(28.0)


def test_leaderboard_picks_highest_fitness_per_group():
    rows = [
        {"run_id": "a", "strategy": "s", "universe": "u", "fitness": 0.5,
         "decay": 0.1, "splits": [{"name": "OOS", "sharpe": 0.5}]},
        {"run_id": "b", "strategy": "s", "universe": "u", "fitness": 0.9,
         "decay": 0.2, "splits": [{"name": "OOS", "sharpe": 0.8}]},
        {"run_id": "c", "strategy": "s", "universe": "u", "fitness": None,
         "decay": None, "splits": [{"name": "OOS", "sharpe": 0.1}]},
    ]
    md = ex.build_leaderboard_md(rows)
    # Best per group is the highest-fitness 'b'; 'a' and 'c' are not group winners.
    assert "| b |" in md
    assert "| a |" not in md
    # legacy-only 'c' is dominated within its group, so absent
    assert "| c |" not in md


def test_leaderboard_legacy_ranks_below_scored():
    rows = [
        {"run_id": "scored", "strategy": "s1", "universe": "u", "fitness": 0.4,
         "decay": 0.0, "splits": [{"name": "OOS", "sharpe": 0.3}]},
        {"run_id": "legacy", "strategy": "s2", "universe": "u", "fitness": None,
         "decay": None, "splits": [{"name": "OOS", "sharpe": 0.9}]},
    ]
    md = ex.build_leaderboard_md(rows)
    assert md.index("scored") < md.index("legacy")


def test_backfill_is_idempotent(tmp_path):
    # Build minimal legacy files.
    rdir = tmp_path / "reports"
    rdir.mkdir()
    (rdir / "tournament_diversified.json").write_text(json.dumps({
        "trend_ma": {"stats": {"Compounding Annual Return": "6.680%",
                               "Sharpe Ratio": "0.237", "Drawdown": "14.000%",
                               "Portfolio Turnover": "8.32%"}},
    }))
    (rdir / "walkforward.json").write_text(json.dumps({
        "vol_target_momentum": {"in_sample": {"cagr": -0.16, "sharpe": -0.285, "dd": 15.1},
                                "out_sample": {"cagr": 10.5, "sharpe": 0.321, "dd": 18.7},
                                "sharpe_decay": -0.606},
    }))
    (rdir / "baselines.json").write_text(json.dumps({
        "SPY": {"cagr": 14.1, "sharpe": 0.53, "maxdd": 32.5, "role": "market"},
        "QQQ": {"cagr": 20.2, "sharpe": 0.68, "maxdd": 34.5},
        "TQQQ": {"cagr": 37.9, "sharpe": 0.77, "maxdd": 81.3},
    }))
    ledger = tmp_path / "experiments.jsonl"

    n1 = ex.run_backfill(reports_dir=str(rdir), path=str(ledger))
    count1 = len(load_experiments(str(ledger)))
    n2 = ex.run_backfill(reports_dir=str(rdir), path=str(ledger))
    count2 = len(load_experiments(str(ledger)))

    assert n1 == count1 == 5      # 1 tournament + 1 wf + 3 baselines
    assert n2 == 0                 # second run appends nothing
    assert count2 == count1        # row count unchanged


def test_backfill_records_coerces_and_shapes():
    recs = ex.backfill_records([])
    assert recs == []
