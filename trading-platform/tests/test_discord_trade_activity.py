"""Regression tests for Discord's active-fleet trade-activity warning."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notifications import discord


class _Cursor:
    def __init__(self, rows: list[tuple[str, datetime]]):
        self.rows = rows
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, cursor: _Cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_value


class TestDiscordTradeActivity(unittest.TestCase):
    def test_etf_open_timestamp_is_used_as_recent_trade_activity(self):
        """An open SPY/QQQ ETF fill must suppress the stale no-trades warning."""
        activity_at = datetime(2026, 8, 19, 14, 5, tzinfo=timezone.utc)
        cursor = _Cursor([("bot2_spy_qqq", activity_at)])

        with (
            patch("db.postgres.is_pg_available", return_value=True),
            patch("db.postgres.get_conn", return_value=_Connection(cursor)),
        ):
            result = discord._last_trade_timestamps()

        self.assertEqual(result, {"spy_qqq_trend": activity_at})
        self.assertIn("FROM alpaca_etf_positions", cursor.sql)
        self.assertIn("opened_at", cursor.sql)
        self.assertIn("closed_at", cursor.sql)
        self.assertNotIn("FROM trades", cursor.sql)
        self.assertEqual(cursor.params, (list(discord._ETF_LEDGER_TO_ACTIVE_BOT),))