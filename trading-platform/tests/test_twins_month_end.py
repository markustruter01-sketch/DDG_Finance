"""Month-end freeze (TWINS-V2 record keeping): figures by hand, written once,
append-only, drift shown, GitHub copy never overwrites. No network."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timezone

import pytest

import twins  # noqa: F401
from twins import month_end as me
from twins import store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

ACCT = {"twin_id": "t", "start_equity": 100.0}
ROWS = [{"day": date(2026, 10, 30), "equity": 100.0, "ref_equity": None},
        {"day": date(2026, 11, 2), "equity": 110.0, "ref_equity": 109.0},
        {"day": date(2026, 11, 3), "equity": 99.0, "ref_equity": 98.0},
        {"day": date(2026, 11, 30), "equity": 105.0, "ref_equity": 104.5},
        {"day": date(2026, 12, 1), "equity": 120.0, "ref_equity": None}]


def test_figures_by_hand():
    f = me.figures(ACCT, ROWS, date(2026, 11, 1))
    assert f["equity_start"] == 100.0 and f["equity_end"] == 105.0
    assert f["return_pct"] == 5.0                 # 105 / 100 - 1
    assert f["worst_fall_pct"] == -10.0           # 110 -> 99
    assert f["ref_equity_end"] == 104.5 and f["days"] == 3
    assert me.figures(ACCT, ROWS, date(2026, 9, 1)) is None
    first = me.figures(ACCT, ROWS, date(2026, 10, 1))
    assert first["equity_start"] == 100.0         # the start balance before the first row


def test_finished_months():
    assert me.finished_months(date(2026, 11, 17), date(2026, 11, 30)) == []
    assert me.finished_months(date(2026, 11, 17), date(2026, 12, 1)) == [date(2026, 11, 1)]
    assert me.finished_months(date(2026, 11, 17), date(2027, 2, 2)) == [
        date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)]


def _setup(get_conn):
    store.ensure_schema(get_conn)
    store.create_account(get_conn, twin_id="league:T:v0", bot_id="league", kind="shadow", version=0, bars="alpaca_1d",
                         start_at=datetime(2026, 10, 30, 21, tzinfo=timezone.utc), start_equity=100.0,
                         config={"max_gross": 1.0, "allow_short": False})
    store.upsert_equity(get_conn, "league:T:v0", [(r["day"], r["equity"], 1.0) for r in ROWS])
    store.append_decision(get_conn, twin_id="league:T:v0", decided_at=datetime(2026, 11, 2, 22, tzinfo=timezone.utc),
                          step_at=datetime(2026, 11, 2, 21, tzinfo=timezone.utc), weights={"SPY": 1.0})


@needs_pg
def test_freeze_once_append_only_and_drift_is_shown_not_hidden():
    get_conn = make_get_conn()
    _setup(get_conn)
    dec1 = datetime(2026, 12, 1, 17, 30, tzinfo=NEW_YORK)
    assert me.freeze_all(get_conn, dec1, only=set()) == []                    # not valued tonight: waits
    assert me.freeze_all(get_conn, dec1) == ["league:T:v0 2026-10", "league:T:v0 2026-11"]
    assert me.freeze_all(get_conn, dec1) == []                                # written once
    nov = store.frozen(get_conn, date(2026, 11, 1))[0]
    assert nov["return_pct"] == 5.0 and nov["decisions"] == 1 and nov["last_hash"]
    with get_conn() as conn, conn.cursor() as cur, pytest.raises(Exception, match="append-only"):
        cur.execute("UPDATE twin_month_freeze SET return_pct = 0")
    assert me.drift(get_conn) == []
    store.upsert_equity(get_conn, "league:T:v0", [(date(2026, 11, 30), 106.0, 1.0)])   # a price revision
    moved = me.drift(get_conn)
    assert moved == [{"twin_id": "league:T:v0", "month": "2026-11-01", "frozen_pct": 5.0, "now_pct": 6.0,
                      "gap_pp": 1.0}]
    alarms = []
    out = me.run(get_conn, dec1, lambda *a, **k: alarms.append(a), lambda *a: None, token="", repo="")
    assert alarms and alarms[0][1] == "twin_freeze_drift"
    assert out["copy"]["status"].startswith("off")
    assert store.frozen(get_conn, date(2026, 11, 1))[0]["return_pct"] == 5.0        # frozen figure stands


class FakeGitHub:
    def __init__(self, files=None):
        self.files, self.calls = dict(files or {}), []

    def __call__(self, method, url, token, body=None):
        self.calls.append((method, url.rsplit("/", 1)[-1]))
        name = url.split("/contents/", 1)[1]
        resp = type("R", (), {})()
        if method == "GET":
            if name in self.files:
                resp.status_code = 200
                text = self.files[name]
                resp.json = lambda: {"content": base64.b64encode(text.encode()).decode()}
            else:
                resp.status_code = 404
        else:
            self.files[name] = base64.b64decode(body["content"]).decode()
            resp.status_code = 201
        return resp


def test_copy_never_overwrites():
    gh = FakeGitHub()
    m = date(2026, 11, 1)
    assert me.copy_month(m, {"2026-11.json": "a"}, token="x", repo="o/r", http=gh) == "copied"
    assert me.copy_month(m, {"2026-11.json": "a"}, token="x", repo="o/r", http=gh) == "already there"
    with pytest.raises(RuntimeError, match="not overwritten"):
        me.copy_month(m, {"2026-11.json": "b"}, token="x", repo="o/r", http=gh)
    assert gh.files["records/2026-11.json"] == "a"


@needs_pg
def test_copy_all_writes_json_and_one_page_once():
    get_conn = make_get_conn()
    _setup(get_conn)
    me.freeze_all(get_conn, datetime(2026, 12, 1, 17, 30, tzinfo=NEW_YORK))
    gh = FakeGitHub()
    out = me.copy_all(get_conn, datetime(2026, 12, 1, 17, 30, tzinfo=NEW_YORK), token="x", repo="o/r", http=gh)
    assert out == {"2026-10": "copied", "2026-11": "copied"}
    data = json.loads(gh.files["records/2026-11.json"])
    assert data["lines"][0]["twin_id"] == "league:T:v0" and data["lines"][0]["return_pct"] == 5.0
    assert "| league:T:v0 | +5.00% | -10.00% |" in gh.files["records/2026-11.md"]
    gh.calls.clear()
    assert me.copy_all(get_conn, datetime(2026, 12, 2, 17, 30, tzinfo=NEW_YORK), token="x", repo="o/r",
                       http=gh) == {}
    assert gh.calls == []                         # done months are not asked about again
