from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

import forex_ai_strategy as fs
import forex_ledger as fl


def test_trading_day_due_follows_the_new_york_close():
    # Friday 9 Oct 2026, 17:10 New York (EDT, UTC-4) = 21:10 UTC.
    assert fl.trading_day_due(datetime(2026, 10, 9, 21, 10, tzinfo=timezone.utc)) == date(2026, 10, 9)
    # Friday 16:59 New York: not yet.
    assert fl.trading_day_due(datetime(2026, 10, 9, 20, 59, tzinfo=timezone.utc)) is None
    # Saturday and Sunday New York: never.
    assert fl.trading_day_due(datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)) is None
    assert fl.trading_day_due(datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)) is None
    # After US daylight saving ends (EST, UTC-5): Monday 2 Nov 17:10 NY = 22:10 UTC.
    assert fl.trading_day_due(datetime(2026, 11, 2, 22, 10, tzinfo=timezone.utc)) == date(2026, 11, 2)
    assert fl.trading_day_due(datetime(2026, 11, 2, 21, 10, tzinfo=timezone.utc)) is None


def test_ledger_ddl_blocks_update_and_delete():
    ddl = fl.FOREX_LEDGER_DDL
    assert "BEFORE UPDATE OR DELETE ON forex_decision_ledger" in ddl
    assert "append-only" in ddl and "trading_day    DATE NOT NULL UNIQUE" in ddl


def test_record_hash_is_stable_and_order_independent():
    assert fl.record_sha256({"a": 1, "b": [2]}) == fl.record_sha256({"b": [2], "a": 1})
    assert fl.record_sha256({"a": 1}) != fl.record_sha256({"a": 2})


class FakeDB:
    def __init__(self, logged=False):
        self.logged = logged
        self.sql = []

    @contextmanager
    def conn(self):
        yield self

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=None):
        self.sql.append((sql.strip().split()[0], params))

    def fetchone(self):
        return (1,) if self.logged else None


FRIDAY_CLOSE = datetime(2026, 10, 9, 21, 10, tzinfo=timezone.utc)


OFF = lambda: {"on": False, "reason": "", "at": None}


def test_shadow_council_runs_once_per_day_and_appends_record():
    db, calls = FakeDB(), []

    def council(rows, sides, *, news, today):
        calls.append((sides, news, today))
        return {"status": "shadow", "low_confidence": False, "decisions": []}

    headlines = {"headlines": [], "sources": []}
    positions = [{"instrument": "EUR_USD", "long": {"units": "100"}, "short": {"units": "0"}}]
    status = fs.run_shadow_council({"rows": []}, positions, now=lambda: FRIDAY_CLOSE,
                                   get_conn=db.conn, council=council, kill_state=OFF,
                                   news=lambda: headlines)
    assert status.startswith("logged 2026-10-09 status=shadow")
    assert calls == [({"EUR_USD": "long"}, headlines, "2026-10-09")]
    assert [s for s, _ in db.sql] == ["CREATE", "SELECT", "INSERT"]


def test_shadow_council_skips_when_logged_not_due_or_failing():
    def boom(*_a):
        raise AssertionError("must not run")

    assert fs.run_shadow_council({"rows": []}, [], now=lambda: FRIDAY_CLOSE,
                                 get_conn=FakeDB(logged=True).conn, council=boom, kill_state=OFF) == "already logged 2026-10-09"
    saturday = datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)
    assert fs.run_shadow_council({"rows": []}, [], now=lambda: saturday,
                                 get_conn=FakeDB().conn, council=boom, kill_state=OFF) == "not due"

    def broken_conn():
        raise RuntimeError("db down")

    assert fs.run_shadow_council({"rows": []}, [], now=lambda: FRIDAY_CLOSE,
                                 get_conn=broken_conn, council=boom, kill_state=OFF) == "failed: RuntimeError"


def test_ai_kill_switch_stops_the_council_before_any_call_or_ledger_write():
    def boom(*_a):
        raise AssertionError("must not run")

    db = FakeDB()
    on = lambda: {"on": True, "reason": "operator", "at": None}
    status = fs.run_shadow_council({"rows": []}, [], now=lambda: FRIDAY_CLOSE,
                                   get_conn=db.conn, council=boom, kill_state=on)
    assert status == "ai kill switch on: operator"
    assert db.sql == []
