"""The one-time vault backfill on a database without the old forex_trades table (production, 25 Nov 2026):
no Postgres error, and the 'done' marker is written so it is skipped on every later startup."""

from __future__ import annotations

import pytest

from twins_pg import loopback_dsn


@pytest.mark.skipif(loopback_dsn() is None, reason="needs a throwaway Postgres on this machine")
def test_backfill_without_forex_trades_marks_itself_done(monkeypatch):
    import psycopg2

    import execution.profit_sweep as ps

    monkeypatch.setattr(ps, "_build_dsn", loopback_dsn)
    conn = psycopg2.connect(loopback_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS forex_trades")
        cur.execute(ps._PG_VAULT_MIGRATIONS_DDL)
        cur.execute("DELETE FROM vault_migrations WHERE key = %s", (ps._VAULT_BACKFILL_KEY,))
    errors = []
    monkeypatch.setattr(ps.logger, "warning", lambda msg, *a, **k: errors.append(msg))
    ps._backfill_from_trade_history()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM vault_migrations WHERE key = %s", (ps._VAULT_BACKFILL_KEY,))
        assert cur.fetchone() is not None                      # skipped from now on
    conn.close()
    assert not [e for e in errors if "backfill failed" in str(e)]
