"""Stablecoin Depeg strategy logic."""
from typing import Optional
import config as cfg


def position_size_pct(severity: str) -> float:
    """Returns equity pct to allocate based on severity."""
    return {
        "medium":  cfg.POSITION_PCT_MEDIUM,
        "high":    cfg.POSITION_PCT_HIGH,
        "extreme": cfg.POSITION_PCT_EXTREME,
    }.get(severity, cfg.POSITION_PCT_MEDIUM)


def calculate_units(equity: float, depeg_price: float, severity: str) -> float:
    """How many units to buy at current depegged price."""
    pct = position_size_pct(severity)
    usd_allocation = equity * pct
    return usd_allocation / depeg_price if depeg_price > 0 else 0


def check_exit(entry_price: float, current_price: float,
               hours_held: float) -> Optional[str]:
    """Returns exit reason string or None if position should stay open."""
    if current_price >= cfg.REPEG_THRESHOLD:
        return "repegged"
    if current_price <= cfg.HARD_STOP_PRICE:
        return "hard_stop_floor"
    if hours_held >= cfg.MAX_HOLD_HOURS:
        return "max_hold_timeout"
    return None
