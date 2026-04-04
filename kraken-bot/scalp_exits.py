from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Literal


def check_scalp_exits(
    side: Literal["long", "short"],
    entry_price: float,
    current_price: float,
    best_price: float,
    entry_time: str | None,
    tp_pct: float = 0.004,
    sl_pct: float = 0.002,
    stagnancy_minutes: float = 5.0,
    stagnancy_deadzone: float = 0.001,
    latency_tax_pct: float = 0.0005,
    atr: float = 0.0,
    atr_stop_price: float | None = None,
) -> Optional[str]:
    if side == "long":
        raw_pnl_pct = (current_price - entry_price) / entry_price
    else:
        raw_pnl_pct = (entry_price - current_price) / entry_price

    net_pnl_pct = raw_pnl_pct - latency_tax_pct

    if atr_stop_price is not None:
        if side == "long" and current_price <= atr_stop_price:
            return "scalp_atr_stop"
        elif side == "short" and current_price >= atr_stop_price:
            return "scalp_atr_stop"

    if side == "long":
        sl_price = entry_price * (1.0 - sl_pct)
        if current_price <= sl_price:
            return "scalp_stop"
    else:
        sl_price = entry_price * (1.0 + sl_pct)
        if current_price >= sl_price:
            return "scalp_stop"

    if net_pnl_pct >= tp_pct:
        return "scalp_tp"

    if best_price > entry_price and side == "long":
        trail_stop = best_price * (1.0 - sl_pct)
        if current_price <= trail_stop:
            return "scalp_trail"
    elif best_price < entry_price and side == "short":
        trail_stop = best_price * (1.0 + sl_pct)
        if current_price >= trail_stop:
            return "scalp_trail"

    if entry_time:
        try:
            et = datetime.fromisoformat(entry_time)
            minutes_held = (datetime.now(tz=timezone.utc) - et).total_seconds() / 60.0
        except Exception:
            minutes_held = 0.0

        if minutes_held >= stagnancy_minutes:
            price_move_pct = abs(raw_pnl_pct)
            if price_move_pct <= stagnancy_deadzone:
                return "scalp_stagnant"

    return None
