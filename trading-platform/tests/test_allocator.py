"""Allocator in shadow (roadmap Phase 3, rules): label, table, limits and the
15% stop by hand; labels written once; a night end to end. No network."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

import twins  # noqa: F401
from research_harness.league import allocator as A
from twins import store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg


def test_label_by_hand():
    m = {"spy_above_trend": True, "breadth": 0.40, "ief_60d": 0.01, "vol20": 0.12, "vol20_median": 0.15}
    assert A.label(m) == "calm up"                       # 2 of 3 up votes, vol below its median
    assert A.label({**m, "ief_60d": -0.01}) == "calm down"
    assert A.label({**m, "vol20": 0.20}) == "rough up"


def test_table_rows_add_to_one_and_no_family_is_missing():
    for lab, row in A.TABLE.items():
        assert set(row) == set(A.FAMILIES) and sum(row.values()) == pytest.approx(1.0), lab


def test_table_weights_split_a_family_equally_and_send_a_missing_family_to_cash():
    fams = {"T-1X": "trend", "T-2X": "trend", "S-DEF": "stocks", "D-RP": "diversifier", "ST-DIP": "short_term"}
    w = A.table_weights("calm up", fams)
    assert w["T-1X"] == w["T-2X"] == pytest.approx(0.175)
    assert w["S-DEF"] == pytest.approx(0.35)
    assert w["Y-CASH"] == pytest.approx(0.10)              # no forex line: its 10% waits in cash
    assert sum(w.values()) == pytest.approx(1.0)


def test_limits_cap_a_line_at_40_percent_and_exposure_at_1_5x():
    w = A.limited({"A": 0.7, "B": 0.3}, {"A": 1.0, "B": 1.0})
    assert w == {"A": 0.4, "B": 0.3, "Y-CASH": 0.3}
    geared = A.limited({"A": 0.4, "B": 0.4, "C": 0.2}, {"A": 2.0, "B": 2.0, "C": 1.0})   # 1.8x before
    assert sum(geared[i] * e for i, e in (("A", 2.0), ("B", 2.0), ("C", 1.0))) == pytest.approx(1.5)
    assert sum(geared.values()) == pytest.approx(1.0)
    assert A.line_exposure({"SSO": 0.5, "SPY": 0.3, "BIL": 0.2}) == pytest.approx(1.3)
    assert A.line_exposure({"EUR_USD": -0.6, "JPY_USD": 0.4}) == pytest.approx(1.0)


DAYS = [date(2026, 11, 2) + timedelta(days=i) for i in range(40) if (date(2026, 11, 2) + timedelta(days=i)).weekday() < 5]


def test_fund_earns_the_next_day_and_pays_for_switching():
    fams = {"T-1X": "trend", "S-DEF": "stocks", "D-RP": "diversifier"}
    flat = {d: 0.0 for d in DAYS}
    rets = {"T-1X": {d: 0.01 for d in DAYS}, "S-DEF": flat, "D-RP": flat, "Y-CASH": flat}
    res = A.run_fund("equal", DAYS[:3], {d: "calm up" for d in DAYS}, rets, fams, {})
    e = [x for _, x in res["curve"]]
    assert e[0] == pytest.approx(1 - 0.0005)                         # bought at the first close: 5 bps
    assert e[1] == pytest.approx(e[0] * (1 + 0.01 / 3))              # a third in a line that made 1%
    two = A.run_fund("equal", DAYS[:2], {d: "calm up" for d in DAYS}, rets, {"T-1X": "trend", "S-DEF": "stocks"}, {})
    assert two["decisions"][0]["weights"] == {"T-1X": 0.4, "S-DEF": 0.4, "Y-CASH": 0.2}   # the 40% cap
    assert len(res["decisions"]) == 1                                 # no rebalance mid-month


def test_rules_fund_moves_on_a_label_change_and_the_15_percent_stop_is_final():
    fams = {"T-1X": "trend", "D-RP": "diversifier"}
    labels = {d: ("calm up" if d < DAYS[5] else "rough down") for d in DAYS}
    crash = {d: (-0.08 if DAYS[8] <= d <= DAYS[12] else 0.0) for d in DAYS}   # 55% invested: about -35%
    rets = {"T-1X": crash, "D-RP": crash, "Y-CASH": {d: 0.0 for d in DAYS}}
    res = A.run_fund("rules", DAYS, labels, rets, fams, {})
    labs = [x["label"] for x in res["decisions"]]
    assert labs[:2] == ["calm up", "rough down"]
    assert res["tripped"] is not None and labs[-1] == "stopped: 15% fall"
    after = [x for d, x in res["curve"] if d > res["tripped"]]
    assert max(after) == pytest.approx(min(after))                    # all cash from then on
    assert res["decisions"][-1]["weights"] == {"Y-CASH": 1.0}


@needs_pg
def test_labels_written_once_and_the_funds_show_on_the_board():
    from test_league import LIVE_CAL, fake_fetch, fake_fx_now, fake_universe
    from test_twins_job import _platform_tables
    from twins import allocator, job, leaderboard, league

    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    _platform_tables(get_conn)
    alarms = []
    for day in LIVE_CAL[-3:]:
        job.nightly(datetime.combine(day, time(17, 15), NEW_YORK), record_fx_rates=lambda g, n: 0, get_conn=get_conn, fetch_daily=fake_fetch,
                    universe_loader=fake_universe, fetch_fx_daily=fake_fx_now, fetch_hourly=lambda p, s: {},
                    alarm=lambda *a, **k: alarms.append(a), resolve=lambda *a: None, commit="abc1234")
    labs = store.labels(get_conn)
    assert [r["day"] for r in labs] == list(LIVE_CAL[-3:])
    assert all(r["label"] in A.LABELS for r in labs)
    assert not store.record_label(get_conn, labs[0]["day"], "rough down", {}, datetime.now(NEW_YORK))  # once
    with get_conn() as conn, conn.cursor() as cur, pytest.raises(Exception, match="append-only"):
        cur.execute("UPDATE allocator_labels SET label = 'x'")
    board = leaderboard.read(get_conn)
    assert board["regime"] == labs[-1]["label"]
    funds = {r["id"]: r for r in board["rows"] if r["kind"] == "allocator"}
    assert set(funds) == {"ALLOC-EQUAL", "ALLOC-RULES"} and all(f["days"] >= 2 for f in funds.values())
    assert not [a for a in alarms if a[1] in ("allocator_check_failed", "league_failed")], alarms
    del league, allocator
