import asyncio
from contextlib import contextmanager
from decimal import Decimal

import routes.fleet_equity as fe


def _fake_db(monkeypatch, rows):
    seen = {}

    class Cur:
        def execute(self, sql, params=None): seen["sql"], seen["params"] = sql, params
        def fetchall(self): return rows
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Conn:
        def cursor(self): return Cur()

    @contextmanager
    def get_conn():
        yield Conn()

    import db.postgres as pg
    monkeypatch.setattr(pg, "get_conn", get_conn)
    monkeypatch.setattr(pg, "is_pg_available", lambda: True)
    return seen


def test_rows_pass_through_grouped_by_active_bot(monkeypatch):
    seen = _fake_db(monkeypatch, [
        ("oracle", "2026-10-20", Decimal("89738.4"), Decimal("0.00055"), Decimal("0.37"), 5),
        ("oracle", "2026-10-21", Decimal("90017.19"), None, Decimal("0.38"), 5),
        ("buck_futures", "2026-10-21", Decimal("1"), Decimal("0"), Decimal("0"), 0),   # retired
    ])
    monkeypatch.setattr(fe, "ACTIVE_BOT_IDS", {"oracle", "spy_qqq_trend"})
    out = asyncio.run(fe.fleet_bot_history(days=5000))
    assert out["days"] == 400 and seen["params"] == (400,)            # clamped
    assert list(out["bots"]) == ["oracle"]
    assert out["bots"]["oracle"][1] == {"date": "2026-10-21", "equity": 90017.19, "daily_return": None,
                                        "deployed_pct": 0.38, "positions": 5}


def test_database_error_returns_empty(monkeypatch):
    import db.postgres as pg

    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(pg, "is_pg_available", lambda: True)
    monkeypatch.setattr(pg, "get_conn", boom)
    assert asyncio.run(fe.fleet_bot_history()) == {"days": 90, "bots": {}}
