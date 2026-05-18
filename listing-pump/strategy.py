"""Listing Pump strategy."""
from typing import Optional
import config as cfg


def calculate_units(equity: float, price: float) -> tuple:
    if price <= 0:
        return (0, 0)
    allocation = equity * cfg.POSITION_PCT_PER_LISTING
    max_pos = equity * cfg.MAX_POSITION_FRACTION
    allocation = min(allocation, max_pos)
    units = allocation / price
    return (units, allocation)


def check_exit(position: dict, current_price: float, hours_held: float) -> Optional[str]:
    entry = position["entry_price"]
    peak = position.get("peak_price", entry)

    # Hard stop
    if current_price <= entry * (1 - cfg.HARD_STOP_PCT):
        return "hard_stop"

    # Take profit
    if current_price >= entry * (1 + cfg.TAKE_PROFIT_PCT):
        return "take_profit"

    # Trailing stop (only after profit)
    if peak > entry and current_price <= peak * (1 - cfg.TRAILING_STOP_PCT):
        return "trailing_stop"

    # Max hold
    if hours_held >= cfg.MAX_HOLD_HOURS:
        return "max_hold_timeout"

    return None
