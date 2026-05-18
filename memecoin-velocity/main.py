"""Memecoin Velocity main loop.

- Reads unprocessed 'memecoin_breakout' signals (triple-gated by crypto-signals)
- Opens position if cooldown clear and price available
- Monitors positions for exits (TP/SL/trail/timeout)
"""
import time
import logging
import json
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
# Reverse-priority order so _HERE ends up at index 0 (same pattern as listing-pump).
sys.path.insert(0, os.path.join(_HERE, '..', 'trading-platform'))
sys.path.insert(0, os.path.join(_HERE, '..', 'crypto-signals'))
sys.path.insert(0, _HERE)

import config as cfg
import strategy
import paper_portfolio as pp
from db_utils import record_trade
from signal_writer import read_unprocessed_signals, mark_processed
from price_cache import get_price, update_price as cache_update_price
from core.bot_state import touch_heartbeat

logger = logging.getLogger("memecoin-velocity")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

CONTROL_FILE = os.path.join(_HERE, "memecoin_control.json")


def is_paused() -> bool:
    if os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE) as f:
            return json.load(f).get("bot_paused", True)
    return True


def _get_ccxt_price(pair: str):
    """Fetch current price from Binance via ccxt public API."""
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
        ticker = exchange.fetch_ticker(pair)
        return float(ticker["last"]) if ticker.get("last") else None
    except Exception:
        return None


def _resolve_price(asset: str, payload: dict):
    """Try price cache first, then ccxt using pair from signal payload."""
    price = get_price(asset)
    if price:
        return price
    pair = payload.get("pair")
    if pair:
        price = _get_ccxt_price(pair)
        if price:
            return price
    # Fallback: try common pairs directly
    for suffix in ("USDT", "USD"):
        price = _get_ccxt_price(f"{asset}/{suffix}")
        if price:
            return price
    return None


def process_memecoin_signals():
    if pp.position_count() >= cfg.MAX_POSITIONS:
        return
    signals = read_unprocessed_signals(signal_type="memecoin_breakout")
    for sig in signals:
        asset = sig["asset"]
        if pp.has_position(asset):
            mark_processed(sig["id"])
            continue
        if strategy.is_in_cooldown(asset):
            logger.info(f"{asset}: in cooldown, skipping")
            mark_processed(sig["id"])
            continue
        payload = sig.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        price = _resolve_price(asset, payload)
        if price is None:
            logger.info(f"no price for {asset}, skipping memecoin signal")
            mark_processed(sig["id"])
            continue
        cache_update_price(asset, price)
        equity = pp.get_equity()
        units, alloc = strategy.calculate_units(equity, price)
        if alloc > pp.get_cash() or units <= 0:
            mark_processed(sig["id"])
            continue
        pp.open_position(
            asset, units, price,
            pair=payload.get("pair", ""),
            volume_ratio=payload.get("volume_ratio", 0.0),
            reddit_mentions=int(payload.get("reddit_mentions", 0)),
        )
        logger.warning(
            f"OPENED: {asset} pair={payload.get('pair')} "
            f"units={units:.4f} @ ${price:.6f} "
            f"vol={payload.get('volume_ratio', 0):.1f}x "
            f"reddit={payload.get('reddit_mentions', 0)}"
        )
        mark_processed(sig["id"])
        if pp.position_count() >= cfg.MAX_POSITIONS:
            break


def monitor_open_positions():
    state = pp._load()
    for asset, pos in list(state["positions"].items()):
        pair = pos.get("pair", f"{asset}/USDT")
        current_price = get_price(asset) or _get_ccxt_price(pair)
        if current_price is None:
            continue
        pp.update_position_price(asset, current_price)
        entry_dt = datetime.fromisoformat(pos["entry_time"])
        hours_held = (datetime.utcnow() - entry_dt).total_seconds() / 3600
        reason = strategy.check_exit(pos, current_price, hours_held)
        if reason:
            trade = pp.close_position(asset, current_price, reason)
            if trade:
                record_trade(trade)
                strategy.mark_cooldown(asset)
                logger.warning(f"CLOSED: {asset} pnl=${trade['pnl_usd']:.2f} reason={reason}")


import socket as _ka_socket
import threading as _ka_threading

def _keep_alive_listener():
    """Bind to $PORT to satisfy Replit's port-readiness check."""
    try:
        port = int(os.environ.get("PORT", "8099"))
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


def main():
    logger.info("memecoin-velocity | starting up")
    while True:
        try:
            if is_paused():
                touch_heartbeat(cfg.BOT_ID, status="paused", error="")
            else:
                process_memecoin_signals()
                monitor_open_positions()
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
