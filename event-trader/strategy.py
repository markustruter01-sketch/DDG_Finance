"""Event Trader strategy: enter pre-event, exit on/before event."""
from datetime import datetime, timedelta
from typing import Optional
import config as cfg


def should_enter(event_date: datetime, classification: str, now: datetime = None) -> bool:
    """Returns True if we should enter this event now."""
    if classification != cfg.CLASSIFICATION_HIGH:
        return False
    now = now or datetime.utcnow()
    days_until = (event_date - now).total_seconds() / 86400
    return 0 < days_until <= cfg.ENTRY_DAYS_BEFORE_EVENT


def calculate_units(equity: float, price: float) -> tuple:
    """Returns (units, allocated_usd) for a high-impact event."""
    if price <= 0:
        return (0, 0)
    allocation = equity * cfg.RISK_PCT_HIGH_IMPACT
    max_pos = equity * cfg.MAX_POSITION_FRACTION
    allocation = min(allocation, max_pos)
    units = allocation / price
    return (units, allocation)


def check_exit(position: dict, current_price: float,
               event_date: datetime, now: datetime = None) -> Optional[str]:
    """Returns exit reason or None.

    Exit conditions (in order):
    1. Hard stop -10% from entry
    2. Trailing stop -15% from peak (only after positive move)
    3. Event time arrived
    """
    now = now or datetime.utcnow()
    entry = position["entry_price"]
    peak = position.get("peak_price", entry)

    # Hard stop
    if current_price <= entry * (1 - cfg.HARD_STOP_PCT):
        return "hard_stop"

    # Trailing stop (only if we've ever been in profit)
    if peak > entry and current_price <= peak * (1 - cfg.TRAILING_STOP_PCT):
        return "trailing_stop"

    # Event time exit
    if now >= event_date:
        return "event_time_exit"

    return None


def is_partial_exit_due(position: dict, event_date: datetime, now: datetime = None) -> bool:
    """Returns True if we should exit 50% (24h before event)."""
    if position.get("partial_exited", False):
        return False
    now = now or datetime.utcnow()
    hours_until = (event_date - now).total_seconds() / 3600
    return hours_until <= cfg.PARTIAL_EXIT_HOURS_BEFORE and hours_until > 0
