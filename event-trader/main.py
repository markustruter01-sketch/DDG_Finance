"""Event Trader main loop.

- Refreshes event calendar every 6h
- Classifies each event via Groq
- Enters HIGH-impact events 5 days before
- Manages partial + full exits
"""
import time
import logging
import json
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, '..', 'crypto-signals'))
sys.path.insert(0, os.path.join(_HERE, '..', 'trading-platform'))

import config as cfg
import strategy
import paper_portfolio as pp
import event_sources
import event_classifier
from db_utils import record_trade
from price_cache import get_price
from core.bot_state import touch_heartbeat

logger = logging.getLogger("event-trader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

CONTROL_FILE = os.path.join(_HERE, "event_control.json")
_event_cache = {"events": [], "last_refresh": 0}


def is_paused() -> bool:
    if os.path.exists(CONTROL_FILE):
        with open(CONTROL_FILE) as f:
            return json.load(f).get("bot_paused", True)
    return True


def refresh_events():
    """Refresh upcoming events + classify any new ones."""
    if time.time() - _event_cache["last_refresh"] < cfg.EVENT_CALENDAR_REFRESH_HOURS * 3600:
        return
    logger.info("refreshing event calendar...")
    events = event_sources.get_all_upcoming_events(days_ahead=30)
    classified = []
    for e in events:
        existing = next((c for c in _event_cache["events"] if c["id"] == e["id"]), None)
        if existing and existing.get("classification"):
            classified.append(existing)
            continue
        cls = event_classifier.classify_event(e)
        e["classification"] = cls or "LOW"
        classified.append(e)
        logger.info(f"classified {e['id']} ({e['asset']}): {e['classification']}")
    _event_cache["events"] = classified
    _event_cache["last_refresh"] = time.time()


def process_entries():
    """Open positions for HIGH-impact events within entry window."""
    if pp.position_count() >= cfg.MAX_POSITIONS:
        return
    now = datetime.utcnow()
    for e in _event_cache["events"]:
        if e["classification"] != cfg.CLASSIFICATION_HIGH:
            continue
        if pp.has_position(e["id"]):
            continue
        try:
            event_dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            if event_dt.tzinfo:
                event_dt = event_dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if not strategy.should_enter(event_dt, e["classification"], now):
            continue
        symbol = f"{e['asset']}/USD"
        price = get_price(symbol)
        if price is None:
            logger.warning(f"no price for {symbol}, skipping {e['id']}")
            continue
        equity = pp.get_equity()
        units, alloc = strategy.calculate_units(equity, price)
        if alloc > pp.get_cash() or units <= 0:
            continue
        pp.open_position(e["id"], e["asset"], units, price, event_dt, e["classification"])
        logger.warning(f"OPENED: {e['id']} ({e['asset']}) units={units:.4f} @ ${price:.2f}")
        if pp.position_count() >= cfg.MAX_POSITIONS:
            break


def monitor_positions():
    """Check exits on all open positions."""
    state = pp._load()
    now = datetime.utcnow()
    for event_id, pos in list(state["positions"].items()):
        symbol = f"{pos['asset']}/USD"
        current_price = get_price(symbol)
        if current_price is None:
            continue
        pp.update_position_price(event_id, current_price)
        try:
            event_dt = datetime.fromisoformat(pos["event_date"].replace("Z", "+00:00"))
            if event_dt.tzinfo:
                event_dt = event_dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if strategy.is_partial_exit_due(pos, event_dt, now):
            trade = pp.partial_close(event_id, current_price, fraction=0.5)
            if trade:
                record_trade(trade)
                logger.warning(f"PARTIAL: {event_id} pnl=${trade['pnl_usd']:.2f}")
            continue
        reason = strategy.check_exit(pos, current_price, event_dt, now)
        if reason:
            trade = pp.close_position(event_id, current_price, reason)
            if trade:
                record_trade(trade)
                logger.warning(f"CLOSED: {event_id} pnl=${trade['pnl_usd']:.2f} reason={reason}")


def main():
    logger.info("event-trader | starting up")
    while True:
        try:
            if is_paused():
                touch_heartbeat(cfg.BOT_ID, status="paused", error="")
            else:
                refresh_events()
                process_entries()
                monitor_positions()
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
