import pytest

import core.forex_ai_kill as k


class _Cur:
    def __init__(self, row, rowcount=1):
        self.row, self.rowcount, self.sql = row, rowcount, []

    def execute(self, sql, params=None): self.sql.append((sql, params))
    def fetchone(self): return self.row
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _use(monkeypatch, cur):
    monkeypatch.setattr(k, "_conn", lambda: _Conn(cur))


def test_reads_the_stored_switch(monkeypatch):
    _use(monkeypatch, _Cur(({"ai_kill": True, "ai_kill_reason": "x", "ai_kill_at": "t"},)))
    assert k.ai_kill_state() == {"on": True, "reason": "x", "at": "t"}
    _use(monkeypatch, _Cur(({},)))
    assert k.ai_kill_state()["on"] is False


def test_missing_row_or_unreadable_state_fails_closed(monkeypatch):
    _use(monkeypatch, _Cur(None))
    assert k.ai_kill_state()["on"] is True
    monkeypatch.setattr(k, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert k.ai_kill_state()["on"] is True


def test_set_writes_one_row_or_raises(monkeypatch):
    cur = _Cur(None)
    _use(monkeypatch, cur)
    k.set_ai_kill(True, "operator")
    assert cur.sql[0][1] == (True, "operator", "forex_ai")
    _use(monkeypatch, _Cur(None, rowcount=0))
    with pytest.raises(RuntimeError):
        k.set_ai_kill(True)
