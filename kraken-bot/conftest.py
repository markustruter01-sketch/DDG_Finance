"""Test guard: kraken-bot tests may only reach a Postgres on this machine.

In Replit the configured database is PRODUCTION, and these tests had no guard
(22 Oct 2026: a bot3 unit test tried to write bot3_decision_log). Any test that
connects anywhere else now fails loudly instead of writing to live data.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys

import psycopg2
import pytest

# pytest puts this folder first on sys.path to import this file. Left there,
# kraken-bot/db.py and config.py would shadow trading-platform's db/ and
# config/ packages for every test. Test modules here still get the folder
# added when they are imported, exactly as before this file existed.
_HERE = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.abspath(sys.path[0]) == _HERE:
    sys.path.pop(0)


def _is_local(dsn: str | None, kwargs: dict) -> bool:
    params = dict(psycopg2.extensions.parse_dsn(dsn)) if dsn else {}
    params.update({k: v for k, v in kwargs.items() if v is not None})
    host = params.get("host") or "localhost"
    if host.startswith("/"):                      # unix socket on this machine
        return True
    try:
        return all(ipaddress.ip_address(socket.gethostbyname(h.strip())).is_loopback
                   for h in host.split(","))
    except (OSError, ValueError):
        return False


@pytest.fixture(scope="session", autouse=True)
def _only_local_postgres():
    real_connect = psycopg2.connect

    def guarded(dsn=None, connection_factory=None, cursor_factory=None, **kwargs):
        if not _is_local(dsn, kwargs):
            raise RuntimeError("kraken-bot tests may not connect to a non-local database "
                               "(in Replit that is production)")
        return real_connect(dsn, connection_factory=connection_factory, cursor_factory=cursor_factory, **kwargs)

    psycopg2.connect = guarded
    try:
        yield
    finally:
        psycopg2.connect = real_connect
