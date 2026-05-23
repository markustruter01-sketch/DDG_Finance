"""Daily cycle: refresh universe → rank → enter/manage/exit → write state."""
import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_TP   = os.path.abspath(os.path.join(_HERE, "..", "trading-platform"))
# Add trading-platform with normalized path so bot_state.py's own guard won't
# re-insert it at [0] later.  Then UNCONDITIONALLY anchor momentum-bot at [0]
# so momentum-bot/config.py always beats trading-platform/config/__init__.py.
if _TP not in sys.path:
    sys.path.insert(0, _TP)
sys.path.insert(0, _HERE)   # always first — may create a harmless duplicate
from core.bot_state import write_portfolio, touch_heartbeat

from config import (BOT_ID, RANK_PICK, POSITION_SIZE_PCT,
                    ENTRY_RANK_THRESHOLD, EXIT_RANK_THRESHOLD,
                    MAX_HOLD_DAYS, CYCLE_HOUR_UTC, CYCLE_MINUTE_UTC)
import paper_portfolio as pp
import strategy as strat
import universe as univ
import db_utils

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s | {BOT_ID} | %(levelname)s | %(message)s",
)
logger = logging.getLogger(BOT_ID)


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass


def _start_health():
    port = int(os.environ.get("PORT", "8101"))
    HTTPServer(("0.0.0.0", port), _Health).serve_forever()


def _sync_portfolio(price_lookup):
    equity = pp.get_equity(price_lookup)
    state  = pp._load()
    positions_list = [{"symbol": k, **v} for k, v in state["positions"].items()]
    write_portfolio(
        bot_id=BOT_ID,
        cash=state["cash_usd"],
        equity=equity,
        positions=positions_list,
    )


def run_cycle():
    logger.info(f"=== CYCLE START — rank pick {RANK_PICK} ===")
    touch_heartbeat(BOT_ID)

    universe  = univ.refresh_if_needed()
    logger.info(f"Universe size: {len(universe)}")

    ranked = strat.rank_universe(universe)
    logger.info(f"Ranked signals: {len(ranked)} (top: {[r['symbol'] for r in ranked[:5]]})")

    top_symbols    = {r["symbol"]: r for r in ranked[:EXIT_RANK_THRESHOLD]}
    price_lookup   = {r["symbol"]: r["close"] for r in ranked}
    open_positions = pp.get_open_positions()

    for sym, pos in list(open_positions.items()):
        current = price_lookup.get(sym)
        if current is None:
            df = strat.fetch_ohlcv(pos.get("binance_pair", f"{sym}/USDT"))
            if df is None:
                continue
            ind     = strat.compute_indicators(df)
            current = ind["close"]
            price_lookup[sym] = current
        else:
            ind = top_symbols.get(sym, {})

        atr = ind.get("atr", 0) if ind else 0
        if atr:
            pp.update_trailing_stop(sym, current, atr)

        exit_reason = None
        if pp.check_stop_hit(sym, current):
            exit_reason = "trailing_stop"
        elif sym not in top_symbols:
            exit_reason = "rank_dropout"
        elif top_symbols[sym]["direction"] != pos["direction"]:
            exit_reason = "direction_flip"
        else:
            try:
                opened = datetime.fromisoformat(pos["opened_at"])
                if (datetime.utcnow() - opened).days >= MAX_HOLD_DAYS:
                    exit_reason = "max_hold"
            except Exception:
                pass

        if exit_reason:
            closed = pp.close_position(sym, current, exit_reason)
            if closed:
                db_utils.record_close(
                    BOT_ID, sym, current,
                    closed["realised_pnl_usd"], exit_reason,
                )
                logger.info(
                    f"CLOSED {sym} {closed['direction']} "
                    f"P&L=${closed['realised_pnl_usd']:.2f} reason={exit_reason}"
                )

    if not pp.get_open_positions():
        if len(ranked) >= RANK_PICK:
            pick     = ranked[RANK_PICK - 1]
            equity   = pp.get_equity(price_lookup)
            notional = equity * POSITION_SIZE_PCT
            qty      = notional / pick["close"]
            atr      = pick["atr"]
            if pick["direction"] == "long":
                trailing_stop = pick["close"] - (atr * 2.0)
            else:
                trailing_stop = pick["close"] + (atr * 2.0)
            pp.open_position(
                pick["symbol"], pick["direction"], qty,
                pick["close"], trailing_stop,
                pick["ema20"], pick["ema50"], pick["adx"],
                entry_reason=f"rank_{RANK_PICK}",
            )
            db_utils.record_open(
                BOT_ID, pick["symbol"], pick["direction"],
                qty, pick["close"], f"rank_{RANK_PICK}",
                pick["ema20"], pick["ema50"], pick["adx"],
            )
            logger.info(
                f"OPENED {pick['symbol']} {pick['direction']} "
                f"qty={qty:.4f} @ ${pick['close']:.4f} "
                f"score={pick['score']:.4f}"
            )
        else:
            logger.info(f"No ranked signal at position {RANK_PICK} — holding cash")

    _sync_portfolio(price_lookup)
    logger.info("=== CYCLE END ===")


def _next_cycle_target(now: datetime) -> datetime:
    """Return next 00:05 UTC (today or tomorrow)."""
    target = now.replace(
        hour=CYCLE_HOUR_UTC, minute=CYCLE_MINUTE_UTC, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=1)
    return target


def main():
    Thread(target=_start_health, daemon=True).start()
    logger.info(f"Started. Cycle daily at {CYCLE_HOUR_UTC:02d}:{CYCLE_MINUTE_UTC:02d} UTC.")

    try:
        run_cycle()
    except Exception as e:
        logger.error(f"Initial cycle failed: {e}", exc_info=True)

    while True:
        now     = datetime.now(timezone.utc)
        target  = _next_cycle_target(now)
        sleep_s = (target - now).total_seconds()
        logger.info(f"Sleeping {sleep_s:.0f}s until next cycle at {target.isoformat()}")
        time.sleep(sleep_s)
        try:
            run_cycle()
        except Exception as e:
            logger.error(f"Cycle failed: {e}", exc_info=True)
            time.sleep(300)


if __name__ == "__main__":
    main()
