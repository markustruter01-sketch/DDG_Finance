"""
strategy.py — Poseidon Momentum Strategy
=========================================
Dual-Timeframe Momentum with Volume Confirmation.

Entry requires ALL of:
  1. 4H EMA21 > EMA55 (uptrend) or EMA21 < EMA55 (downtrend)
  2. 4H EMA spread > 0.3% (not a flat market)
  3. 1H RSI in pullback zone (38-58 for longs, 42-62 for shorts)
  4. 1H volume > 1.5x 20-period average
  5. Not already holding this symbol

Exit on any of:
  1. Hard stop: price crosses 2.5x ATR from entry
  2. Trailing stop: activates at 2x ATR profit, trails at 2x ATR from best
  3. Time stop: 120 hours max hold
  4. Trend reversal: EMA crosses against position after MIN_HOLD_HOURS
"""
from __future__ import annotations
import math
import logging
from typing import Optional

logger = logging.getLogger("poseidon.strategy")


# ── Indicators ────────────────────────────────────────────────────────────────

def calculate_ema(prices: list[float], period: int) -> float:
    """Exponential Moving Average."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI — consistent with rest of fleet."""
    if len(closes) < period + 1:
        return 50.0
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [max(c, 0.0) for c in changes]
    losses = [abs(min(c, 0.0)) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss < 1e-10:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)


def calculate_atr(highs: list[float], lows: list[float],
                  closes: list[float], period: int = 14) -> float:
    """Wilder's ATR."""
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i]  - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calculate_volume_ma(volumes: list[float], period: int = 20) -> float:
    if len(volumes) < period:
        return sum(volumes) / len(volumes) if volumes else 0.0
    return sum(volumes[-period:]) / period


# ── Signal Evaluation ─────────────────────────────────────────────────────────

def evaluate_entry(
    symbol: str,
    closes_4h: list[float],
    highs_4h:  list[float],
    lows_4h:   list[float],
    volumes_4h: list[float],
    closes_1h: list[float],
    volumes_1h: list[float],
    config,
) -> dict | None:
    """
    Evaluate entry signal for a symbol.
    Returns signal dict if entry conditions met, None otherwise.
    """
    if len(closes_4h) < config.EMA_SLOW + 10:
        return None
    if len(closes_1h) < config.RSI_PERIOD + config.VOLUME_MA_PERIOD + 5:
        return None

    # ── 4H Trend Filter ──────────────────────────────────────────────────────
    ema_fast = calculate_ema(closes_4h, config.EMA_FAST)
    ema_slow = calculate_ema(closes_4h, config.EMA_SLOW)
    ema_spread = abs(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0

    trend_up   = ema_fast > ema_slow
    trend_down = ema_fast < ema_slow

    if ema_spread < config.EMA_MIN_SPREAD_PCT:
        logger.debug(f"{symbol}: EMA spread {ema_spread:.4f} < {config.EMA_MIN_SPREAD_PCT} — flat market, skip")
        return None

    # ── 1H RSI Entry Timing ───────────────────────────────────────────────────
    rsi = calculate_rsi(closes_1h, config.RSI_PERIOD)

    # ── 1H Volume Confirmation ────────────────────────────────────────────────
    vol_ma  = calculate_volume_ma(volumes_1h, config.VOLUME_MA_PERIOD)
    cur_vol = volumes_1h[-1] if volumes_1h else 0
    vol_ok  = vol_ma > 0 and cur_vol >= vol_ma * config.VOLUME_MIN_MULT

    # ── ATR for sizing ────────────────────────────────────────────────────────
    atr = calculate_atr(highs_4h, lows_4h, closes_4h, config.ATR_PERIOD)
    if atr <= 0:
        return None

    current_price = closes_1h[-1]

    # ── Long Signal ───────────────────────────────────────────────────────────
    if (trend_up
            and config.RSI_LONG_MIN <= rsi <= config.RSI_LONG_MAX
            and vol_ok):
        conviction = 0.5
        conviction += 0.15 if ema_spread > 0.008 else 0.05
        conviction += 0.15 if rsi < 50 else 0.05
        conviction += 0.10 if cur_vol > vol_ma * 2.0 else 0
        logger.info(
            f"{symbol}: LONG signal | EMA spread={ema_spread:.3f} "
            f"RSI={rsi:.1f} vol_ratio={cur_vol/vol_ma:.2f}x "
            f"ATR={atr:.4f} conviction={conviction:.2f}"
        )
        return {
            "symbol":     symbol,
            "direction":  "long",
            "price":      current_price,
            "atr":        atr,
            "conviction": round(conviction, 2),
            "ema_fast":   ema_fast,
            "ema_slow":   ema_slow,
            "rsi":        rsi,
        }

    # ── Short Signal ──────────────────────────────────────────────────────────
    if (trend_down
            and config.RSI_SHORT_MIN <= rsi <= config.RSI_SHORT_MAX
            and vol_ok):
        conviction = 0.5
        conviction += 0.15 if ema_spread > 0.008 else 0.05
        conviction += 0.15 if rsi > 50 else 0.05
        conviction += 0.10 if cur_vol > vol_ma * 2.0 else 0
        logger.info(
            f"{symbol}: SHORT signal | EMA spread={ema_spread:.3f} "
            f"RSI={rsi:.1f} vol_ratio={cur_vol/vol_ma:.2f}x "
            f"ATR={atr:.4f} conviction={conviction:.2f}"
        )
        return {
            "symbol":     symbol,
            "direction":  "short",
            "price":      current_price,
            "atr":        atr,
            "conviction": round(conviction, 2),
            "ema_fast":   ema_fast,
            "ema_slow":   ema_slow,
            "rsi":        rsi,
        }

    return None


def calculate_position_size(
    equity: float,
    price:  float,
    atr:    float,
    config,
) -> tuple[float, float]:
    """
    ATR-based position sizing.
    Risk 1.5% of equity on a 2.5x ATR stop.
    Returns (units, position_usd).
    """
    if atr <= 0 or price <= 0:
        return 0.0, 0.0

    risk_usd      = equity * config.RISK_PER_TRADE
    stop_distance = atr * config.ATR_STOP_MULT
    units         = risk_usd / stop_distance
    position_usd  = units * price

    max_usd = equity * config.MAX_POSITION_PCT
    if position_usd > max_usd:
        position_usd = max_usd
        units = position_usd / price

    if position_usd < config.MIN_POSITION_USD:
        return 0.0, 0.0

    return round(units, 6), round(position_usd, 2)


def check_exit(
    position: dict,
    current_price: float,
    closes_4h: list[float],
    hours_held: float,
    config,
) -> str | None:
    """
    Check exit conditions for an open position.
    Returns exit reason string or None if hold.
    """
    direction  = position["direction"]
    entry      = position["entry_price"]
    atr        = position["atr"]
    best_price = position.get("best_price", entry)

    if direction == "long":
        best_price = max(best_price, current_price)
    else:
        best_price = min(best_price, current_price)

    if direction == "long":
        pnl_atr      = (current_price - entry) / atr if atr > 0 else 0
        best_pnl_atr = (best_price - entry) / atr if atr > 0 else 0
    else:
        pnl_atr      = (entry - current_price) / atr if atr > 0 else 0
        best_pnl_atr = (entry - best_price) / atr if atr > 0 else 0

    # ── Hard stop ─────────────────────────────────────────────────────────────
    if pnl_atr <= -config.ATR_STOP_MULT:
        return "hard_stop"

    if hours_held < config.MIN_HOLD_HOURS:
        return None

    # ── Trailing stop ─────────────────────────────────────────────────────────
    if best_pnl_atr >= config.ATR_TRAIL_TRIGGER:
        trail_stop_dist = atr * config.ATR_TRAIL_MULT
        if direction == "long":
            if current_price <= best_price - trail_stop_dist:
                return "trailing_stop"
        else:
            if current_price >= best_price + trail_stop_dist:
                return "trailing_stop"

    # ── Time stop ─────────────────────────────────────────────────────────────
    if hours_held >= config.MAX_HOLD_HOURS:
        return f"time_stop_{int(hours_held)}h"

    # ── Trend reversal exit ───────────────────────────────────────────────────
    if len(closes_4h) >= config.EMA_SLOW + 5:
        ema_fast = calculate_ema(closes_4h, config.EMA_FAST)
        ema_slow = calculate_ema(closes_4h, config.EMA_SLOW)
        if direction == "long" and ema_fast < ema_slow:
            return "trend_reversal"
        if direction == "short" and ema_fast > ema_slow:
            return "trend_reversal"

    return None
