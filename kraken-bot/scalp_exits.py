"""
═══════════════════════════════════════════════════════════════════
  DEPRECATED SCALPING EXIT MODULE
  ────────────────────────────────
  This scalp exit logic was used by Blackbeard and Calypso when
  they ran scalping strategies.  Both strategies were structurally
  unprofitable and have been retired.

  Replaced by:
    swing_exits.py  →  check_swing_exits()

  This file is kept for reference only.  Do not import from it in
  production code.
═══════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Literal


def check_scalp_exits(
    side: Literal["long", "short"],
    entry_price: float,
    current_price: float,
    best_price: float,
    entry_time: str | None,
    tp_pct: float = 0.010,
    sl_pct: float = 0.005,
    stagnancy_minutes: float = 15.0,
    stagnancy_deadzone: float = 0.002,
    latency_tax_pct: float = 0.0005,
    atr: float = 0.0,
    atr_stop_price: float | None = None,
    fee_rate: float = 0.0026,
) -> Optional[str]:
    round_trip_fees = fee_rate * 2.0

    eff_tp = tp_pct
    eff_sl = sl_pct
    if atr > 0 and entry_price > 0:
        atr_pct = atr / entry_price
        eff_tp = max(tp_pct, min(atr_pct * 0.5, 0.025))
        eff_sl = max(sl_pct, min(atr_pct * 0.4, 0.020))

    if side == "long":
        raw_pnl_pct = (current_price - entry_price) / entry_price
    else:
        raw_pnl_pct = (entry_price - current_price) / entry_price

    net_pnl_pct = raw_pnl_pct - round_trip_fees - latency_tax_pct

    if atr_stop_price is not None:
        if side == "long" and current_price <= atr_stop_price:
            return "scalp_atr_stop"
        elif side == "short" and current_price >= atr_stop_price:
            return "scalp_atr_stop"

    if side == "long":
        sl_price = entry_price * (1.0 - eff_sl)
        if current_price <= sl_price:
            return "scalp_stop"
    else:
        sl_price = entry_price * (1.0 + eff_sl)
        if current_price >= sl_price:
            return "scalp_stop"

    if net_pnl_pct >= eff_tp:
        return "scalp_tp"

    if best_price > entry_price and side == "long":
        trail_stop = best_price * (1.0 - eff_sl)
        if current_price <= trail_stop:
            return "scalp_trail"
    elif best_price < entry_price and side == "short":
        trail_stop = best_price * (1.0 + eff_sl)
        if current_price >= trail_stop:
            return "scalp_trail"

    if entry_time:
        try:
            et = datetime.fromisoformat(entry_time)
            minutes_held = (datetime.now(tz=timezone.utc) - et).total_seconds() / 60.0
        except Exception:
            minutes_held = 0.0

        if minutes_held >= 10.0 and net_pnl_pct > 0:
            return "scalp_tp"

        if minutes_held >= stagnancy_minutes:
            if net_pnl_pct > 0:
                return "scalp_tp"

        forced_exit_minutes = stagnancy_minutes * 3.0
        if minutes_held >= forced_exit_minutes:
            price_move_pct = abs(raw_pnl_pct)
            if price_move_pct <= stagnancy_deadzone * 2.0:
                return "scalp_stagnant"

    return None
