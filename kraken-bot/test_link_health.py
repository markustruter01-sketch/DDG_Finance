"""core/link_health.py (trading-platform): state rules, and that reporting never breaks the caller."""
from datetime import datetime, timedelta, timezone

import core.link_health as lh

T = datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc)


def test_a_success_after_the_last_failure_means_working():
    assert lh.state(T, T - timedelta(minutes=12)) == "working"
    assert lh.state(T - timedelta(minutes=12), T) == "failing"
    assert lh.state(T, None) == "working" and lh.state(None, T) == "failing"
    assert lh.state(None, None) == "unknown"


def test_reporting_never_raises_when_the_database_is_down(monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(lh, "_conn", broken)
    lh.record_link("OANDA practice", False, "HTTP 401")
    lh.record_link("OANDA practice", True)


def test_successes_are_throttled_failures_are_not(monkeypatch):
    writes = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None):
            if params: writes.append(("ok" if "last_ok" in sql.split("VALUES")[0] else "fail", params[0]))

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()

    monkeypatch.setattr(lh, "_conn", lambda: Conn())
    monkeypatch.setattr(lh, "_last_ok_write", {})
    for _ in range(3):
        lh.record_link("Alpaca · Atlas", True)
        lh.record_link("Alpaca · Atlas", False, "boom")
    assert writes.count(("ok", "Alpaca · Atlas")) == 1
    assert writes.count(("fail", "Alpaca · Atlas")) == 3
