"""21 Nov 2026: OANDA's API answers 5xx over the weekend. With the forex market shut
that is expected, so it is a note, not an alarm. From the Sunday open it alarms as before."""
from datetime import datetime, timezone

from core import invariants, kill_switch, market_hours

SAT = datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc)        # Fri 20:00 New York: closed
TUE = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)       # open
SUN_OPEN = datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc)  # Sun 17:00 New York: open again

OANDA_FAIL = {"bot_id": "forex_ai", "kind": "oanda_read_failed", "status": "UNKNOWN",
              "detail": "OANDA practice API returned HTTP 520"}
NAV_FAIL = {"check": "fleet_equity_read", "kind": "reconciliation_check_failed",
            "error": "forex_ai: failed to read USD account NAV: OANDA practice API returned HTTP 503"}


def test_forex_week():
    assert market_hours.oanda_weekend(SAT) and not market_hours.oanda_weekend(TUE)
    assert not market_hours.oanda_weekend(SUN_OPEN)
    assert market_hours.oanda_weekend(SAT.timestamp())


def _triggers(now, extra=()):
    kill_switch._state["read_fail_counts"].clear(); kill_switch._state["read_fail_seen"].clear()
    kill_switch._state["mismatch_counts"].clear()
    out = []
    for i in range(kill_switch.READ_FAIL_REQUIRED_CHECKS):
        snap = {"accounts": [], "fleet_equity": None, "fleet_hwm": 100, "captured_at": f"t{i}",
                "account_findings": [OANDA_FAIL, *extra],
                "mismatches": [NAV_FAIL] * 1}
        for _ in range(kill_switch.MISMATCH_REQUIRED_CHECKS):
            out = kill_switch.evaluate_snapshot(snap, now=now.timestamp())
    return out


def test_weekend_oanda_failures_raise_nothing():
    assert _triggers(SAT) == []


def test_weekday_oanda_failures_still_alarm():
    kinds = {t.get("kind") or t["trigger"] for t in _triggers(TUE)}
    assert {"oanda_read_failed", "reconciliation_check_failed", "fleet_equity_unknown"} <= kinds


def test_weekend_still_alarms_on_an_alpaca_read_failure():
    alpaca = {"bot_id": "oracle", "kind": "alpaca_read_failed", "detail": "HTTP 500"}
    kinds = {t.get("kind") or t["trigger"] for t in _triggers(SAT, [alpaca])}
    assert "alpaca_read_failed" in kinds and "fleet_equity_unknown" in kinds and "oanda_read_failed" not in kinds


def _unknown(source_error):
    return {"name": "strategy_positions_have_covering_stops", "status": "UNKNOWN", "message": "UNKNOWN: x",
            "actual": {"source_error": source_error}}


def test_invariant_unknown_from_oanda_is_closed_on_the_weekend_only():
    assert invariants._weekend(_unknown("OANDA practice API returned HTTP 503"), SAT)["status"] == "CLOSED"
    assert invariants._weekend(_unknown("OANDA practice API returned HTTP 503"), TUE)["status"] == "UNKNOWN"
    assert invariants._weekend(_unknown("Alpaca returned HTTP 500"), SAT)["status"] == "UNKNOWN"


def test_link_shows_closed_not_failing_on_the_weekend(monkeypatch):
    from core import link_health
    monkeypatch.setattr(market_hours, "oanda_weekend", lambda now=None: True)

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass
        def fetchall(self): return [("OANDA", None, SAT, "HTTP 503"), ("Alpaca · Atlas", None, SAT, "HTTP 500")]

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _Cur()

    monkeypatch.setattr(link_health, "_conn", lambda: _Conn())
    states = {l["name"]: l["state"] for l in link_health.read_links()}
    assert states == {"OANDA": "closed", "Alpaca · Atlas": "failing"}
