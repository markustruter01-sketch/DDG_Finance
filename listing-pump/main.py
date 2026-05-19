"""Listing Pump main loop.

- Reads unprocessed 'listing_announced' signals
- Opens position immediately if asset has CoinGecko price available
- Monitors positions for exits (TP/SL/trail/timeout)
"""
import time
import logging
import json
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
# Reverse-priority order so _HERE ends up at index 0 (same pattern as event-trader).
# This prevents crypto-signals or trading-platform modules from shadowing listing-pump's own.
sys.path.insert(0, os.path.join(_HERE, '..', 'trading-platform'))
sys.path.insert(0, os.path.join(_HERE, '..', 'crypto-signals'))
sys.path.insert(0, _HERE)

import config as cfg
import strategy
import paper_portfolio as pp
from db_utils import record_trade
from signal_writer import read_unprocessed_signals, mark_processed
from price_cache import get_price, update_price as cache_update_price
from http_client import RateLimitedClient
from core.bot_state import touch_heartbeat, write_portfolio

logger = logging.getLogger("listing-pump")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

CONTROL_FILE = os.path.join(_HERE, "listing_control.json")
_CLEANUP_FLAG = os.path.join(_HERE, ".cleanup_v1_done")
_http = RateLimitedClient()


def _sync_bot_portfolio() -> None:
    try:
        state = pp._load()
        write_portfolio(
            bot_id=cfg.BOT_ID,
            cash=state["cash_usd"],
            equity=pp.get_equity(),
            positions=list(state["positions"].values()),
            metadata={"source": cfg.BOT_ID, "via": "wild_bot_sync"},
        )
    except Exception as e:
        logger.debug(f"bot_portfolio sync failed: {e}")


def _is_tradeable_listing(asset: str, price: float, exchange) -> bool:
    exchange = (exchange or "") if isinstance(exchange, str) else ""
    if price < 0.001:
        logger.info(f"{asset}: price ${price:.8f} below $0.001 threshold, skipping")
        return False
    if exchange.lower() == "coingecko":
        logger.info(f"{asset}: CoinGecko-only listing, skipping")
        return False
    return True


def _run_startup_cleanup() -> None:
    if os.path.exists(_CLEANUP_FLAG):
        return
    state = pp._load()
    positions = list(state["positions"].keys())
    if positions:
        logger.warning(f"universe_purge: closing {len(positions)} bogus position(s) at entry price")
        for asset in positions:
            pos = state["positions"].get(asset)
            if pos is None:
                continue
            entry_price = pos["entry_price"]
            trade = pp.close_position(asset, entry_price, "universe_purge")
            if trade:
                record_trade(trade)
                logger.warning(f"universe_purge: closed {asset} @ ${entry_price:.8f} pnl=$0.00")
    with open(_CLEANUP_FLAG, "w") as f:
        f.write("done")
    logger.info("universe_purge: cleanup complete, flag written")

# Inlined from crypto-signals/config.py to avoid sys.path collision with
# trading-platform/config/__init__.py when both are on sys.path.
COINGECKO_BASE    = "https://api.coingecko.com/api/v3"
COINGECKO_MAX_RPM = 25


def is_paused() -> bool:
    if os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE) as f:
            return json.load(f).get("bot_paused", True)
    return True


def _get_coingecko_price(symbol: str):
    """Try to fetch current price for a newly-listed asset from CoinGecko."""
    try:
        url = f"{COINGECKO_BASE}/simple/price?ids={symbol.lower()}&vs_currencies=usd"
        resp = _http.get("coingecko", url, COINGECKO_MAX_RPM)
        if resp.status_code != 200:
            return None
        data = resp.json()
        for k, v in data.items():
            if "usd" in v:
                return float(v["usd"])
        return None
    except Exception:
        return None


def process_listing_signals():
    if pp.position_count() >= cfg.MAX_POSITIONS:
        return
    signals = read_unprocessed_signals(signal_type="listing_announced")
    for sig in signals:
        asset = sig["asset"]
        if pp.has_position(asset):
            mark_processed(sig["id"])
            continue
        payload = sig.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        price = get_price(asset) or _get_coingecko_price(asset)
        if price is None:
            logger.info(f"no price for {asset}, skipping listing")
            mark_processed(sig["id"])
            continue
        exchange = payload.get("exchange", "")
        if not _is_tradeable_listing(asset, price, exchange):
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
            exchange=exchange,
            listing_title=payload.get("title", ""),
        )
        logger.warning(f"OPENED: {asset} from {exchange} units={units:.4f} @ ${price:.4f}")
        mark_processed(sig["id"])
        if pp.position_count() >= cfg.MAX_POSITIONS:
            break


def monitor_open_positions():
    state = pp._load()
    for asset, pos in list(state["positions"].items()):
        current_price = get_price(asset) or _get_coingecko_price(asset)
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
                logger.warning(f"CLOSED: {asset} pnl=${trade['pnl_usd']:.2f} reason={reason}")


import socket as _ka_socket
import threading as _ka_threading

def _keep_alive_listener():
    """Bind to $PORT to satisfy Replit's port-readiness check."""
    try:
        port = int(os.environ.get("PORT", "8098"))
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
    logger.info("listing-pump | starting up")
    try:
        _run_startup_cleanup()
    except Exception as e:
        logger.error(f"startup cleanup failed (continuing): {e}")
    while True:
        try:
            if is_paused():
                touch_heartbeat(cfg.BOT_ID, status="paused", error="")
            else:
                process_listing_signals()
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
