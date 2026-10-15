"""Position sizing shared by backtests and the live sleeve runtime.

One definition, so the live sleeve buys exactly what the backtest assumed.
"""

from __future__ import annotations

import math


def target_shares(weight: float, equity: float, price: float, *, whole_shares: bool) -> float:
    """Shares for a target weight of equity at a price. Whole shares round toward zero."""
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    shares = weight * equity / price
    return float(math.trunc(shares)) if whole_shares else shares


def stop_price(entry: float, *, long: bool, stop_pct: float) -> float:
    """Protective stop stop_pct away from the reference price."""
    if not 0 < stop_pct < 1:
        raise ValueError("stop_pct must be between 0 and 1")
    return entry * (1 - stop_pct) if long else entry * (1 + stop_pct)
