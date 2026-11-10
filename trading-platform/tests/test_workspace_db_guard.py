"""The Replit workspace must never write to the live database (10 Nov 2026).

.replit [userenv.development] sets PGOPTIONS so every libpq session in the
workspace is read-only; published deployments must never get it.
"""
import os
import pathlib
import tomllib

import pytest

REPLIT = pathlib.Path(__file__).resolve().parents[2] / ".replit"
GUARD = "-c default_transaction_read_only=on"


def _userenv():
    return tomllib.loads(REPLIT.read_text()).get("userenv", {})


def test_workspace_sessions_are_read_only():
    assert _userenv()["development"]["PGOPTIONS"] == GUARD


def test_production_and_shared_never_get_the_guard():
    env = _userenv()
    assert "PGOPTIONS" not in env.get("production", {})
    assert "PGOPTIONS" not in env.get("shared", {})


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs the local test database")
def test_guarded_session_blocks_writes_and_reports_read_only(monkeypatch):
    import psycopg2

    conn = psycopg2.connect(os.environ["DATABASE_URL"], options=GUARD)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            assert cur.fetchone()[0] == "on"
            with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
                cur.execute("CREATE TABLE _ro_probe (a int)")
    finally:
        conn.rollback()
        conn.close()


def test_startup_skips_schema_and_vault_setup_in_a_read_only_session(monkeypatch):
    import analysis.trade_journal as tj
    import db.postgres as pg
    import execution.profit_sweep as ps

    calls = []
    monkeypatch.setattr(pg, "session_read_only", lambda: True)
    monkeypatch.setattr(pg, "ensure_schema", lambda: calls.append("schema"))
    monkeypatch.setattr(ps, "init_vault_db", lambda: calls.append("vault"))
    tj.init_db()
    assert calls == []


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs the local test database")
def test_runner_sees_the_guard_and_ignores_a_normal_session(monkeypatch):
    import importlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "kraken-bot"))
    runner = importlib.import_module("runner")
    monkeypatch.setenv("PGOPTIONS", GUARD)
    assert runner._database_read_only() is True
    monkeypatch.setenv("PGOPTIONS", "")
    assert runner._database_read_only() is False
