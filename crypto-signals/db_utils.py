"""
db_utils.py — Database connection helper for crypto-signals service.
Borrows the get_conn() delegation pattern from poseidon/db_utils.py.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.insert(0, _TRADING_PLATFORM)


def _get_conn():
    """Return a psycopg2 connection from the shared trading-platform pool."""
    from db.postgres import get_conn
    return get_conn()
