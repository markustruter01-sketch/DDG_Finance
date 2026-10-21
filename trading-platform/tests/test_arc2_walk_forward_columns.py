"""The walk-forward trade fetch must only use columns that exist (22 Oct: oracle
asked alpaca_etf_positions for realised_pnl_usd, which has only realised_pnl)."""
import re
from contextlib import contextmanager
from pathlib import Path

import analysis.arc2_walk_forward as wf

SCHEMA = (Path(wf.__file__).parents[1] / "db" / "postgres.py").read_text()


def _table_columns(table: str) -> set[str]:
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA, re.S).group(1)
    return {m.group(1) for m in re.finditer(r"^\s{4}(\w+)\s+[A-Z]", body, re.M)}


def _captured_sql(monkeypatch, bot_id):
    seen = []

    class Cur:
        def execute(self, sql, params=None): seen.append(sql)
        def fetchall(self): return []
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Conn:
        def cursor(self): return Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import db.postgres as pg
    monkeypatch.setattr(pg, "is_pg_available", lambda: True)
    monkeypatch.setattr(pg, "get_conn", lambda: Conn())
    wf._fetch_closed_trades(bot_id, 30)
    return seen[0]


def test_oracle_and_momentum_queries_use_real_columns(monkeypatch):
    cols = _table_columns("alpaca_etf_positions")
    for bot in ("oracle", "spy_qqq_trend"):
        sql = _captured_sql(monkeypatch, bot)
        used = set(re.findall(r"\b(realised_pnl\w*|closed_at|opened_at|exit_reason|status|bot_id)\b", sql))
        assert used <= cols, (bot, used - cols)
