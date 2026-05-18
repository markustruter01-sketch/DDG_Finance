"""DB helper + trade recording for memecoin velocity."""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'trading-platform'))

from db.postgres import get_conn


def record_trade(trade: dict, bot_id: str = "memecoin_velocity"):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO memecoin_velocity_trades
                  (bot_id, asset, pair, entry_price, exit_price, units,
                   pnl_usd, reason, volume_ratio, reddit_mentions,
                   entry_time, exit_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (bot_id, trade["asset"], trade.get("pair", ""),
                  trade["entry_price"], trade["exit_price"], trade["units"],
                  trade["pnl_usd"], trade["reason"],
                  trade.get("volume_ratio", 0), trade.get("reddit_mentions", 0),
                  trade["entry_time"], trade["exit_time"]))
