"""Regression: the vault re-bought the same pending amount every cycle.

Production oracle, 15-21 Oct 2026: after the first $5.21 order was applied,
every later order's fill was compared with that order's applied amount, so
nothing was recorded, pending never fell, and a new order went out every
15 minutes (236 attempts). Runs against the real test Postgres.
"""

from __future__ import annotations

import ipaddress
import os
import pathlib
import socket
import sys
import urllib.parse
from contextlib import contextmanager
from itertools import count

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

from execution import per_bot_vault as vault  # noqa: E402


def _loopback_dsn() -> str | None:
    """Only a Postgres on this machine. Anywhere the DSN points elsewhere
    (Replit points at production) these tests skip instead of writing."""
    dsn = os.environ.get("DATABASE_URL", "")
    host = urllib.parse.urlparse(dsn).hostname
    try:
        return dsn if host and ipaddress.ip_address(socket.gethostbyname(host)).is_loopback else None
    except (OSError, ValueError):
        return None


DSN = _loopback_dsn()
pytestmark = pytest.mark.skipif(DSN is None, reason="needs a throwaway Postgres on this machine")


@contextmanager
def get_conn():
    import psycopg2
    conn = psycopg2.connect(DSN)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _local_db(monkeypatch):
    import db.postgres
    monkeypatch.setattr(db.postgres, "get_conn", get_conn)
    monkeypatch.setattr(db.postgres, "is_pg_available", lambda: True)

PRICES = {"BIL": 91.598, "VOO": 710.584}


@pytest.fixture
def broker(monkeypatch):
    orders: dict[str, dict] = {}
    ids = count(1)
    submitted: list[str] = []

    def submit(bot_id, symbol, notional, queue_id):
        oid = f"new-{next(ids)}"
        orders[oid] = {"status": "filled", "filled_qty": round(notional / PRICES[symbol], 9),
                       "filled_avg_price": PRICES[symbol], "replaced_by": None}
        submitted.append(symbol)
        return {"status": "submitted", "order_id": oid}

    def read(bot_id, oid):
        return orders[oid]

    # The two orders left in the queue by the loop, already filled at the broker.
    orders["old-bil"] = {"status": "filled", "filled_qty": 0.056878971, "filled_avg_price": 91.598, "replaced_by": None}
    orders["old-voo"] = {"status": "filled", "filled_qty": 0.007317924, "filled_avg_price": 710.584, "replaced_by": None}
    monkeypatch.setattr(vault, "vault_enabled", lambda: True)
    monkeypatch.setattr(vault, "_submit_vault_buy", submit)
    monkeypatch.setattr(vault, "_read_vault_order", read)
    monkeypatch.setattr(vault, "_orders_today", {}, raising=False)
    return submitted


@pytest.fixture
def stuck_queue():
    vault.ensure_schema()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM per_bot_vault_deployment_queue WHERE bot_id = 'oracle'")
        cur.execute("DELETE FROM per_bot_vault_holdings WHERE bot_id = 'oracle'")
        cur.execute("DELETE FROM per_bot_vault_accounts WHERE bot_id = 'oracle'")
        cur.execute("INSERT INTO per_bot_vault_accounts (bot_id, activation_enabled, cash_usd) VALUES ('oracle', TRUE, 10.43)")
        cur.execute("INSERT INTO per_bot_vault_holdings (bot_id, symbol, qty, cost_basis_usd) VALUES "
                    "('oracle', 'BIL', 25.250485556, 2313.44), ('oracle', 'VOO', 3.28414826, 2313.42)")
        # Exactly the production row seen on 22 Oct 2026.
        cur.execute("""INSERT INTO per_bot_vault_deployment_queue
            (bot_id, pending_cash_usd, pending_bil_usd, pending_voo_usd, bil_order_id, voo_order_id,
             bil_filled_usd, voo_filled_usd, status, attempts)
            VALUES ('oracle', 0, 5.22, 5.21, 'old-bil', 'old-voo', 5.21, 5.20, 'submitted', 236)""")
    yield
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM per_bot_vault_deployment_queue WHERE bot_id = 'oracle'")
        cur.execute("DELETE FROM per_bot_vault_holdings WHERE bot_id = 'oracle'")
        cur.execute("DELETE FROM per_bot_vault_accounts WHERE bot_id = 'oracle'")


def _state():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT pending_bil_usd, pending_voo_usd, status FROM per_bot_vault_deployment_queue WHERE bot_id='oracle'")
        q = cur.fetchone()
        cur.execute("SELECT symbol, qty FROM per_bot_vault_holdings WHERE bot_id='oracle' ORDER BY symbol")
        h = dict(cur.fetchall())
    return float(q[0]), float(q[1]), q[2], {k: float(v) for k, v in h.items()}


def test_stuck_queue_buys_once_records_the_fill_and_stops(broker, stuck_queue):
    for _ in range(6):                                    # 90 minutes of market-hours cycles
        vault.run_deployment_cycle(market_open=True)
    assert broker == ["BIL", "VOO"]                       # one buy each, not one per cycle
    pending_bil, pending_voo, status, held = _state()
    assert pending_bil < vault.MIN_TRADE_NOTIONAL and pending_voo < vault.MIN_TRADE_NOTIONAL
    assert status == "complete"
    assert held["BIL"] == pytest.approx(25.250485556 + 5.22 / 91.598, abs=1e-4)
    assert held["VOO"] == pytest.approx(3.28414826 + 5.21 / 710.584, abs=1e-5)


def test_daily_cap_stops_a_runaway(broker, stuck_queue, monkeypatch):
    monkeypatch.setattr(vault, "DAILY_ORDER_CAP", 1)
    vault.run_deployment_cycle(market_open=True)
    assert broker == ["BIL"]                              # VOO refused by the breaker
    out = vault.run_deployment_cycle(market_open=True)
    assert broker == ["BIL"]
    assert any(r.get("reason") == "daily_order_cap" for r in out["orders"])
