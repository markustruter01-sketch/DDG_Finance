"""Live versus research (sleeve_runtime/live_check.py): pure, no network, no DB."""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone

from sleeve_runtime import fleet_live as fl
from sleeve_runtime import live_check as lc
from sleeve_runtime.tests.test_fleet_live import _bars, _series

DAY = date(2026, 10, 22)
AFTER_CLOSE = datetime(2026, 10, 22, 22, 0, tzinfo=timezone.utc)   # 18:00 New York


def _fetcher(bars):
    def fetch(symbols, start):
        return {s: copy.deepcopy(bars.get(s, [])) for s in symbols}
    return fetch


def test_same_bars_agree_and_raise_no_flags():
    bars = _bars(end=DAY)
    row = lc.check_account("oracle", live_fetch=_fetcher(bars), research_fetch=_fetcher(bars),
                           state={"targets": {"SPY": 0.5}}, equity=1000,
                           positions=[{"symbol": "SPY", "value_usd": 500}, {"symbol": "BIL", "value_usd": 0}],
                           now=AFTER_CLOSE, vault={"BIL", "VOO"}, cash_park={"SGOV"})
    assert row["kind"] == "FLEET-V1-F1" and row["day"] == DAY.isoformat()
    assert row["votes_agree"] and row["weight_gap"] == 0 and row["flags"] == []
    assert row["holdings"] == {"SPY": 0.5} and row["holdings_vs_last_targets"] == 0


def test_a_feed_gap_and_a_signal_split_are_flagged():
    live = _bars(end=DAY)
    research = copy.deepcopy(live)
    for b in research["SPY"][-60:]:               # research SPY falls away: fewer votes
        b["close"] *= 0.8
    research["GLD"][-1]["close"] *= 1.01          # one close 1% apart
    row = lc.check_account("jerome_macro", live_fetch=_fetcher(live), research_fetch=_fetcher(research),
                           state={}, equity=1000, positions=[], now=AFTER_CLOSE,
                           vault={"BIL", "VOO"}, cash_park={"SGOV"})
    assert row["kind"] == "FLEET-V1-C1"
    assert row["votes_agree"] is False and "votes differ between feeds" in row["flags"]
    assert any("close gap" in f and "SPY" in f for f in row["flags"])


def test_momo_split_missed_by_one_feed_shows_on_the_name():
    names = ["AAA", "BBB"]
    live = {"SPY": _series(DAY, 400, 0.001, 0.002), "AAA": _series(DAY, 50, 0.001, 0.003),
            "BBB": _series(DAY, 80, 0.0005, 0.003)}
    research = copy.deepcopy(live)
    for b in live["BBB"][:-30]:                   # live feed: BBB's 2:1 split not adjusted
        b["close"] *= 2
    state = {"names": names, "selection_day": live["SPY"][-40]["day"].isoformat()}
    row = lc.check_account("spy_qqq_trend", live_fetch=_fetcher(live), research_fetch=_fetcher(research),
                           state=state, equity=1000, positions=[], now=AFTER_CLOSE,
                           vault={"BIL", "VOO"}, cash_park={"SGOV"})
    assert row["kind"] == "MOMO-V2" and row["name_gaps"][0]["symbol"] == "BBB"
    assert row["name_gaps"][0]["gap"] == 0.5          # half after the split, relative to selection day
    assert row["sma_gap"] > 0.01 and any("BBB" in f for f in row["flags"])


def test_errors_become_the_row_and_the_month_counts_them():
    def broken(symbols, start):
        raise RuntimeError("feed down")
    row = lc.check_account("oracle", live_fetch=broken, research_fetch=broken, state={}, equity=1,
                           positions=[], now=AFTER_CLOSE, vault=set(), cash_park=set())
    assert row["flags"] == ["check failed: RuntimeError: feed down"]
    ok = {"kind": "FLEET-V1-F1", "flags": [], "votes_agree": True, "weight_gap": 0.0, "alpaca_feed": "sip"}
    s = lc.monthly_summary([{"bot_id": "oracle", "day": DAY, "payload": ok},
                            {"bot_id": "oracle", "day": DAY, "payload": row}], "2026-10")
    b = s["bots"]["oracle"]
    assert b["days"] == 2 and b["days_flagged"] == 1 and b["alpaca_feeds"] == ["sip"]
    assert lc.summary_lines(s)[0].startswith("oracle (FLEET-V1-F1): 2 days, 1/2 days flagged")


def test_variant_map_matches_the_live_wiring():
    assert lc.SLEEVES["oracle"] is fl.F1 and lc.SLEEVES["jerome_macro"] is fl.C1


def test_missing_research_data_is_flagged_never_read_as_agreement():
    bars = _bars(end=DAY)
    row = lc.check_account("oracle", live_fetch=_fetcher(bars), research_fetch=_fetcher({}),
                           state={}, equity=1000, positions=[], now=AFTER_CLOSE,
                           vault={"BIL", "VOO"}, cash_park={"SGOV"})
    assert "no signal from the research feed" in row["flags"]
    live = {"SPY": _series(DAY, 400, 0.001, 0.002), "AAA": _series(DAY, 50, 0.001, 0.003)}
    state = {"names": ["AAA"], "selection_day": live["SPY"][-40]["day"].isoformat()}
    row = lc.check_account("spy_qqq_trend", live_fetch=_fetcher(live), research_fetch=_fetcher({}),
                           state=state, equity=1000, positions=[], now=AFTER_CLOSE,
                           vault={"BIL", "VOO"}, cash_park={"SGOV"})
    assert "no book index from the research feed" in row["flags"]
    assert "1 names without prices on both feeds" in row["flags"]
