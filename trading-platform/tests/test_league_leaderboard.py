"""Shadow League leaderboard: figures checked by hand, then read from a
throwaway Postgres after two league nights. No network."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

import twins  # noqa: F401
from twins import leaderboard as lb
from twins import league, store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

D = [date(2026, 11, 16) + timedelta(days=i) for i in range(4)]   # Mon-Thu


def test_figures_by_hand():
    lines = [
        {"id": "Y-SPX", "name": "S&P", "kind": "yardstick", "family": "yardstick", "start_equity": 100.0,
         "curve": list(zip(D, [100.0, 102.0, 101.0, 104.0])), "decisions": [(D[0], {"SPY": 1.0})]},
        {"id": "T-1X", "name": "trend", "kind": "shadow", "family": "trend", "start_equity": 100.0,
         "curve": list(zip(D, [100.0, 110.0, 99.0, 105.0])),
         "decisions": [(D[0], {"BIL": 1.0}), (D[2], {"SPY": 1.0})]},
        {"id": "oracle", "name": "Atlas", "kind": "real", "family": "real account", "start_equity": None,
         "curve": list(zip(D, [200.0, 200.0, 190.0, 210.0]))},
    ]
    rows = {r["id"]: r for r in lb.build(lines, n_trials=13)}
    t = rows["T-1X"]
    assert t["return_pct"] == 5.0                       # 105 / 100 - 1
    assert t["worst_fall_pct"] == -10.0                 # 110 -> 99
    assert t["days_in_cash"] == 2                       # 16 and 17 Nov held only BIL
    assert t["gap_to_spx_pp"] == 1.0                    # +5% vs +4%
    assert t["luck"] == "too few days"
    a = rows["oracle"]
    assert a["return_pct"] == 5.0 and a["worst_fall_pct"] == -5.0 and a["days_in_cash"] is None
    assert rows["Y-SPX"]["gap_to_spx_pp"] is None
    assert [r["kind"] for r in lb.build(lines, 13)] == ["real", "yardstick", "shadow"]


def test_luck_check_needs_enough_days_and_uses_the_trial_count():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(lb.MIN_LUCK_DAYS + 2)]
    steady = [100 * 1.002 ** i * (1.003 if i % 2 else 0.997) for i in range(len(days))]
    noisy = [100 * (1.02 if i % 2 else 0.98) for i in range(len(days))]
    lines = [{"id": sid, "name": sid, "kind": "shadow", "family": "trend", "start_equity": 100.0,
              "curve": list(zip(days, c)), "decisions": []} for sid, c in (("A", steady), ("B", noisy))]
    rows = {r["id"]: r for r in lb.build(lines, n_trials=2)}
    assert rows["A"]["luck"] == "clear" and rows["A"]["dsr"] >= lb.LUCK_CLEAR
    assert rows["B"]["luck"] == "could be luck"


@needs_pg
def test_read_from_the_twins_tables_after_two_nights():
    from test_league import fake_fetch, fake_universe

    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    for day in (date(2026, 11, 17), date(2026, 11, 18)):
        now = datetime.combine(day, time(17, 15), NEW_YORK)
        league.run(get_conn, now, day, fetch_daily=fake_fetch, universe_loader=fake_universe)
    # Value the lines as the twins job would (replay), then read the board.
    from twins import engine, job
    for acct in store.accounts(get_conn):
        rows = store.decisions(get_conn, acct["twin_id"])
        need = {s for r in rows for s in (r["weights"] or {})} | {"SPY"}
        res = job.replay_twin(get_conn, acct, fake_fetch(sorted(need), date(2024, 1, 1)))
        store.upsert_equity(get_conn, acct["twin_id"], engine.daily_points(res.curve, acct["bars"]))
    board = lb.read(get_conn)
    assert board["league_version"] == league.LEAGUE_VERSION
    assert len(board["rows"]) == 16
    assert board["luck_rule"]["n_trials"] == 16          # declared up front, not the count running
    spx = next(r for r in board["rows"] if r["id"] == "Y-SPX")
    assert spx["days"] >= 1 and spx["return_pct"] is not None
    cash = next(r for r in board["rows"] if r["id"] == "Y-CASH")
    assert cash["days_in_cash"] == cash["days"]
