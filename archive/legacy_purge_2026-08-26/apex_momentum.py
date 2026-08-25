"""
apex_momentum.py — Dual-Timeframe Momentum Signal Engine for Apex Predator
===========================================================================
Evaluates entry/exit signals for the Apex Predator crypto momentum scalper.

Entry logic (LONG):
  1. 1h RSI crossed upward through the oversold threshold (prev < threshold ≤ current)
  2. 4h price is above both EMA-20 and EMA-50 (uptrend confirmed)
  3. Latest 1h volume ≥ 1.5× 20-bar volume average
  4. VPIN ≤ 0.80 (no toxic/informed flow)

Entry logic (SHORT):
  1. 1h RSI crossed downward through the overbought threshold
  2. 4h price is below both EMA-20 and EMA-50 (downtrend confirmed)
  3. Latest 1h volume ≥ 1.5× 20-bar volume average
  4. VPIN ≤ 0.80

Exit logic (ATR-based):
  - Stop-loss       : entry_price ± 1.5 × ATR(14)   [fixed]
  - Take-profit     : entry_price ± 3.0 × ATR(14)   [fixed]
  - Trailing stop   : activates once price moves +1.5 × ATR in profit direction;
                      once activated, trails at 1.5 × ATR from the best price seen.

All calculation helpers are pure functions; they never mutate shared state.
Re-uses calculate_ema / calculate_rsi / calculate_atr from logic.py when called
from main.py, which passes pre-computed indicator values as arguments.
"""

from __future__ import annotations

from typing import Optional


# ── Private indicator helpers (used when logic.py values not pre-computed) ────

def _ema(values: list[float], period: int) -> Optional[float]:
    """Exponential Moving Average — returns the current (last) EMA value."""
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _volume_ratio(volumes: list[float], period: int = 20) -> Optional[float]:
    """Ratio of latest volume to the simple moving average over `period` bars."""
    if len(volumes) < period + 1:
        return None
    avg = sum(volumes[-period - 1:-1]) / period
    if avg <= 0:
        return None
    return volumes[-1] / avg


# ── Signal result builder (plain dict for JSON-serializability) ───────────────

def _make_signal(
    direction: str,          # "long", "short", or "none"
    reason: str,
    rsi_1h: Optional[float] = None,
    ema_fast_4h: Optional[float] = None,
    ema_slow_4h: Optional[float] = None,
    price_4h: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    vpin: Optional[float] = None,
    atr: Optional[float] = None,
) -> dict:
    return {
        "direction": direction,
        "reason": reason,
        "rsi_1h": round(rsi_1h, 2) if rsi_1h is not None else None,
        "ema_fast_4h": round(ema_fast_4h, 4) if ema_fast_4h is not None else None,
        "ema_slow_4h": round(ema_slow_4h, 4) if ema_slow_4h is not None else None,
        "price_4h": round(price_4h, 4) if price_4h is not None else None,
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "vpin": round(vpin, 3) if vpin is not None else None,
        "atr": round(atr, 4) if atr is not None else None,
    }


# ── Core entry signal ─────────────────────────────────────────────────────────

def calculate_apex_momentum_signal(
    symbol: str,
    closes_1h: list[float],
    volumes_1h: list[float],
    closes_4h: list[float],
    rsi_1h: float,
    prev_rsi_1h: Optional[float],
    atr_1h: float,
    vpin: float,
    rsi_oversold: float,
    rsi_overbought: float,
    ema_fast_period: int,
    ema_slow_period: int,
    volume_mult: float,
    vpin_block: float,
) -> dict:
    """
    Returns a signal dict with direction="long"/"short"/"none" plus diagnostics.

    Parameters
    ----------
    closes_1h    : list of 1h closes (most recent last)
    volumes_1h   : list of 1h volumes (most recent last)
    closes_4h    : list of 4h closes (most recent last)
    rsi_1h       : RSI(14) computed from closes_1h
    prev_rsi_1h  : RSI(14) from the prior 1h bar (for crossover detection)
    atr_1h       : ATR(14) computed from 1h bars
    vpin         : VPIN value (0–1)
    """

    # ── 4h trend filter ───────────────────────────────────────────────────────
    ema_fast = _ema(closes_4h, ema_fast_period)
    ema_slow = _ema(closes_4h, ema_slow_period)
    if ema_fast is None or ema_slow is None or not closes_4h:
        return _make_signal("none", "insufficient_4h_data",
                            rsi_1h=rsi_1h, vpin=vpin, atr=atr_1h)
    price_4h = closes_4h[-1]

    # ── Volume surge check ────────────────────────────────────────────────────
    vol_ratio = _volume_ratio(volumes_1h, period=20)
    if vol_ratio is None:
        return _make_signal(
            "none", "insufficient_volume_data",
            rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
            price_4h=price_4h, vpin=vpin, atr=atr_1h,
        )
    if vol_ratio < volume_mult:
        return _make_signal(
            "none", f"volume_insufficient ({vol_ratio:.2f}x < {volume_mult}x required)",
            rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
            price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
        )

    # ── VPIN toxic-flow block ─────────────────────────────────────────────────
    if vpin > vpin_block:
        return _make_signal(
            "none", f"vpin_block ({vpin:.3f} > {vpin_block})",
            rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
            price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
        )

    # ── RSI crossover detection ───────────────────────────────────────────────
    # Require a confirmed crossover (prev was on the other side of threshold).
    # If prev_rsi is unavailable, use a relaxed "is below/above threshold" gate.
    if prev_rsi_1h is not None:
        rsi_crossed_up   = prev_rsi_1h < rsi_oversold  <= rsi_1h
        rsi_crossed_down = prev_rsi_1h > rsi_overbought >= rsi_1h
    else:
        rsi_crossed_up   = rsi_1h <= rsi_oversold
        rsi_crossed_down = rsi_1h >= rsi_overbought

    # ── LONG entry ────────────────────────────────────────────────────────────
    if rsi_crossed_up:
        uptrend = price_4h > ema_fast > ema_slow
        if not uptrend:
            return _make_signal(
                "none",
                f"rsi_crossover_up_but_4h_downtrend "
                f"(price={price_4h:.4f} ema20={ema_fast:.4f} ema50={ema_slow:.4f})",
                rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
                price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
            )
        return _make_signal(
            "long",
            f"rsi_crossover_up ({rsi_1h:.1f} crossed {rsi_oversold}) "
            f"+ 4h_uptrend + vol={vol_ratio:.2f}x",
            rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
            price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
        )

    # ── SHORT entry ───────────────────────────────────────────────────────────
    if rsi_crossed_down:
        downtrend = price_4h < ema_fast < ema_slow
        if not downtrend:
            return _make_signal(
                "none",
                f"rsi_crossover_down_but_4h_uptrend "
                f"(price={price_4h:.4f} ema20={ema_fast:.4f} ema50={ema_slow:.4f})",
                rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
                price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
            )
        return _make_signal(
            "short",
            f"rsi_crossover_down ({rsi_1h:.1f} crossed {rsi_overbought}) "
            f"+ 4h_downtrend + vol={vol_ratio:.2f}x",
            rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
            price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
        )

    return _make_signal(
        "none", "no_rsi_crossover",
        rsi_1h=rsi_1h, ema_fast_4h=ema_fast, ema_slow_4h=ema_slow,
        price_4h=price_4h, volume_ratio=vol_ratio, vpin=vpin, atr=atr_1h,
    )


# Backward-compatible alias
evaluate_momentum_entry = calculate_apex_momentum_signal


# ── ATR-based exit evaluator (fixed TP/SL + trailing stop) ───────────────────

def evaluate_momentum_exit(
    side: str,
    entry_price: float,
    current_price: float,
    atr: float,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
    trail_atr_mult: float = 1.5,
    best_price: Optional[float] = None,
) -> Optional[str]:
    """
    Returns an exit reason string if the position should close, else None.

    Exit triggers (checked in priority order):
      "apex_tp"          — price reached fixed take-profit (entry ± tp_atr_mult × ATR)
      "apex_sl"          — price hit fixed stop-loss (entry ± sl_atr_mult × ATR)
      "apex_trail_stop"  — trailing stop triggered (activates after price moves
                           +trail_atr_mult × ATR in profit direction; trails at
                           trail_atr_mult × ATR from the best price seen)

    Parameters
    ----------
    best_price  : highest (long) or lowest (short) price seen since entry.
                  Caller is responsible for updating this each cycle and
                  persisting it in _apex_trail_prices[symbol].  If None, only
                  fixed TP/SL checks are performed.
    """
    if atr <= 0 or entry_price <= 0:
        return None

    sl_dist    = sl_atr_mult  * atr
    tp_dist    = tp_atr_mult  * atr
    trail_dist = trail_atr_mult * atr

    if side == "long":
        # Fixed take-profit
        if current_price >= entry_price + tp_dist:
            return "apex_tp"
        # Fixed stop-loss
        if current_price <= entry_price - sl_dist:
            return "apex_sl"
        # Trailing stop — activates only after +1.5 ATR profit
        if best_price is not None and best_price >= entry_price + trail_dist:
            trail_stop = best_price - trail_dist
            if current_price <= trail_stop:
                return "apex_trail_stop"

    elif side == "short":
        # Fixed take-profit
        if current_price <= entry_price - tp_dist:
            return "apex_tp"
        # Fixed stop-loss
        if current_price >= entry_price + sl_dist:
            return "apex_sl"
        # Trailing stop — activates only after +1.5 ATR profit (price dropped)
        if best_price is not None and best_price <= entry_price - trail_dist:
            trail_stop = best_price + trail_dist
            if current_price >= trail_stop:
                return "apex_trail_stop"

    return None
