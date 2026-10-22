"""GEAR-V1-G4 shadow job: stores one row per finished session; never trades."""
import json
from contextlib import contextmanager
from datetime import datetime, timezone

import core.gear_shadow_job as job


def _fake_db(monkeypatch, fetch_rows=(), table_exists=True):
    seen = []

    class Cur:
        def execute(self, sql, params=None): seen.append((" ".join(sql.split()), params))
        def fetchone(self): return ("sleeve_shadow_daily" if table_exists else None,)
        def fetchall(self): return list(fetch_rows)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Conn:
        def cursor(self): return Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    @contextmanager
    def get_conn():
        yield Conn()

    import db.postgres as pg
    monkeypatch.setattr(pg, "get_conn", get_conn)
    return seen


def test_ok_result_is_upserted_once_per_day(monkeypatch):
    seen = _fake_db(monkeypatch)
    import sleeve_runtime.gear_shadow as gs
    result = {"status": "ok", "as_of": "2026-12-04", "gear": "normal"}
    monkeypatch.setattr(gs, "run_gear_shadow", lambda fetch, now: result)
    out = job.run_and_store(now=datetime(2026, 12, 4, 22, tzinfo=timezone.utc), fetch=lambda s, d: {})
    assert out is result
    assert seen[0][0].startswith("CREATE TABLE IF NOT EXISTS sleeve_shadow_daily")
    sql, params = seen[1]
    assert "ON CONFLICT (sleeve_id, as_of) DO UPDATE" in sql
    assert params[:2] == ("GEAR-V1-G4", "2026-12-04") and json.loads(params[2]) == result


def test_waiting_result_writes_nothing(monkeypatch):
    seen = _fake_db(monkeypatch)
    import sleeve_runtime.gear_shadow as gs
    monkeypatch.setattr(gs, "run_gear_shadow", lambda fetch, now: {"status": "waiting"})
    assert job.run_and_store(fetch=lambda s, d: {})["status"] == "waiting"
    assert seen == []


def test_history_is_oldest_first(monkeypatch):
    _fake_db(monkeypatch, fetch_rows=[("2026-10-27", {"gear": "safe"}), ("2026-10-26", json.dumps({"gear": "normal"}))])
    assert job.history() == [{"as_of": "2026-10-26", "gear": "normal"}, {"as_of": "2026-10-27", "gear": "safe"}]


def test_history_empty_before_first_row_or_on_error(monkeypatch):
    _fake_db(monkeypatch, table_exists=False)
    assert job.history() == []
    import db.postgres as pg

    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(pg, "get_conn", boom)
    assert job.history() == []
