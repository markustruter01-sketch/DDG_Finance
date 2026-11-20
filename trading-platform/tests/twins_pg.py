"""Throwaway local Postgres for the twin tests (never the configured database)."""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
from contextlib import contextmanager

import pytest

TABLES = ("twin_fx_financing", "allocator_labels", "twin_month_freeze", "twin_fills", "twin_equity_daily", "twin_votes", "twin_decisions", "twin_accounts",
          "change_log", "bot_portfolio", "bots_state")


def loopback_dsn() -> str | None:
    dsn = os.environ.get("TWINS_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    host = urllib.parse.urlparse(dsn).hostname
    try:
        return dsn if host and ipaddress.ip_address(socket.gethostbyname(host)).is_loopback else None
    except (OSError, ValueError):
        return None


needs_pg = pytest.mark.skipif(loopback_dsn() is None, reason="needs a throwaway Postgres on this machine")


def make_get_conn():
    import psycopg2

    dsn = loopback_dsn()

    @contextmanager
    def get_conn():
        conn = psycopg2.connect(dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS " + ", ".join(TABLES) + " CASCADE")
        cur.execute("DROP FUNCTION IF EXISTS twins_append_only() CASCADE")
    return get_conn
