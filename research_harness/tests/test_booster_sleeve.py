"""BOOST-V1 sleeve and exploration script (synthetic data only)."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from research_harness.harness.portfolio import HistoryView
from research_harness.harness.store import BarStore
from research_harness.sleeves import booster as bs


def _calendar(n: int, start: date, weekdays_only: bool):
    out, d = [], start
    while len(out) < n:
        if not weekdays_only or d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(days, drift, vol, seed):
    rng, px, out = random.Random(seed), 100.0, []
    for d in days:
        o = px
        px *= math.exp(drift + rng.gauss(0, vol))
        out.append({"day": d, "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px})
    return out


def test_weekend_rolls_into_monday_and_its_low_is_kept():
    fri, sat, sun, mon = date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 5), date(2020, 1, 6)
    bars = [{"day": fri, "open": 10, "high": 11, "low": 9, "close": 10},
            {"day": sat, "open": 10, "high": 10, "low": 5, "close": 6},
            {"day": sun, "open": 6, "high": 8, "low": 6, "close": 7},
            {"day": mon, "open": 7, "high": 9, "low": 7, "close": 8}]
    out = bs.to_sessions(bars, [fri, mon])
    assert out[0] == {"day": fri, "open": 10, "high": 11, "low": 9, "close": 10}
    assert out[1] == {"day": mon, "open": 10, "high": 10, "low": 5, "close": 8}   # Sat open, weekend low


def test_missing_session_bar_rolls_into_the_next_session():
    d1, d2, d3 = date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8)
    bars = [{"day": d1, "open": 1, "high": 2, "low": 1, "close": 2},
            {"day": d3, "open": 3, "high": 4, "low": 0.5, "close": 3}]
    out = bs.to_sessions(bars, [d1, d2, d3])
    assert [b["day"] for b in out] == [d1, d3]


def test_candidate_a_always_holds_and_b_is_flat_in_a_downtrend():
    days = _calendar(400, date(2016, 1, 4), weekdays_only=True)
    down = _series(days, -0.003, 0.01, 1)
    view = HistoryView({bs.BTC: down})
    view.today = days[-1]
    a, b = bs.make_candidate("A"), bs.make_candidate("B")
    assert a(days[-1], view) == {bs.BTC: 1.0}
    assert b(days[-1], view) == {}                           # below its 210-session average
    assert a(days[-1], view) is None                         # once a month only


def test_candidate_c_splits_by_inverse_vol_when_both_trend():
    days = _calendar(400, date(2016, 1, 4), weekdays_only=True)
    view = HistoryView({bs.BTC: _series(days, 0.003, 0.01, 2), bs.ETH: _series(days, 0.003, 0.03, 3)})
    view.today = days[-1]
    w = bs.make_candidate("C")(days[-1], view)
    assert set(w) == {bs.BTC, bs.ETH} and w[bs.BTC] > w[bs.ETH] and abs(sum(w.values()) - 1) < 1e-9


def test_drawdown_gate_then_sharpe_then_simpler():
    def c(sharpe, mdd):
        return {"summary": {"sharpe_excess_tbill": sharpe, "max_drawdown_pct": mdd}}
    from research_harness.explore.boost_v1 import choose
    assert choose({"A": c(1.5, -80), "B": c(0.9, -30), "C": c(1.0, -40)}) == "C"
    assert choose({"A": c(1.0, -40), "B": c(1.0, -30), "C": c(0.5, -20)}) == "A"
    assert choose({"A": c(1.0, -60), "B": c(1.0, -51), "C": c(2.0, -90)}) is None


def test_exploration_runs_on_sessions_and_logs(tmp_path):
    from research_harness.explore import boost_v1

    store = BarStore(tmp_path / "data")
    sessions = _calendar(2600, date(2010, 1, 4), weekdays_only=True)
    etf = {s: _series(sessions, 0.0002 * (i % 3), 0.01, 10 + i) for i, s in enumerate(boost_v1.TREND_UNIVERSE)}
    store.write_dataset("etf", source="synthetic", bars_by_symbol=etf)
    cal = _calendar(2600 * 7 // 5, date(2013, 1, 1), weekdays_only=False)
    cal = [d for d in cal if d <= sessions[-1]]
    store.write_dataset("crypto", source="synthetic", bars_by_symbol={
        bs.BTC: _series(cal, 0.002, 0.04, 7),
        bs.ETH: _series([d for d in cal if d >= date(2017, 11, 9)], 0.002, 0.05, 8)})
    store.write_dataset("rates", source="synthetic", fields=("day", "rate"), positive_fields=(),
                        bars_by_symbol={"DTB3": [{"day": date(2010, 1, 1), "rate": 0.02}]})
    log = tmp_path / "log.jsonl"
    out = boost_v1.run("crypto", "etf", "rates", store, log_path=log)
    assert set(out["candidates"]) == {"A", "B", "C"}
    assert out["window"] == ["2015-01-01", "2020-12-31"]
    for c in out["candidates"].values():
        s = c["summary"]
        assert s["to"] <= "2020-12-31" and "stops_hit" in s and "correlation_to_trend_v1_b_explore" in s
        assert s["max_gross_leverage"] <= 1.0001
    assert out["chosen_for_registration"] in {"A", "B", "C", None}
    assert log.read_text().count("BOOST-V1") == 1
