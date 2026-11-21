"""Roadmap v2 macro state (V2-06) and the four daily flags (V2-19): votes, label,
the five-session rule and every flag checked by hand on made-up prices; the
flags are read by no rule (rule 10); the table is append-only. No network."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path

import pytest

import twins  # noqa: F401
from research_harness.harness.portfolio import HistoryView
from research_harness.league import allocator as alloc
from research_harness.league import macro_state as ms
from test_league import CAL, bars_from, steady
from twins import store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

UP, DOWN, FLAT = 0.001, -0.001, 0.0
DAY = date(2026, 11, 2)


def market(**rates):
    """Every macro symbol, flat unless given a daily rate."""
    return {s: bars_from(steady(rates.get(s, FLAT), wiggle=0.002)) for s in ms.SYMBOLS}


def view(bars, day=DAY):
    v = HistoryView(bars)
    v.today = day
    return v


@pytest.mark.parametrize("rates, label", [
    ({"SPY": UP, "IWM": UP, "HYG": UP, "DBC": DOWN, "USO": DOWN, "TIP": DOWN}, "goldilocks"),
    ({"SPY": UP, "IWM": UP, "HYG": DOWN, "DBC": UP, "USO": UP, "TIP": UP}, "reflation"),
    ({"SPY": DOWN, "IWM": DOWN, "HYG": UP, "DBC": UP, "USO": UP, "TIP": DOWN}, "stagflation"),
    ({"SPY": DOWN, "IWM": UP, "HYG": DOWN, "DBC": DOWN, "USO": UP, "TIP": DOWN}, "bust"),
])
def test_votes_and_label_by_hand(rates, label):
    v = ms.votes(view(market(**rates)))
    # IEF is flat, so HYG / IEF and TIP / IEF follow HYG and TIP
    assert v == {"spy": rates["SPY"] > 0, "iwm": rates["IWM"] > 0, "hyg_ief": rates["HYG"] > 0,
                 "dbc": rates["DBC"] > 0, "uso": rates["USO"] > 0, "tip_ief": rates["TIP"] > 0}
    assert ms.raw_label(v) == label


def test_ratio_votes_compare_the_two_funds_not_each_alone():
    v = ms.votes(view(market(HYG=UP, IEF=UP * 2, TIP=DOWN, SPY=UP, IWM=UP, DBC=UP, USO=UP)))
    assert v["hyg_ief"] is False            # risky bonds rose, but safe bonds rose faster
    assert v["tip_ief"] is False


def test_a_missing_fund_means_no_label():
    bars = market()
    del bars["IWM"]
    assert ms.votes(view(bars)) is None


def test_five_session_rule():
    raw = ["bust"] * 5 + ["reflation"] * 4 + ["bust"] + ["reflation"] * 5
    got = ms.confirm(raw)
    assert got[:4] == [None] * 4                         # nothing has held 5 sessions yet
    assert got[4] == "bust"
    assert got[5:9] == ["bust"] * 4                      # reflation for 4 sessions: bust still stands
    assert got[9] == "bust"
    assert got[10:14] == ["bust"] * 4
    assert got[14] == "reflation"                        # the 5th reflation session in a row


def test_label_on_walks_history_and_keeps_yesterdays_label():
    bars = market(SPY=UP, IWM=UP, HYG=UP, DBC=DOWN, USO=DOWN, TIP=DOWN)      # goldilocks for years
    v = view(bars)
    assert ms.label_on(v, CAL, DAY) == ("goldilocks", "goldilocks")
    assert v.today == DAY                                                   # the walk restores the view


def test_fast_and_slow_sell_off_by_hand():
    s = ms.flags(view(market(SPY=DOWN, TLT=DOWN, UUP=DOWN)))
    assert s["sell_off_fast"] is True and s["sell_off_slow"] is True
    s = ms.flags(view(market(SPY=DOWN, TLT=DOWN, UUP=UP)))                  # the dollar rose: money moved, not left
    assert s["sell_off_fast"] is False and s["sell_off_slow"] is False


def test_fast_flag_reads_21_sessions_back_exactly():
    c = [100.0] * 300
    c[-22] = 101.0                                      # 21 sessions before today
    bars = {sym: bars_from(c) for sym in ("SPY", "TLT", "UUP")}
    assert ms.flags(view(bars, CAL[-1]))["sell_off_fast"] is True
    c[-22] = 99.0
    bars = {sym: bars_from(c) for sym in ("SPY", "TLT", "UUP")}
    assert ms.flags(view(bars, CAL[-1]))["sell_off_fast"] is False


def test_hard_assets_lead_and_tight_money_by_hand():
    f = ms.flags(view(market(GLD=UP, DBC=UP, SPY=FLAT, TIP=DOWN, UUP=UP)))
    assert f["hard_assets_lead"] is True and f["tight_money"] is True
    f = ms.flags(view(market(GLD=UP, DBC=DOWN, SPY=FLAT, TIP=UP, UUP=UP)))
    assert f["hard_assets_lead"] is False and f["tight_money"] is False


def test_side_measures_by_hand_and_rough_is_the_allocator_v1_measure():
    n = len(CAL)
    spy = [100 * 1.0004 ** i * (1.01 if i % 2 else 0.99) for i in range(n)]
    ief = [100 * (0.995 if i % 2 else 1.005) for i in range(n)]        # moves against SPY every day
    bars = market()
    bars["SPY"], bars["IEF"] = bars_from(spy), bars_from(ief)
    s = ms.side(view(bars))
    assert s["bonds_hedging"] is True and s["spy_ief_corr63"] < -0.9
    m = alloc.measurements(view(bars), ("SPY",))                        # the Allocator's own numbers
    assert s["rough"] == (m["vol20"] > m["vol20_median"])


def test_no_fund_or_table_reads_the_flags():
    """Roadmap v2, rule 10: the flags are context only."""
    root = Path(__file__).resolve().parents[2]
    files = [root / "research_harness" / "league" / "allocator.py", root / "research_harness" / "league" / "families.py",
             root / "trading-platform" / "twins" / "allocator.py", root / "research_harness" / "league" / "funds_v2.py"]
    pattern = re.compile("|".join(ms.FLAGS + ("long_cycle",)))
    for f in files:
        if f.exists():
            assert not pattern.search(f.read_text()), f.name


@needs_pg
def test_macro_state_is_written_once_and_never_changed():
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    row = ms.state(view(market(SPY=UP, IWM=UP, HYG=UP)), CAL, DAY)
    now = datetime.combine(DAY, time(17, 15), NEW_YORK)
    assert store.record_macro_state(get_conn, DAY, row, now) is True
    assert store.record_macro_state(get_conn, DAY, {**row, "label": "bust"}, now) is False    # first one kept
    got = store.macro_states(get_conn)
    assert len(got) == 1 and got[0]["label"] == row["label"] and set(got[0]["flags"]) == set(ms.FLAGS)
    with pytest.raises(Exception):
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE macro_state SET label = 'bust'")


def test_the_read_only_check_prints_every_session_in_range():
    from datetime import timezone

    from twins import macro_check

    def fetch(symbols, start):
        return {s: [b for b in market(SPY=DOWN, TLT=DOWN, UUP=DOWN)[s] if b["day"] >= start] for s in symbols}

    got = macro_check.rows(date(2026, 10, 1), date(2026, 10, 30), fetch=fetch,
                           now=datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert [r["day"] for r in got] == [d for d in CAL if date(2026, 10, 1) <= d <= date(2026, 10, 30)]
    assert all(r["flags"]["sell_off_fast"] and r["flags"]["sell_off_slow"] for r in got)
