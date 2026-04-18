"""
trend_engine.py — Kraken Current Trend Following Core Logic
EMA crossover, ADX, ATR-based position sizing, Hurst, trailing stop
"""
from __future__ import annotations

import math
from typing import Optional

from loguru import logger


# ── EMA Calculation ───────────────────────────────────────────────────────────

def calculate_ema(prices: list[float], period: int) -> float:
    """Calculate EMA of a price series. Returns current EMA."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_ema_series(prices: list[float], period: int) -> list[float]:
    """Return full EMA series."""
    if not prices:
        return []
    k = 2.0 / (period + 1)
    if len(prices) < period:
        ema_series = [prices[0]] * len(prices)
    else:
        seed = sum(prices[:period]) / period
        ema_series = [0.0] * period + [seed]
        for price in prices[period:]:
            ema_series.append(price * k + ema_series[-1] * (1 - k))
        ema_series = ema_series[period:]
    return ema_series


# ── ATR Calculation ───────────────────────────────────────────────────────────

def calculate_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """
    Average True Range. Returns ATR value.
    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    if len(highs) < period + 1:
        if len(highs) > 1:
            return (highs[-1] - lows[-1])
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        trs.append(max(hl, hpc, lpc))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    # Use EMA-style smoothing for ATR
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ── ADX Calculation ───────────────────────────────────────────────────────────

def calculate_adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """
    Average Directional Index. Returns ADX value (0-100).
    ADX > 25: strong trend worth following
    ADX < 20: weak trend, stay out
    """
    if len(highs) < period * 2 + 1:
        return 0.0
    try:
        plus_dm = []
        minus_dm = []
        trs = []
        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
            hl = highs[i] - lows[i]
            hpc = abs(highs[i] - closes[i - 1])
            lpc = abs(lows[i] - closes[i - 1])
            trs.append(max(hl, hpc, lpc))

        def smooth(series: list[float], p: int) -> list[float]:
            result = [sum(series[:p])]
            for v in series[p:]:
                result.append(result[-1] - result[-1] / p + v)
            return result

        sm_tr = smooth(trs, period)
        sm_pdm = smooth(plus_dm, period)
        sm_mdm = smooth(minus_dm, period)

        di_plus = [(sm_pdm[i] / sm_tr[i] * 100) if sm_tr[i] > 0 else 0 for i in range(len(sm_tr))]
        di_minus = [(sm_mdm[i] / sm_tr[i] * 100) if sm_tr[i] > 0 else 0 for i in range(len(sm_tr))]

        dx_list = []
        for i in range(len(di_plus)):
            denom = di_plus[i] + di_minus[i]
            if denom > 0:
                dx_list.append(abs(di_plus[i] - di_minus[i]) / denom * 100)
            else:
                dx_list.append(0.0)

        if len(dx_list) < period:
            return 0.0
        adx = sum(dx_list[-period:]) / period
        return min(100.0, max(0.0, adx))
    except Exception:
        return 0.0


# ── Hurst Exponent ────────────────────────────────────────────────────────────

def hurst_exponent(series: list[float], max_lag: int = 20) -> float:
    """H > 0.5 means trending (required for Kraken Current entry)."""
    if len(series) < 20:
        return 0.5
    lags = range(2, min(max_lag, len(series) // 2))
    rs_list = []
    lag_list = []
    for lag in lags:
        sub = series[-(lag * 2):]
        if len(sub) < lag:
            continue
        chunk = sub[:lag]
        if len(chunk) < 2:
            continue
        mean = sum(chunk) / len(chunk)
        deviations = [v - mean for v in chunk]
        cumsum = 0.0
        cumdev = []
        for d in deviations:
            cumsum += d
            cumdev.append(cumsum)
        r = max(cumdev) - min(cumdev) if cumdev else 0.0
        variance = sum(d * d for d in deviations) / len(deviations)
        s = math.sqrt(variance) if variance > 0 else 1e-10
        rs = r / s
        if rs > 0:
            rs_list.append(math.log(rs))
            lag_list.append(math.log(lag))
    if len(lag_list) < 3:
        return 0.5
    n = len(lag_list)
    sum_x = sum(lag_list)
    sum_y = sum(rs_list)
    sum_xx = sum(v * v for v in lag_list)
    sum_xy = sum(xi * yi for xi, yi in zip(lag_list, rs_list))
    denom = n * sum_xx - sum_x ** 2
    if abs(denom) < 1e-12:
        return 0.5
    h = (n * sum_xy - sum_x * sum_y) / denom
    return max(0.0, min(1.0, h))


# ── Momentum ──────────────────────────────────────────────────────────────────

def momentum_return(closes: list[float], days: int = 10, candles_per_day: int = 6) -> float:
    """
    Return of last n days (using 4h candles, 6 per day).
    Positive → bullish, negative → bearish.
    """
    lookback = days * candles_per_day
    if len(closes) < lookback + 1:
        return 0.0
    prev = closes[-(lookback + 1)]
    if prev <= 0:
        return 0.0
    return (closes[-1] - prev) / prev


# ── VPIN (Volume-Synchronised Probability of Informed Trading) ────────────────

def calculate_vpin(
    opens: list[float],
    closes: list[float],
    volumes: list[float],
    window: int = 50,
) -> float:
    """
    Simplified VPIN using bulk volume classification.

    Each bar's volume is classified as buy-initiated (close >= open) or
    sell-initiated (close < open).  VPIN is the absolute order-flow imbalance
    normalised by total volume over the rolling window:

        VPIN = |buy_vol - sell_vol| / total_vol ∈ [0, 1]

    High VPIN (> 0.88) signals toxic/informed order flow — a period when
    informed traders dominate and market-makers widen spreads.  Entering
    trend positions in such conditions often results in adverse fills and
    increased reversal risk.

    Returns 0.0 when insufficient data.
    """
    n = min(len(opens), len(closes), len(volumes))
    if n < 5:
        return 0.0
    start = max(0, n - window)
    buy_vol = 0.0
    total_vol = 0.0
    for i in range(start, n):
        v = volumes[i]
        if v <= 0:
            continue
        total_vol += v
        if closes[i] >= opens[i]:
            buy_vol += v
    if total_vol <= 0:
        return 0.0
    sell_vol = total_vol - buy_vol
    return min(abs(buy_vol - sell_vol) / total_vol, 1.0)


# ── Position Sizing ───────────────────────────────────────────────────────────

def calculate_position_size(
    equity: float,
    atr: float,
    price: float,
    adx: float,
    risk_per_trade: float = 0.02,
    atr_multiplier: float = 2.0,
    max_fraction: float = 0.20,
    regime_mult: float = 1.0,
    adx_scale_weak: float = 0.70,
    adx_scale_strong: float = 1.00,
    adx_strong_threshold: float = 35.0,
    adx_very_strong_threshold: float = 50.0,
) -> dict:
    """
    ATR-based position sizing with ADX scaling.
    Returns units, position_value, stop_distance.
    """
    if atr <= 0 or price <= 0:
        return {"units": 0, "position_value": 0, "stop_distance": 0, "trail_immediate": False}

    risk_amount = equity * risk_per_trade
    atr_risk = atr * atr_multiplier
    raw_units = risk_amount / atr_risk
    raw_value = raw_units * price

    # ADX scaling
    if adx >= adx_very_strong_threshold:
        adx_scale = adx_scale_strong
        trail_immediate = True
    elif adx >= adx_strong_threshold:
        adx_scale = adx_scale_strong
        trail_immediate = False
    else:
        adx_scale = adx_scale_weak
        trail_immediate = False

    scaled_value = raw_value * adx_scale * regime_mult
    max_value = equity * max_fraction
    final_value = min(scaled_value, max_value)
    final_units = final_value / price

    return {
        "units": final_units,
        "position_value": final_value,
        "stop_distance": atr_risk,
        "trail_immediate": trail_immediate,
    }


# ── Signal Evaluation ─────────────────────────────────────────────────────────

def evaluate_trend_signal(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    ema_fast_period: int = 20,
    ema_slow_period: int = 100,
    adx_period: int = 14,
    adx_min: float = 25.0,
    hurst_min: float = 0.5,
    momentum_days: int = 10,
    vpin: float = 0.0,
    vpin_block: float = 0.88,
) -> dict:
    """
    Evaluate all trend entry conditions.
    Returns metrics dict with 'direction': 'long', 'short', or None.
    """
    result = {
        "direction": None,
        "ema_fast": None,
        "ema_slow": None,
        "adx": None,
        "hurst": None,
        "momentum": None,
        "atr": None,
        "passed": False,
        "block_reason": None,
    }
    if len(closes) < ema_slow_period + 5:
        result["block_reason"] = "insufficient_data"
        return result

    ema_fast = calculate_ema(closes, ema_fast_period)
    ema_slow = calculate_ema(closes, ema_slow_period)
    adx = calculate_adx(highs, lows, closes, adx_period)
    h = hurst_exponent(closes)
    mom = momentum_return(closes, momentum_days)
    atr = calculate_atr(highs, lows, closes, 14)

    result.update({
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "adx": adx,
        "hurst": h,
        "momentum": mom,
        "atr": atr,
    })

    # VPIN block
    if vpin >= vpin_block:
        result["block_reason"] = f"vpin_high ({vpin:.3f})"
        return result

    # ADX filter
    if adx < adx_min:
        result["block_reason"] = f"adx_weak ({adx:.1f} < {adx_min})"
        return result

    # Hurst filter
    if h <= hurst_min:
        result["block_reason"] = f"hurst_low ({h:.3f} <= {hurst_min}) — mean-reverting"
        return result

    # Direction from EMA crossover + momentum confirmation
    if ema_fast > ema_slow and mom > 0:
        result["direction"] = "long"
        result["passed"] = True
    elif ema_fast < ema_slow and mom < 0:
        result["direction"] = "short"
        result["passed"] = True
    else:
        result["block_reason"] = "ema_momentum_conflict"

    return result


# ── Trailing Stop ─────────────────────────────────────────────────────────────

def update_trailing_stop(
    current_price: float,
    best_price: float,
    entry_price: float,
    stop_distance: float,
    direction: str,
    trail_trigger_multiplier: float = 1.5,
    atr: float = 0.0,
    trail_immediate: bool = False,
) -> dict:
    """
    Update trailing stop logic.
    Returns new best_price and stop_level.
    """
    if direction == "long":
        new_best = max(best_price, current_price)
        profit_distance = new_best - entry_price
        trail_triggered = trail_immediate or (atr > 0 and profit_distance >= atr * trail_trigger_multiplier)
        if trail_triggered:
            stop_level = new_best - stop_distance
        else:
            stop_level = entry_price - stop_distance
    else:
        new_best = min(best_price, current_price)
        profit_distance = entry_price - new_best
        trail_triggered = trail_immediate or (atr > 0 and profit_distance >= atr * trail_trigger_multiplier)
        if trail_triggered:
            stop_level = new_best + stop_distance
        else:
            stop_level = entry_price + stop_distance

    return {"best_price": new_best, "stop_level": stop_level, "trailing_active": trail_triggered}
