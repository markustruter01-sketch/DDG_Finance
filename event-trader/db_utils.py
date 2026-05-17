"""DB helper + trade recording for event trader."""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'trading-platform'))

from db.postgres import get_conn


def record_trade(trade: dict, bot_id: str = "event_trader"):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO event_trader_trades
                  (bot_id, event_id, asset, entry_price, exit_price, units,
                   pnl_usd, reason, classification, entry_time, exit_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (bot_id, trade["event_id"], trade["asset"],
                  trade["entry_price"], trade["exit_price"], trade["units"],
                  trade["pnl_usd"], trade["reason"], trade["classification"],
                  trade["entry_time"], trade["exit_time"]))
