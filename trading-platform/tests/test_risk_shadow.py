"""Drawdown limits: the episode log, and the kill switch on the fleet drawdown (enforced since 2 Nov 2026)."""
from __future__ import annotations

from contextlib import contextmanager

from core import risk_shadow


class FakeDb:
    """Just enough of risk_limit_shadow: inserts append, the last-state query reads back."""

    def __init__(self):
        self.rows: list[dict] = []

    @contextmanager
    def conn(self):
        db = self

        class Cur:
            def __enter__(self): return self
            def __exit__(self, *a): return False

            def execute(self, sql, params=()):
                self._one = None
                if sql.lstrip().startswith("INSERT"):
                    name, event, threshold, dd, eq, hwm, would, detail = params
                    db.rows.append({"limit": name, "event": event, "threshold": threshold, "dd": dd,
                                    "would_have": would})
                elif sql.lstrip().startswith("SELECT"):
                    hits = [r for r in db.rows if r["limit"] == params[0] and r["event"] in ("breached", "cleared")]
                    self._one = (hits[-1]["event"],) if hits else None

            def fetchone(self): return self._one

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def cursor(self): return Cur()

        yield Conn()


def _snap(equity, hwm=100_000.0):
    return {"fleet_equity": equity, "fleet_hwm": hwm}


def test_episodes_are_written_once_on_each_crossing():
    db = FakeDb()
    rec = lambda s: risk_shadow.record_drawdown_episodes(s, get_conn=db.conn)
    assert rec(_snap(90_000)) == []                                           # 10%: inside both
    assert rec(_snap(79_000)) == ["governor_soft:breached"]                   # 21%
    assert rec(_snap(78_000)) == []                                           # still breached: no repeat
    assert rec(_snap(74_000)) == ["kill_switch_hard:breached"]                # 26%
    assert rec(_snap(85_000)) == ["governor_soft:cleared", "kill_switch_hard:cleared"]
    assert [r["event"] for r in db.rows] == ["breached", "breached", "cleared", "cleared"]
    assert db.rows[1]["would_have"].startswith("trip: latch, pause every bot")


def test_unknown_equity_writes_nothing_and_errors_never_raise():
    db = FakeDb()
    assert risk_shadow.record_drawdown_episodes({"fleet_equity": None}, get_conn=db.conn) == []

    def broken():
        raise RuntimeError("db down")

    assert risk_shadow.record_drawdown_episodes(_snap(70_000), get_conn=broken) == []
    risk_shadow.record_would_refuse(0.3, _snap(70_000), ["x"], get_conn=broken)  # no raise


def test_would_refuse_row():
    db = FakeDb()
    risk_shadow.record_would_refuse(0.175, _snap(82_500), ["fleet drawdown 17.5% above the 15% soft limit"],
                                    get_conn=db.conn)
    assert db.rows == [{"limit": "governor_soft", "event": "would_refuse", "threshold": 0.15, "dd": 0.175,
                        "would_have": "refuse every new buy (sells and protective stops continue)"}]


def _kill_switch_check(monkeypatch, *, enforce: bool, report_only: bool):
    from core import kill_switch, risk_limits
    from execution import reconciliation

    snapshot = {"accounts": [], "fleet_equity": 70_000.0, "fleet_hwm": 100_000.0, "mismatches": [],
                "pause_state_disagreements": [], "account_findings": [], "liveness_findings": []}
    calls = {}
    monkeypatch.setattr(risk_limits, "ENFORCE_DRAWDOWN_LIMITS", enforce)
    monkeypatch.setattr(reconciliation, "collect_live_snapshot", lambda: snapshot)
    monkeypatch.setattr(kill_switch, "_load_acknowledgements", lambda: set())
    monkeypatch.setattr(kill_switch, "trip", lambda flags, snap: calls.setdefault("trip", flags))
    monkeypatch.setattr(kill_switch, "report", lambda snap: calls.setdefault("report", True))
    monkeypatch.setattr(risk_shadow, "record_drawdown_episodes", lambda snap: calls.setdefault("recorded", True))
    reconciliation.run_kill_switch_check(report_only=report_only)
    return calls


def test_armed_kill_switch_trips_on_a_30pct_fleet_drawdown(monkeypatch):
    calls = _kill_switch_check(monkeypatch, enforce=True, report_only=False)
    assert calls["recorded"] and [f["trigger"] for f in calls["trip"]] == ["fleet_drawdown"]


def test_report_only_never_trips_even_when_enforced(monkeypatch):
    calls = _kill_switch_check(monkeypatch, enforce=True, report_only=True)
    assert "trip" not in calls and calls["report"]


def test_record_only_mode_never_trips_on_drawdown(monkeypatch):
    calls = _kill_switch_check(monkeypatch, enforce=False, report_only=False)
    assert "trip" not in calls and calls["report"] and calls["recorded"]
