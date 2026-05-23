"""Trade journal writes to momentum_bot_trades."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TP   = os.path.abspath(os.path.join(_HERE, "..", "trading-platform"))
if _TP not in sys.path: sys.path.insert(0, _TP)
sys.path.insert(0, _HERE)
from db.postgres import get_conn


def record_open(bot_id, symbol, direction, qty, entry_price,
                entry_reason, ema20, ema50, adx):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO momentum_bot_trades
                    (bot_id, symbol, direction, qty, entry_price,
                     entry_reason, ema20_at_entry, ema50_at_entry, adx_at_entry, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
                """,
                (bot_id, symbol, direction, qty, entry_price,
                 entry_reason, ema20, ema50, adx),
            )


def record_close(bot_id, symbol, exit_price, realised_pnl, exit_reason):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE momentum_bot_trades
                SET exit_price       = %s,
                    realised_pnl_usd = %s,
                    exit_reason      = %s,
                    closed_at        = NOW(),
                    status           = 'closed'
                WHERE bot_id = %s AND symbol = %s AND status = 'open'
                """,
                (exit_price, realised_pnl, exit_reason, bot_id, symbol),
            )
