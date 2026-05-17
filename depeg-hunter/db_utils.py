"""DB helper + trade recording for depeg hunter."""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.insert(0, _TRADING_PLATFORM)


def _get_conn():
    from db.postgres import get_conn
    return get_conn()


def record_trade(trade: dict, bot_id: str = "depeg_hunter") -> None:
    """Insert a closed trade into depeg_hunter_trades."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO depeg_hunter_trades
                    (bot_id, stable, entry_price, exit_price, units,
                     pnl_usd, reason, severity, entry_time, exit_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    bot_id,
                    trade["stable"],
                    trade["entry_price"],
                    trade["exit_price"],
                    trade["units"],
                    trade["pnl_usd"],
                    trade["reason"],
                    trade["severity"],
                    trade["entry_time"],
                    trade["exit_time"],
                ),
            )
