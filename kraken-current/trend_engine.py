"""
trend_engine.py — Kraken Current Mean Reversion Strategy
=========================================================
Strategy: BB(20, 2σ) + RSI confirmation + volume filter.
Long  when price touches lower band AND RSI < 30 AND volume >= 1.2x avg.
Short when price touches upper band AND RSI > 70 AND volume >= 1.2x avg.
Exit:  return to middle band, 2*ATR stop loss, 5% take profit, or 48h timeout.

All 8 legacy function signatures preserved for main.py import compatibility.
New export: check_mean_reversion_exit().
"""
from __future__ import annotations
import math
from typing import Dict, List, Tuple, Optional


# ── Legacy compat stubs ────────────────────────────────────────────────────────

def calculate_ema(prices: List[float], period: int) -> float:
    """EMA — kept for backward compat, used internally."""
    if not prices or period <= 0:
        return 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calculate_adx(highs: List[float], lows: List[float],
                  closes: List[float], period: int = 14) -> float:
    """ADX — no longer used by strategy. Returns 0 (legacy compat)."""
    return 0.0


def hurst_exponent(series: List[float], max_lag: int = 20) -> float:
    """Hurst — no longer used. Returns 0.5 (random walk, legacy compat)."""
    return 0.5


def momentum_return(closes: List[float], days: int = 10,
                    candles_per_day: int = 6) -> float:
    """Momentum return — no longer used. Returns 0 (legacy compat)."""
    return 0.0


def calculate_vpin(opens: List[float], closes: List[float],
                   volumes: List[float], window: int = 50) -> float:
    """VPIN — no longer used. Returns 0 (legacy compat)."""
    return 0.0


# ── Core indicators ────────────────────────────────────────────────────────────

def calculate_atr(highs: List[float], lows: List[float],
                  closes: List[float], period: int = 14) -> float:
    """Wilder ATR — used for stop loss sizing."""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _sma(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period


def _stddev(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    sub = values[-period:]
    mean = sum(sub) / period
    var = sum((v - mean) ** 2 for v in sub) / period
    return math.sqrt(var)


def _calculate_rsi(closes: List[float], period: int = 14) -> float:
    """Wilder's RSI."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss < 1e-10:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)


def _bollinger_bands(closes: List[float], period: int,
                     std_mult: float) -> Tuple[float, float, float]:
    """Returns (lower_band, mid_band, upper_band)."""
    mid = _sma(closes, period)
    sd  = _stddev(closes, period)
    return (mid - std_mult * sd, mid, mid + std_mult * sd)


# ── Signal evaluation ──────────────────────────────────────────────────────────

def evaluate_trend_signal(
    closes: List[float],
    highs:  List[float],
    lows:   List[float],
    ema_fast_period: int   = 20,    # unused (legacy compat)
    ema_slow_period: int   = 100,   # unused
    adx_period:      int   = 14,    # unused
    adx_min:         float = 0.0,   # unused
    hurst_min:       float = 0.0,   # unused
    momentum_days:   int   = 10,    # unused
    vpin:            float = 0.0,   # unused
    vpin_block:      float = 999.0, # unused
    # BB Breakout params
    bb_period:        int   = 20,
    bb_std:           float = 2.0,
    rsi_period:       int   = 14,
    rsi_long_min:     float = 50.0,   # long: RSI in momentum zone
    rsi_long_max:     float = 75.0,   # long: not exhausted
    rsi_short_min:    float = 25.0,   # short: bear-momentum zone
    rsi_short_max:    float = 50.0,   # short: not oversold
    volumes:          Optional[List[float]] = None,
    volume_ma_period: int   = 20,
    volume_min_mult:  float = 1.5,
) -> Dict:
    """
    Evaluate BB breakout entry signal.

    Long  when price closes ABOVE upper BB band AND RSI in momentum zone
          (50–75) AND volume >= 1.5x avg.
    Short when price closes BELOW lower BB band AND RSI in bear-momentum
          zone (25–50) AND volume >= 1.5x avg.

    Returns same dict shape as legacy trend signal for main.py compat.
    """
    _empty = {
        "direction": None, "passed": False,
        "block_reason": "insufficient_data",
        "ema_fast": 0.0, "ema_slow": 0.0, "adx": 0.0,
        "hurst": 0.5, "momentum": 0.0, "atr": 0.0,
        "bb_lower": 0.0, "bb_mid": 0.0, "bb_upper": 0.0,
        "rsi": 50.0, "current_price": 0.0, "volume_ok": False,
    }
    min_bars = max(bb_period, rsi_period, volume_ma_period) + 5
    if len(closes) < min_bars:
        return _empty

    current_price = closes[-1]
    bb_low, bb_mid, bb_up = _bollinger_bands(closes, bb_period, bb_std)
    rsi = _calculate_rsi(closes, rsi_period)
    atr = calculate_atr(highs, lows, closes, 14)

    # Volume filter
    vol_ok = True
    vol_avg = 0.0
    if volumes and len(volumes) >= volume_ma_period:
        vol_avg = sum(volumes[-volume_ma_period:]) / volume_ma_period
        vol_ok = vol_avg > 0 and volumes[-1] >= vol_avg * volume_min_mult

    direction    = None
    block_reason = None

    # LONG BREAKOUT: price closes above upper band, RSI in momentum zone
    if current_price > bb_up:
        if rsi_long_min <= rsi <= rsi_long_max:
            if vol_ok:
                direction = "long"
            else:
                block_reason = (
                    f"volume_low (vol={volumes[-1] if volumes else 0:.0f}"
                    f" need>={vol_avg * volume_min_mult:.0f})"
                )
        else:
            block_reason = (
                f"rsi_out_of_long_zone (rsi={rsi:.1f}"
                f" need {rsi_long_min:.0f}-{rsi_long_max:.0f})"
            )
    # SHORT BREAKOUT: price closes below lower band, RSI in bear-momentum zone
    elif current_price < bb_low:
        if rsi_short_min <= rsi <= rsi_short_max:
            if vol_ok:
                direction = "short"
            else:
                block_reason = (
                    f"volume_low (vol={volumes[-1] if volumes else 0:.0f}"
                    f" need>={vol_avg * volume_min_mult:.0f})"
                )
        else:
            block_reason = (
                f"rsi_out_of_short_zone (rsi={rsi:.1f}"
                f" need {rsi_short_min:.0f}-{rsi_short_max:.0f})"
            )
    else:
        block_reason = (
            f"price_within_bands ("
            f"price={current_price:.4f} low={bb_low:.4f} up={bb_up:.4f})"
        )

    return {
        "direction":     direction,
        "passed":        direction is not None,
        "block_reason":  block_reason,
        "ema_fast":      0.0,
        "ema_slow":      0.0,
        "adx":           0.0,
        "hurst":         0.5,
        "momentum":      0.0,
        "atr":           atr,
        "bb_lower":      bb_low,
        "bb_mid":        bb_mid,
        "bb_upper":      bb_up,
        "rsi":           rsi,
        "current_price": current_price,
        "volume_ok":     vol_ok,
    }


# ── Position sizing ────────────────────────────────────────────────────────────

def calculate_position_size(
    equity:               float,
    atr:                  float,
    price:                float,
    adx:                  float,
    risk_per_trade:       float = 0.02,
    atr_multiplier:       float = 2.0,
    max_fraction:         float = 0.20,
    regime_mult:          float = 1.0,
    adx_scale_weak:       float = 1.0,
    adx_scale_strong:     float = 1.0,
    adx_strong_threshold:      float = 35.0,
    adx_very_strong_threshold: float = 50.0,
) -> Dict:
    """
    ATR-based position sizing, capped at max_fraction.
    Mean reversion: no ADX scaling — straight risk-per-trade sizing.
    """
    if atr <= 0 or price <= 0:
        return {"units": 0.0, "position_value": 0.0,
                "stop_distance": 0.0, "trail_immediate": False}

    stop_distance  = atr * atr_multiplier
    risk_usd       = equity * risk_per_trade
    units          = risk_usd / stop_distance if stop_distance > 0 else 0.0
    position_value = units * price

    max_position = equity * max_fraction
    if position_value > max_position:
        units          = max_position / price
        position_value = units * price

    return {
        "units":           round(units, 8),
        "position_value":  round(position_value, 2),
        "stop_distance":   round(stop_distance, 8),
        "trail_immediate": False,
    }


# ── Trailing stop (no-op for mean reversion) ───────────────────────────────────

def update_trailing_stop(
    current_price:            float,
    best_price:               float,
    entry_price:              float,
    stop_distance:            float,
    direction:                str,
    trail_trigger_multiplier: float = 1.0,
    atr:                      float = 0.0,
    trail_immediate:          bool  = False,
    trail_atr_mult:           float = 1.5,
) -> Dict:
    """Trail the stop once price moves favorably by trail_trigger_multiplier * ATR.

    Breakout strategy: trail winners by trail_atr_mult * ATR from peak.
    Before trigger: hold hard stop at entry ± stop_distance.
    """
    if not best_price:
        best_price = entry_price

    # Track best price
    if direction == "long":
        best_price     = max(best_price, current_price)
        favorable_move = best_price - entry_price
    else:
        best_price     = min(best_price, current_price)
        favorable_move = entry_price - best_price

    # Activate trailing once favorable move >= trigger * ATR
    trail_active = trail_immediate or (
        atr > 0 and favorable_move >= atr * trail_trigger_multiplier
    )

    if trail_active and atr > 0:
        trail_dist = atr * trail_atr_mult
        if direction == "long":
            stop_level = best_price - trail_dist
        else:
            stop_level = best_price + trail_dist
    else:
        # Hard stop — no trailing yet
        if direction == "long":
            stop_level = entry_price - stop_distance
        else:
            stop_level = entry_price + stop_distance

    return {
        "best_price":      best_price,
        "stop_level":      stop_level,
        "trailing_active": trail_active,
    }


# ── Mean reversion exit check ──────────────────────────────────────────────────

def check_mean_reversion_exit(
    direction:        str,
    entry_price:      float,
    current_price:    float,
    bb_mid:           float,
    bb_lower:         Optional[float] = None,
    bb_upper:         Optional[float] = None,
    atr:              float = 0.0,
    hours_held:       float = 0.0,
    stop_distance:    float = 0.0,
    take_profit_pct:  float = 0.05,
    max_hold_hours:   int   = 48,
    exit_target:      str   = "counter_band",
) -> Tuple[bool, str]:
    """
    Breakout strategy exit logic.
    Returns (should_exit: bool, reason: str).

    Exit conditions (in priority order):
      1. Hard/trailing stop — checked externally via update_trailing_stop;
         stop_distance guard here is a safety fallback only.
      2. Take profit        — price gained >= take_profit_pct from entry.
      3. Counter-band touch — trend exhaustion: long exits at lower band,
                              short exits at upper band.
      4. Time stop          — held >= max_hold_hours.
    """
    if direction == "long":
        # Safety stop fallback (trailing stop is managed in check_exits)
        if stop_distance > 0 and current_price <= entry_price - stop_distance:
            return True, "stop_loss"
        if current_price >= entry_price * (1.0 + take_profit_pct):
            return True, "take_profit"
        # Counter-band: long entered on upper breakout → exit at lower band
        if bb_lower is not None and current_price <= bb_lower:
            return True, "counter_band_reversal"
    else:  # short
        if stop_distance > 0 and current_price >= entry_price + stop_distance:
            return True, "stop_loss"
        if current_price <= entry_price * (1.0 - take_profit_pct):
            return True, "take_profit"
        # Counter-band: short entered on lower breakout → exit at upper band
        if bb_upper is not None and current_price >= bb_upper:
            return True, "counter_band_reversal"

    if hours_held >= max_hold_hours:
        return True, "max_hold_timeout"

    return False, ""
