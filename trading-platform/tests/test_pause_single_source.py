"""bots_state.paused is the only pause switch: reads fail closed, writes fail loud."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from core import bot_state
from core import kill_switch as ks


class _Cur:
    def __init__(self, row=None, rowcount=1, error=None):
        self.row, self.rowcount, self.error = row, rowcount, error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.error:
            raise self.error

    def fetchone(self):
        return self.row


def _conn_factory(cur):
    @contextmanager
    def get_conn():
        class Conn:
            def cursor(self):
                return cur
        yield Conn()
    return get_conn


@pytest.mark.parametrize("row, expected", [((True,), True), ((False,), False)])
def test_is_paused_reads_the_row(monkeypatch, row, expected):
    monkeypatch.setattr(bot_state, "_get_conn", _conn_factory(_Cur(row=row)))
    assert bot_state.is_paused("oracle") is expected


def test_is_paused_fails_closed_on_missing_row(monkeypatch):
    monkeypatch.setattr(bot_state, "_get_conn", _conn_factory(_Cur(row=None)))
    assert bot_state.is_paused("oracle") is True


def test_is_paused_fails_closed_when_database_unreadable(monkeypatch):
    monkeypatch.setattr(bot_state, "_get_conn", _conn_factory(_Cur(error=RuntimeError("db down"))))
    assert bot_state.is_paused("oracle") is True


def test_set_paused_raises_when_nothing_written(monkeypatch):
    monkeypatch.setattr(bot_state, "_get_conn", _conn_factory(_Cur(rowcount=0)))
    with pytest.raises(RuntimeError, match="no bots_state row"):
        bot_state.set_paused("oracle", True, reason="test")


def test_set_paused_raises_on_database_error(monkeypatch):
    monkeypatch.setattr(bot_state, "_get_conn", _conn_factory(_Cur(error=RuntimeError("db down"))))
    with pytest.raises(RuntimeError, match="db down"):
        bot_state.set_paused("oracle", True, reason="test")


def test_kill_switch_pauses_the_rest_and_still_cancels_when_one_pause_fails(monkeypatch):
    attempted = []

    def fake_set_paused(bot_id, paused, reason=""):
        attempted.append(bot_id)
        if bot_id == "oracle":
            raise RuntimeError("db down")

    monkeypatch.setattr(bot_state, "set_paused", fake_set_paused)
    cancelled = []
    client = type("Client", (), {"cancel_order_by_id": lambda self, oid: cancelled.append(oid)})()
    snapshot = {"accounts": [{"bot_id": "oracle", "_client": client,
                              "orders": [{"id": "limit-1", "side": "buy", "type": "limit"}]}]}
    monkeypatch.setattr(ks, "_write_event", lambda *args: None)
    result = ks.trip([{"trigger": "negative_cash"}], snapshot)
    assert set(attempted) == set(ks.ACTIVE_BOTS)          # every bot was tried
    assert cancelled == ["limit-1"]                        # orders still cancelled
    assert "PAUSE_FAILED=oracle" in result["action"]       # failure is reported
    ks._state["tripped"] = False
