"""Depeg Hunter main loop.

- Reads unprocessed 'stablecoin_depegged' signals from crypto_signals
- Opens position if not already in position for that stable
- Monitors open positions for repeg / timeout / hard stop
- Closes and records trades
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime

# ── path setup (run from any CWD) ─────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "crypto-signals"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "trading-platform"))
sys.path.insert(0, _HERE)   # must be last insert → position 0 so depeg-hunter/db_utils wins over crypto-signals/db_utils
# ──────────────────────────────────────────────────────────────────────────────

import config as cfg
import strategy
import paper_portfolio as pp
from db_utils import record_trade
from signal_writer import read_unprocessed_signals, mark_processed
from price_cache import get_price
from core.bot_state import touch_heartbeat, write_portfolio

logger = logging.getLogger("depeg-hunter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

CONTROL_FILE = os.path.join(_HERE, "depeg_control.json")


def _sync_bot_portfolio() -> None:
    try:
        state = pp._load()
        write_portfolio(
            bot_id=cfg.BOT_ID,
            cash=state["cash_usd"],
            equity=pp.get_equity(),
            positions=list(state["positions"].values()),
        )
    except Exception as e:
        logger.debug(f"bot_portfolio sync failed: {e}")


def is_paused() -> bool:
    if os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE) as f:
            return json.load(f).get("bot_paused", True)
    return True


def process_depeg_signals() -> None:
    """Read new depeg signals and open positions."""
    if pp.position_count() >= cfg.MAX_POSITIONS:
        return
    signals = read_unprocessed_signals(signal_type="stablecoin_depegged")
    for sig in signals:
        stable = sig["asset"]
        if pp.has_position(stable):
            mark_processed(sig["id"])
            continue
        payload = sig["payload"] if isinstance(sig["payload"], dict) else json.loads(sig["payload"])
        price   = payload.get("price_usd")
        if price is None or price >= cfg.REPEG_THRESHOLD:
            mark_processed(sig["id"])
            continue
        equity = pp.get_equity()
        units  = strategy.calculate_units(equity, price, sig["severity"])
        if units * price > pp.get_cash():
            logger.info(f"insufficient cash for {stable}, skipping")
            mark_processed(sig["id"])
            continue
        pp.open_position(stable, units, price, sig["severity"])
        logger.warning(f"OPENED: {stable} units={units:.2f} @ ${price:.4f} severity={sig['severity']}")
        mark_processed(sig["id"])
        if pp.position_count() >= cfg.MAX_POSITIONS:
            break


def monitor_open_positions() -> None:
    """Check each open position for exit conditions."""
    state = pp._load()
    for stable, pos in list(state["positions"].items()):
        current_price = get_price(stable)
        if current_price is None:
            continue
        pp.update_position_price(stable, current_price)
        entry_dt   = datetime.fromisoformat(pos["entry_time"])
        hours_held = (datetime.utcnow() - entry_dt).total_seconds() / 3600
        reason     = strategy.check_exit(pos["entry_price"], current_price, hours_held)
        if reason:
            trade = pp.close_position(stable, current_price, reason)
            if trade:
                record_trade(trade)
                logger.warning(f"CLOSED: {stable} pnl=${trade['pnl_usd']:.2f} reason={reason}")


import socket as _ka_socket
import threading as _ka_threading

def _keep_alive_listener():
    """Bind to $PORT to satisfy Replit's port-readiness check."""
    try:
        port = int(os.environ.get("PORT", "8096"))
        s = _ka_socket.socket(_ka_socket.AF_INET, _ka_socket.SOCK_STREAM)
        s.setsockopt(_ka_socket.SOL_SOCKET, _ka_socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        while True:
            conn, _ = s.accept()
            conn.close()
    except Exception as _e:
        pass

_ka_threading.Thread(target=_keep_alive_listener, daemon=True).start()


def main() -> None:
    logger.info("depeg-hunter | starting up")
    while True:
        try:
            if is_paused():
                touch_heartbeat(cfg.BOT_ID, status="paused", error="")
            else:
                process_depeg_signals()
                monitor_open_positions()
                _sync_bot_portfolio()
                touch_heartbeat(cfg.BOT_ID, status="running", error="")
        except Exception as e:
            logger.error(f"main loop error: {e}")
            try:
                touch_heartbeat(cfg.BOT_ID, status="error", error=str(e)[:200])
            except Exception:
                pass
        time.sleep(cfg.LOOP_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
