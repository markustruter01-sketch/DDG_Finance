"""record_resize: one open row per symbol, or nothing is written."""
from __future__ import annotations

import pathlib
import sys
from contextlib import contextmanager

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))

import alpaca_etf_engine as eng_mod


class _Cur:
    def __init__(self, rowcount):
        self.rowcount, self.sql = rowcount, []

    def execute(self, sql, params=None): self.sql.append(params)
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def __init__(self, cur): self.cur, self.rolled_back, self.committed = cur, False, False
    def cursor(self): return self.cur
    def rollback(self): self.rolled_back = True
    def commit(self): self.committed = True


def _engine_with(monkeypatch, rowcount):
    conn = _Conn(_Cur(rowcount))

    @contextmanager
    def get_conn():
        yield conn

    import db.postgres as pg
    monkeypatch.setattr(pg, "get_conn", get_conn)
    monkeypatch.setattr(pg, "is_pg_available", lambda: True)
    engine = eng_mod.AlpacaEtfEngine.__new__(eng_mod.AlpacaEtfEngine)
    return engine, conn


def test_resize_updates_the_single_row(monkeypatch):
    engine, conn = _engine_with(monkeypatch, 1)
    assert engine.record_resize("oracle", "SPY", 44, 59, 700.0) is True
    assert conn.cur.sql[0] == (44, 59, 700.0, 59 * 700.0, "oracle", "SPY") and conn.committed


def test_resize_refuses_when_not_exactly_one_row(monkeypatch):
    for n in (0, 2):
        engine, conn = _engine_with(monkeypatch, n)
        assert engine.record_resize("oracle", "SPY", 44, 59, 700.0) is False
        assert conn.rolled_back
