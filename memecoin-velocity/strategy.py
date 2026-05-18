"""Memecoin Velocity strategy."""
import json
import os
from datetime import datetime, timedelta
from typing import Optional
import config as cfg

_HERE = os.path.dirname(os.path.abspath(__file__))
COOLDOWN_FILE = os.path.join(_HERE, "memecoin_cooldown.json")


def _load_cooldown() -> dict:
    if os.path.exists(COOLDOWN_FILE):
        with open(COOLDOWN_FILE) as f:
            return json.load(f)
    return {}


def _save_cooldown(d: dict):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(d, f, indent=2)


def is_in_cooldown(symbol: str) -> bool:
    cd = _load_cooldown()
    last_exit = cd.get(symbol)
    if not last_exit:
        return False
    last_dt = datetime.fromisoformat(last_exit)
    return (datetime.utcnow() - last_dt) < timedelta(days=cfg.COOLDOWN_DAYS)


def mark_cooldown(symbol: str):
    cd = _load_cooldown()
    cd[symbol] = datetime.utcnow().isoformat()
    _save_cooldown(cd)


def calculate_units(equity: float, price: float) -> tuple:
    if price <= 0:
        return (0, 0)
    allocation = equity * cfg.POSITION_PCT_PER_TRADE
    max_pos = equity * cfg.MAX_POSITION_FRACTION
    allocation = min(allocation, max_pos)
    units = allocation / price
    return (units, allocation)


def check_exit(position: dict, current_price: float, hours_held: float) -> Optional[str]:
    entry = position["entry_price"]
    peak  = position.get("peak_price", entry)

    if current_price <= entry * (1 - cfg.HARD_STOP_PCT):
        return "hard_stop"
    if current_price >= entry * (1 + cfg.TAKE_PROFIT_PCT):
        return "take_profit"
    if peak > entry and current_price <= peak * (1 - cfg.TRAILING_STOP_PCT):
        return "trailing_stop"
    if hours_held >= cfg.MAX_HOLD_HOURS:
        return "max_hold_timeout"
    return None
