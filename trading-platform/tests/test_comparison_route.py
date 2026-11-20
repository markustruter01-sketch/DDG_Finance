"""The 2027 comparison: same days, server-computed returns (routes/comparison.py)."""

from __future__ import annotations

import pytest

from routes.comparison import race_view


def test_only_days_every_account_and_spy_share_are_used():
    equity = {"oracle": {"2026-11-03": 100.0, "2026-11-04": 101.0, "2026-11-05": 99.0},
              "spy_qqq_trend": {"2026-11-03": 200.0, "2026-11-05": 210.0},
              "jerome_macro": {"2026-11-03": 50.0, "2026-11-04": 50.0, "2026-11-05": 51.0}}
    spy = {"2026-11-02": 490.0, "2026-11-03": 500.0, "2026-11-04": 505.0, "2026-11-05": 510.0}
    out = race_view(equity, spy, "2026-11-03")
    assert [r["date"] for r in out["rows"]] == ["2026-11-03", "2026-11-05"]   # 4 Nov missing for Momentum
    assert out["accounts"]["oracle"]["return"] == pytest.approx(-0.01)
    assert out["accounts"]["spy_qqq_trend"]["return"] == pytest.approx(0.05)
    assert out["accounts"]["jerome_macro"]["spy_same_days"] == pytest.approx(0.02)
    assert out["rows"][0] == {"date": "2026-11-03", "spy": 0.0, "oracle": 0.0, "spy_qqq_trend": 0.0, "jerome_macro": 0.0}


def test_worst_fall_is_peak_to_trough_and_sharpe_waits_for_twenty_days():
    days = [f"2026-11-{d:02d}" for d in range(3, 8)]
    equity = {"oracle": dict(zip(days, [100.0, 110.0, 88.0, 99.0, 105.0]))}
    out = race_view(equity, {d: 500.0 for d in days}, "2026-11-03")
    assert out["accounts"]["oracle"]["worst_fall"] == pytest.approx(88 / 110 - 1)
    assert out["accounts"]["oracle"]["sharpe"] is None
    assert out["accounts"]["spy_qqq_trend"] is None          # no data yet: shown as —, not as zero


def test_nothing_before_two_common_days():
    out = race_view({"oracle": {"2026-11-03": 100.0}}, {"2026-11-03": 500.0}, "2026-11-03")
    assert out["rows"] == [] and out["days"] == 1 and out["spy"] is None


def test_fleet_sums_all_four_accounts_and_waits_for_forex():
    days = ["2026-11-06", "2026-11-09", "2026-11-10"]
    equity = {b: dict(zip(days, [100.0, 110.0, 99.0])) for b in ("oracle", "spy_qqq_trend", "jerome_macro")}
    spy = {d: 500.0 for d in days}
    assert race_view(equity, spy, "2026-11-06")["fleet"] is None                      # no Forex rows: no fleet figure
    equity["forex_ai"] = dict(zip(days, [100.0, 110.0, 99.0]))
    fleet = race_view(equity, spy, "2026-11-06")["fleet"]
    assert fleet["return"] == pytest.approx(-0.01) and fleet["worst_fall"] == pytest.approx(99 / 110 - 1)
    assert fleet["annual"] is None and fleet["volatility"] is None    # only from 20 days


def test_forex_is_a_line_in_the_comparison_on_the_same_days():
    from routes.comparison import ACCOUNTS, race_view

    assert "forex_ai" in ACCOUNTS
    days = ["2026-11-09", "2026-11-10", "2026-11-11"]
    equity = {b: dict(zip(days, [100.0, 101.0, 102.0])) for b in ("oracle", "spy_qqq_trend", "jerome_macro")}
    equity["forex_ai"] = {"2026-11-09": 100.0, "2026-11-11": 104.0}          # no close on the 10th
    out = race_view(equity, dict(zip(days, [500.0, 505.0, 510.0])), "2026-11-09")
    assert [r["date"] for r in out["rows"]] == ["2026-11-09", "2026-11-11"]    # same days for every line
    assert out["rows"][-1]["forex_ai"] == 0.04
    assert out["accounts"]["forex_ai"]["return"] == 0.04
