"""Controls page back end: uncached pause state, and /kill off the event loop."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import HTTPException

import db.postgres as pg
from routes import control


def _conn(rows=None, error=None):
    @contextmanager
    def get_conn():
        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                if error:
                    raise error

            def fetchall(self):
                return rows

        class Conn:
            def cursor(self):
                return Cur()
        yield Conn()
    return get_conn


def test_pause_state_reports_missing_rows_as_unknown(monkeypatch):
    monkeypatch.setattr(control, "ks_get_state", lambda: {"tripped": False})
    monkeypatch.setattr(pg, "get_conn", _conn(rows=[
        ("oracle", False, "", None),
        ("forex_ai", True, "monitor only", datetime(2026, 10, 5)),
    ]))
    out = asyncio.run(control.bots_pause_state())
    by_id = {b["bot_id"]: b for b in out["bots"]}
    assert by_id["oracle"]["paused"] is False
    assert by_id["forex_ai"]["paused"] is True
    missing = [b for b in out["bots"] if b["bot_id"] not in ("oracle", "forex_ai")]
    assert missing and all(b["paused"] is None for b in missing)
    assert out["kill_switch_tripped"] is False


def test_pause_state_unreadable_is_503_not_a_guess(monkeypatch):
    monkeypatch.setattr(pg, "get_conn", _conn(error=RuntimeError("db down")))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(control.bots_pause_state())
    assert exc.value.status_code == 503


def test_kill_route_runs_trip_and_reports_cancellations(monkeypatch):
    calls = []

    def fake_trip(reason):
        calls.append(reason)
        return {"cancelled": 2, "action": "paused_all_bots;cancelled_non_protective=2"}

    monkeypatch.setattr(control, "ks_manual_trip", fake_trip)
    monkeypatch.setattr(control, "ks_get_state", lambda: {"tripped": True})
    out = asyncio.run(control.trip_kill_switch())
    assert calls == ["manual_api_trip"] and out["cancelled_orders"] == 2


def test_resume_refused_while_kill_switch_tripped(monkeypatch):
    import core.bot_state as bot_state
    calls = []
    monkeypatch.setattr(control, "is_tripped", lambda: True)
    monkeypatch.setattr(bot_state, "set_paused", lambda *a, **k: calls.append(a))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(control.resume_bot_unified("oracle"))
    assert exc.value.status_code == 409
    assert calls == []


def test_resume_allowed_when_not_tripped(monkeypatch):
    import core.bot_state as bot_state
    calls = []
    monkeypatch.setattr(control, "is_tripped", lambda: False)
    monkeypatch.setattr(bot_state, "set_paused", lambda *a, **k: calls.append((a, k)))
    out = asyncio.run(control.resume_bot_unified("oracle"))
    assert out == {"bot_id": "oracle", "paused": False}
    assert calls
