from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Literal


def check_swing_exits(
    side: Literal["long", "short"],
    entry_price: float,
    current_price: float,
    best_price: float,
    entry_time: str | None,
    atr: float,
    tp_atr_mult: float = 3.0,
    sl_atr_mult: float = 1.5,
    trail_trigger_atr: float = 1.0,
    trail_atr_mult: float = 1.5,
    min_hold_hours: float = 4.0,
    max_hold_hours: float = 72.0,
    fee_rate: float = 0.0026,
) -> Optional[str]:
    if atr <= 0 or entry_price <= 0:
        return None

    hours_held = 0.0
    if entry_time:
        try:
            et = datetime.fromisoformat(entry_time)
            hours_held = (datetime.now(tz=timezone.utc) - et).total_seconds() / 3600.0
        except Exception:
            hours_held = 0.0

    if side == "long":
        pnl_usd = current_price - entry_price
        best_pnl_usd = best_price - entry_price
    else:
        pnl_usd = entry_price - current_price
        best_pnl_usd = entry_price - best_price

    sl_dist = atr * sl_atr_mult
    if side == "long":
        sl_price = entry_price - sl_dist
        if current_price <= sl_price:
            return "swing_stop_loss"
    else:
        sl_price = entry_price + sl_dist
        if current_price >= sl_price:
            return "swing_stop_loss"

    tp_dist = atr * tp_atr_mult
    if pnl_usd >= tp_dist:
        return "swing_take_profit"

    trail_trigger_dist = atr * trail_trigger_atr   # profit threshold to activate trail

    if best_pnl_usd >= trail_trigger_dist:
        # Trail is active — stop trails at trail_atr_mult × ATR below/above best price.
        # No dead zone. No breakeven trap. Position either keeps running or stops out
        # at a defined distance from its best level.
        trail_stop_dist = atr * trail_atr_mult

        if side == "long":
            trail_stop_price = best_price - trail_stop_dist
            if current_price <= trail_stop_price:
                return "swing_trailing_stop"
        else:
            trail_stop_price = best_price + trail_stop_dist
            if current_price >= trail_stop_price:
                return "swing_trailing_stop"

    if hours_held >= max_hold_hours:
        return "swing_time_expiry"

    if hours_held >= max_hold_hours * 0.75:
        round_trip_fees = entry_price * fee_rate * 2.0
        if pnl_usd > round_trip_fees:
            return "swing_time_profit_lock"

    return None
