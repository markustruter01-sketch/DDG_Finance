from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "trading-platform"))

from core import bot_state


class _Cursor:
    def __init__(self, positions):
        self.positions = positions
        self.rowcount = -1
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        if sql.lstrip().lower().startswith("select positions"):
            self.result = (self.positions,)
            self.rowcount = 1
            return
        if sql.lstrip().lower().startswith("update bot_portfolio"):
            payload, _bot_id = params
            self.positions = json.loads(payload)
            self.rowcount = 1
            return
        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self, positions):
        self.cursor_instance = _Cursor(positions)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_instance


def _sync(monkeypatch, existing, broker_positions, *, positions_ok=True, account_ok=True):
    conn = _Connection(existing)
    monkeypatch.setattr(bot_state, "_get_conn", lambda: conn)
    result = bot_state.sync_cash_asset_ledger(
        "spy_qqq_trend",
        broker_positions,
        positions_read_ok=positions_ok,
        account_read_ok=account_ok,
    )
    return result, conn.cursor_instance.positions


def test_sync_sets_sgov_to_broker_qty_and_preserves_other_symbols(monkeypatch):
    result, positions = _sync(
        monkeypatch,
        [{"symbol": "SGOV", "qty": 189}, {"symbol": "SPY", "qty": 15}],
        [{"symbol": "SGOV", "qty": "215"}, {"symbol": "SPY", "qty": "999"}],
    )
    assert result
    assert positions == [{"symbol": "SGOV", "qty": 215.0}, {"symbol": "SPY", "qty": 15}]


def test_sync_removes_ledger_cash_asset_absent_at_broker(monkeypatch):
    result, positions = _sync(
        monkeypatch,
        [{"symbol": "BIL", "qty": 2.5}, {"symbol": "TSLA", "qty": 4}],
        [{"symbol": "VOO", "qty": "1.25"}],
    )
    assert result
    assert positions == [{"symbol": "TSLA", "qty": 4}, {"symbol": "VOO", "qty": 1.25}]


def test_failed_broker_positions_read_leaves_ledger_unchanged(monkeypatch):
    original = [{"symbol": "SGOV", "qty": 189}, {"symbol": "QQQ", "qty": 8}]
    conn = _Connection(original)
    monkeypatch.setattr(bot_state, "_get_conn", lambda: conn)
    assert not bot_state.sync_cash_asset_ledger(
        "spy_qqq_trend", None, positions_read_ok=False, account_read_ok=True
    )
    assert conn.cursor_instance.positions == original


def test_empty_positions_require_successful_account_read_and_non_cash_is_untouched(monkeypatch):
    original = [{"symbol": "VOO", "qty": 3}, {"symbol": "QQQ", "qty": 8}]
    conn = _Connection(original)
    monkeypatch.setattr(bot_state, "_get_conn", lambda: conn)
    assert not bot_state.sync_cash_asset_ledger(
        "spy_qqq_trend", [], positions_read_ok=True, account_read_ok=False
    )
    assert conn.cursor_instance.positions == original

    result, positions = _sync(
        monkeypatch,
        original,
        [{"symbol": "QQQ", "qty": "100"}],
    )
    assert result
    assert positions == [{"symbol": "QQQ", "qty": 8}]
