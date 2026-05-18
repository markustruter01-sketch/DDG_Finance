"""DB helper + trade recording for listing pump."""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'trading-platform'))

from db.postgres import get_conn


def record_trade(trade: dict, bot_id: str = "listing_pump"):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO listing_pump_trades
                  (bot_id, asset, exchange, entry_price, exit_price, units,
                   pnl_usd, reason, listing_title, entry_time, exit_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (bot_id, trade["asset"], trade.get("exchange", ""),
                  trade["entry_price"], trade["exit_price"], trade["units"],
                  trade["pnl_usd"], trade["reason"], trade.get("listing_title", ""),
                  trade["entry_time"], trade["exit_time"]))
