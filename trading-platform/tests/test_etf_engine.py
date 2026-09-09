from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

_ROOT = pathlib.Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))

# Other Kraken tests can load kraken-bot/db.py as the top-level "db" module.
# Remove that non-package alias so this test uses trading-platform/db.
loaded_db = sys.modules.get("db")
if loaded_db is not None and not hasattr(loaded_db, "__path__"):
    del sys.modules["db"]

from alpaca_etf_engine import AlpacaEtfEngine
from db import postgres


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self._result = []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select id, bot_id, symbol, status"):
            self._result = [
                (row["id"], row["bot_id"], row["symbol"], row["status"])
                for row in self.rows
                if row["current_qty"] is None
                and row["status"] in {"open", "closed"}
            ]
            self.rowcount = len(self._result)
            return

        if "set current_qty = 0" in normalized:
            changed = 0
            for row in self.rows:
                if row["current_qty"] is None and row["status"] == "closed":
                    row["current_qty"] = 0
                    changed += 1
            self.rowcount = changed
            return

        if "set current_qty = %s" in normalized:
            broker_qty, row_id = params
            changed = 0
            for row in self.rows:
                if row["id"] == row_id and row["current_qty"] is None:
                    row["current_qty"] = broker_qty
                    changed = 1
                    break
            self.rowcount = changed
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return list(self._result)


class _FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_count += 1


class _FakeApi:
    def __init__(self, positions=None, error=None):
        self.positions = positions or []
        self.error = error
        self.list_positions_calls = 0

    def list_positions(self):
        self.list_positions_calls += 1
        if self.error is not None:
            raise self.error
        return self.positions


def _rows():
    return [
        {"id": 1, "bot_id": "oracle", "symbol": "SPY", "status": "closed", "current_qty": None},
        {"id": 2, "bot_id": "oracle", "symbol": "E/WY", "status": "open", "current_qty": None},
        {"id": 3, "bot_id": "oracle", "symbol": "QQQ", "status": "canceled", "current_qty": None},
        {"id": 4, "bot_id": "oracle", "symbol": "GREK", "status": "open", "current_qty": 7},
    ]


def _engine(monkeypatch, rows, api, degradation_records=None):
    connection = _FakeConnection(rows)
    monkeypatch.setattr(postgres, "get_conn", lambda: connection)
    monkeypatch.setattr(postgres, "is_pg_available", lambda: True)
    if degradation_records is not None:
        monkeypatch.setattr(
            "core.degradation_tracker.record_degradation",
            lambda **kwargs: degradation_records.append(kwargs),
        )
    engine = object.__new__(AlpacaEtfEngine)
    engine.api = api
    return engine, connection


def test_current_qty_backfill_sets_closed_rows_to_zero(monkeypatch):
    rows = _rows()
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="E/WY", qty="43.355")]),
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 0


def test_current_qty_backfill_sets_open_rows_by_canonical_symbol(monkeypatch):
    rows = _rows()
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="EWY", qty="43.355")]),
    )

    engine._backfill_current_qty()

    assert rows[1]["current_qty"] == "43.355"


def test_current_qty_backfill_uses_rest_list_positions_method(monkeypatch):
    rows = _rows()
    api = _FakeApi([SimpleNamespace(symbol="E/WY", qty="43.355")])
    engine, _connection = _engine(monkeypatch, rows, api)

    engine._backfill_current_qty()

    assert api.list_positions_calls == 1


def test_current_qty_backfill_leaves_cancelled_rows_untouched(monkeypatch):
    rows = _rows()
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="E/WY", qty="43.355")]),
    )

    engine._backfill_current_qty()

    assert rows[2]["current_qty"] is None


def test_current_qty_backfill_leaves_populated_rows_untouched(monkeypatch):
    rows = _rows()
    rows[1]["current_qty"] = "43.355"
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi([SimpleNamespace(symbol="GREK", qty="99")]),
    )

    engine._backfill_current_qty()

    assert rows[3]["current_qty"] == 7
    assert engine.api.list_positions_calls == 0


def test_current_qty_backfill_broker_failure_updates_closed_and_records_degradation(
    monkeypatch,
):
    rows = _rows()
    degradation_records = []
    engine, _connection = _engine(
        monkeypatch,
        rows,
        _FakeApi(error=RuntimeError("broker unavailable")),
        degradation_records,
    )

    engine._backfill_current_qty()

    assert rows[0]["current_qty"] == 0
    assert rows[1]["current_qty"] is None
    assert rows[2]["current_qty"] is None
    assert len(degradation_records) == 1
    assert degradation_records[0]["error_type"] == "etf_current_qty_broker_read_failed"


def test_current_qty_backfill_is_idempotent(monkeypatch):
    rows = _rows()
    api = _FakeApi([SimpleNamespace(symbol="EWY", qty="43.355")])
    engine, _connection = _engine(monkeypatch, rows, api)

    engine._backfill_current_qty()
    after_first = [dict(row) for row in rows]
    engine._backfill_current_qty()

    assert rows == after_first
    assert api.list_positions_calls == 1