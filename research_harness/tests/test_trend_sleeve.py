"""Tests for the TREND-V1 sleeve and its exploration script."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta

import pytest

from research_harness.harness.costs import CostModel
from research_harness.harness.holdout import EXPLORE_END
from research_harness.harness.portfolio import HistoryView, simulate
from research_harness.harness.store import BarStore
from research_harness.sleeves.trend import RULES, TrendParams, make_strategy, target_weights

FREE = CostModel(0, 0, 0, 0, 0)


def weekdays(n: int, start: date = date(2010, 1, 4)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def series(n: int, drift: float, vol: float, seed: int, start: date = date(2010, 1, 4)):
    rng, px, out = random.Random(seed), 100.0, []
    for d in weekdays(n, start):
        o = px
        px *= math.exp(drift + rng.gauss(0, vol))
        out.append({"day": d, "open": o, "high": max(o, px), "low": min(o, px), "close": px})
    return out


def view_at(bars, day):
    v = HistoryView(bars)
    v.today = day
    return v


def test_unknown_rule_is_refused():
    with pytest.raises(ValueError, match="declared rules"):
        TrendParams(rule="tsmom_200")


@pytest.mark.parametrize("rule", sorted(RULES))
def test_uptrend_on_downtrend_off(rule):
    bars = {"UP": series(400, 0.002, 0.005, 1), "DOWN": series(400, -0.002, 0.005, 2)}
    w = target_weights(view_at(bars, bars["UP"][-1]["day"]), ["UP", "DOWN"], TrendParams(rule=rule))
    assert w.get("UP", 0) > 0 and "DOWN" not in w


def test_inverse_vol_weights_cap_and_cash_share():
    bars = {"CALM": series(400, 0.002, 0.003, 3), "WILD": series(400, 0.002, 0.012, 4),
            "OFF": series(400, -0.002, 0.003, 5)}
    w = target_weights(view_at(bars, bars["CALM"][-1]["day"]), list(bars),
                       TrendParams(rule="tsmom_252", max_weight=1.0))
    assert w["CALM"] > w["WILD"]                      # lower vol, bigger weight
    assert sum(w.values()) < 1.0                      # OFF's share stays in cash
    capped = target_weights(view_at(bars, bars["CALM"][-1]["day"]), list(bars),
                            TrendParams(rule="tsmom_252", max_weight=0.2))
    assert max(capped.values()) <= 0.2 + 1e-12


def test_not_eligible_without_enough_history_or_todays_bar():
    full = series(400, 0.002, 0.005, 6)
    young = series(100, 0.002, 0.005, 7, start=full[300]["day"])
    stale = full[:-5]
    bars = {"FULL": full, "YOUNG": young, "STALE": stale}
    w = target_weights(view_at(bars, full[-1]["day"]), list(bars), TrendParams(rule="tsmom_252"))
    assert set(w) == {"FULL"}


def test_rebalances_once_a_month_and_stays_long_only():
    bars = {"UP": series(500, 0.001, 0.008, 8), "DN": series(500, -0.001, 0.008, 9)}
    strat = make_strategy(list(bars), TrendParams(rule="blend_63_126_252"))
    calls = []

    def spy(day, view):
        w = strat(day, view)
        if w is not None:
            calls.append(day)
            assert all(x >= 0 for x in w.values()) and sum(w.values()) <= 1 + 1e-12
        return w

    simulate(bars, spy, costs=FREE, rf_annual=None, start=bars["UP"][0]["day"], end=EXPLORE_END)
    months = [(d.year, d.month) for d in calls]
    assert len(months) == len(set(months))           # at most one rebalance per month


def test_exploration_runs_and_logs(tmp_path):
    from research_harness.explore import trend_v1

    store = BarStore(tmp_path / "data")
    etfs = {s: series(1800, 0.0003 * (i % 3 - 1), 0.01, 10 + i, start=date(2005, 1, 3))
            for i, s in enumerate(trend_v1.UNIVERSE)}
    store.write_dataset("etf", source="synthetic", bars_by_symbol=etfs)
    store.write_dataset("rates", source="synthetic", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": date(2004, 12, 31), "rate": 0.02}]})
    log = tmp_path / "log.jsonl"
    out = trend_v1.run("etf", "rates", store, log_path=log)
    assert set(out["candidates"]) == {"A", "B", "C"}
    assert out["chosen_for_registration"] in {"A", "B", "C"}
    for c in out["candidates"].values():
        s = c["summary"]
        assert s["to"] <= EXPLORE_END.isoformat() and "sharpe_excess_tbill" in s
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["plan"] == "TREND-V1" and entry["data"]["etf"][0] == "etf"
