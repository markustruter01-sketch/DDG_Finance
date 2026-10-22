import json

import pytest

import core.bot_state as bs
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
    monkeypatch.setattr(bs, "_get_conn", lambda: _Conn(cur))


def test_reads_the_stored_switch(monkeypatch):
    _use(monkeypatch, _Cur(({"ai_kill": True, "ai_kill_reason": "x", "ai_kill_at": "t"},)))
    st = k.ai_kill_state()
    assert (st["on"], st["reason"], st["at"]) == (True, "x", "t")
    _use(monkeypatch, _Cur(({},)))
    assert k.ai_kill_state()["on"] is False


def test_missing_row_or_unreadable_state_fails_closed(monkeypatch):
    _use(monkeypatch, _Cur(None))
    assert k.ai_kill_state()["on"] is True
    monkeypatch.setattr(bs, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert k.ai_kill_state()["on"] is True


def test_set_merges_one_row_or_raises(monkeypatch):
    cur = _Cur(None)
    _use(monkeypatch, cur)
    k.set_ai_kill(True, "operator")
    patch, bot = cur.sql[0][1]
    assert bot == "forex_ai" and json.loads(patch)["ai_kill"] is True
    _use(monkeypatch, _Cur(None, rowcount=0))
    with pytest.raises(RuntimeError):
        k.set_ai_kill(True)


def test_ai_is_off_if_either_source_says_off(monkeypatch):
    _use(monkeypatch, _Cur(({"ai_kill": False, "ai_kill_control": {"ai_off": True, "reason": "owner"}},)))
    st = k.ai_kill_state()
    assert st["on"] is True and st["reason"] == "DDG Control: owner"
    _use(monkeypatch, _Cur(({"ai_kill": True, "ai_kill_reason": "audit", "ai_kill_control": {"ai_off": False}},)))
    assert k.ai_kill_state()["on"] is True
    _use(monkeypatch, _Cur(({"ai_kill": False, "ai_kill_control": {"ai_off": False}},)))
    assert k.ai_kill_state()["on"] is False


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def test_control_url_is_derived_from_the_push_url(monkeypatch):
    monkeypatch.setenv("DDG_FLEET_PUSH_URL", "https://ctrl.example.app/api/inbound/fleet")
    assert k.control_switch_url() == "https://ctrl.example.app/api/inbound/finance/forex-ai-switch"
    monkeypatch.setenv("DDG_FLEET_PUSH_URL", "https://elsewhere/other")
    assert k.control_switch_url() is None


def test_sync_stores_controls_answer_and_keeps_state_on_any_failure(monkeypatch):
    monkeypatch.setenv("DDG_FLEET_PUSH_URL", "https://ctrl.example.app/api/inbound/fleet")
    monkeypatch.setenv("FLEET_INBOUND_KEY", "push-key")
    cur = _Cur(None)
    _use(monkeypatch, cur)
    seen = {}

    def get(url, headers, timeout):
        seen.update(url=url, auth=headers["Authorization"])
        return _Resp(200, {"ai_off": True, "reason": "owner", "changed_at": "2026-10-22T00:00:00Z"})

    assert k.sync_from_control(get) == "ai_off=True"
    assert seen["auth"] == "Bearer push-key"
    patch = json.loads(cur.sql[0][1][0])["ai_kill_control"]
    assert patch["ai_off"] is True and patch["reason"] == "owner"

    for resp in (_Resp(404), _Resp(500), _Resp(200, {"ai_off": "yes"}), _Resp(200, [1])):
        cur2 = _Cur(None)
        _use(monkeypatch, cur2)
        assert "ai_off=" not in k.sync_from_control(lambda *a, **kw: resp)
        assert cur2.sql == []                          # nothing written

    def down(*a, **kw):
        raise ConnectionError("no route")

    assert "kept last state" in k.sync_from_control(down)
    monkeypatch.delenv("FLEET_INBOUND_KEY")
    assert k.sync_from_control(get) == "not configured"
