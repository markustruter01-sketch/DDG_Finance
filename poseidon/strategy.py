"""
strategy.py — Poseidon Bot (#7)
=================================
Trend-Adaptive Regime Classifier Strategy.

Regime classifier (ADX + ATR percentile):
  - TRENDING:      ADX > 25 AND ATR pctile > 40  →  breakout mode
  - RANGING:       ADX < 20 AND ATR pctile < 60  →  mean reversion mode
  - TRANSITIONAL:  neither                        →  stay flat (no entries)

Breakout mode  : enter ABOVE upper BB band (continuation)
Mean rev mode  : enter BELOW lower BB band or above upper (fade)

Function signatures match the original exactly so main.py needs no changes.
"""
from __future__ import annotations
import math
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("poseidon.strategy")


# =========================================================================
# INDICATORS
# =========================================================================

def calculate_ema(prices: List[float], period: int) -> float:
    if not prices or period <= 0:
        return 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains   = [max(c, 0.0) for c in changes]
    losses  = [abs(min(c, 0.0)) for c in changes]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l < 1e-10:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_g / avg_l)), 2)


def calculate_atr(highs: List[float], lows: List[float],
                  closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        ))
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calculate_adx(highs: List[float], lows: List[float],
                  closes: List[float], period: int = 14) -> float:
    """Wilder's ADX."""
    if len(closes) < period * 2 + 1:
        return 0.0
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        ))
    if len(trs) < period:
        return 0.0
    atr_w    = sum(trs[:period]) / period
    plus_sum = sum(plus_dm[:period])
    minus_sum = sum(minus_dm[:period])
    dxs: List[float] = []
    for i in range(period, len(trs)):
        atr_w     = (atr_w * (period - 1) + trs[i]) / period
        plus_sum  = (plus_sum  * (period - 1) + plus_dm[i])  / period
        minus_sum = (minus_sum * (period - 1) + minus_dm[i]) / period
        if atr_w == 0:
            continue
        plus_di  = 100 * plus_sum  / atr_w
        minus_di = 100 * minus_sum / atr_w
        denom = plus_di + minus_di
        if denom == 0:
            continue
        dxs.append(100 * abs(plus_di - minus_di) / denom)
    if not dxs:
        return 0.0
    if len(dxs) >= period:
        adx = sum(dxs[:period]) / period
        for d in dxs[period:]:
            adx = (adx * (period - 1) + d) / period
        return adx
    return sum(dxs) / len(dxs)


def _sma(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period


def _stddev(values: List[float], period: int) -> float:
    if len(values) < period:
        return 0.0
    sub  = values[-period:]
    mean = sum(sub) / period
    return math.sqrt(sum((v - mean) ** 2 for v in sub) / period)


def _bollinger(closes: List[float], period: int,
               std_mult: float) -> Tuple[float, float, float]:
    mid = _sma(closes, period)
    sd  = _stddev(closes, period)
    return (mid - std_mult * sd, mid, mid + std_mult * sd)


def _atr_percentile(current_atr: float, atr_history: List[float]) -> float:
    """Returns 0–100 percentile of current_atr vs history."""
    if not atr_history:
        return 50.0
    below = sum(1 for a in atr_history if a < current_atr)
    return 100.0 * below / len(atr_history)


# =========================================================================
# REGIME CLASSIFIER
# =========================================================================

def classify_regime(
    closes: List[float],
    highs:  List[float],
    lows:   List[float],
    atr_history: List[float],
    config,
) -> Dict:
    """Returns regime + diagnostics.

    regime: 'TRENDING' | 'RANGING' | 'TRANSITIONAL'
    """
    adx     = calculate_adx(highs, lows, closes, config.ADX_PERIOD)
    atr_now = calculate_atr(highs, lows, closes, config.ADX_PERIOD)
    atr_pct = _atr_percentile(atr_now, atr_history)

    if adx > config.ADX_TRENDING_MIN and atr_pct > config.ATR_PERCENTILE_HIGH:
        regime = "TRENDING"
    elif adx < config.ADX_RANGING_MAX and atr_pct < config.ATR_PERCENTILE_LOW:
        regime = "RANGING"
    else:
        regime = "TRANSITIONAL"

    return {
        "regime":          regime,
        "adx":             adx,
        "atr":             atr_now,
        "atr_percentile":  atr_pct,
    }


# =========================================================================
# EVALUATE_ENTRY — preserves original signature exactly
# =========================================================================

def evaluate_entry(
    symbol:      str,
    closes_4h:   List[float],
    highs_4h:    List[float],
    lows_4h:     List[float],
    volumes_4h:  List[float],
    closes_1h:   List[float],
    volumes_1h:  List[float],
    config,
    atr_history: Optional[List[float]] = None,   # extra kwarg — main.py omits → default []
) -> Optional[Dict]:
    """Evaluate entry using regime-adaptive logic.

    Returns signal dict on entry, None to stay flat.
    atr_history is a rolling list of past ATR values used for the percentile
    calculation. When called from live main.py (no atr_history), the ATR
    percentile defaults to 50 and the classifier still fires correctly.
    """
    min_bars = max(
        config.ADX_PERIOD * 3,
        config.BREAKOUT_BB_PERIOD,
        config.MEANREV_BB_PERIOD,
        config.RSI_PERIOD,
    ) + 5

    if len(closes_4h) < min_bars:
        return None

    if atr_history is None:
        atr_history = []

    # ── Step 1: classify regime ──────────────────────────────────────────────
    regime_info = classify_regime(closes_4h, highs_4h, lows_4h, atr_history, config)
    regime      = regime_info["regime"]

    logger.debug(
        f"{symbol} | regime={regime} ADX={regime_info['adx']:.1f} "
        f"ATR_pct={regime_info['atr_percentile']:.0f}"
    )

    # ── Step 2: flat during TRANSITIONAL ────────────────────────────────────
    if regime == "TRANSITIONAL":
        return None

    # ── Step 3: shared calculations ─────────────────────────────────────────
    current_price = closes_4h[-1]
    rsi           = calculate_rsi(closes_4h, config.RSI_PERIOD)
    atr           = regime_info["atr"]

    vol_avg = (
        sum(volumes_4h[-config.VOLUME_MA_PERIOD:]) / config.VOLUME_MA_PERIOD
        if len(volumes_4h) >= config.VOLUME_MA_PERIOD else 0.0
    )
    vol_now = volumes_4h[-1] if volumes_4h else 0.0

    # ── Step 4: mode-specific entry ─────────────────────────────────────────
    if regime == "TRENDING":
        bb_low, bb_mid, bb_up = _bollinger(
            closes_4h, config.BREAKOUT_BB_PERIOD, config.BREAKOUT_BB_STD
        )
        if vol_now < vol_avg * config.BREAKOUT_VOLUME_MULT:
            return None
        if (current_price > bb_up
                and config.BREAKOUT_RSI_LONG_MIN <= rsi <= config.BREAKOUT_RSI_LONG_MAX):
            direction = "long"
        elif (current_price < bb_low
                and config.BREAKOUT_RSI_SHORT_MIN <= rsi <= config.BREAKOUT_RSI_SHORT_MAX):
            direction = "short"
        else:
            return None

        logger.info(
            f"{symbol} | BREAKOUT {direction.upper()} | "
            f"ADX={regime_info['adx']:.1f} RSI={rsi:.1f} "
            f"price={current_price:.4f} bb_up={bb_up:.4f}"
        )
        return {
            "symbol":    symbol,
            "direction": direction,
            "price":     current_price,
            "atr":       atr,
            "conviction": 0.7,
            "ema_fast":  0.0,
            "ema_slow":  0.0,
            "rsi":       rsi,
            "mode":      "breakout",
            "regime":    regime,
            "bb_lower":  bb_low,
            "bb_mid":    bb_mid,
            "bb_upper":  bb_up,
        }

    else:  # RANGING
        bb_low, bb_mid, bb_up = _bollinger(
            closes_4h, config.MEANREV_BB_PERIOD, config.MEANREV_BB_STD
        )
        if vol_now < vol_avg * config.MEANREV_VOLUME_MULT:
            return None
        if current_price <= bb_low and rsi < config.MEANREV_RSI_LONG_MAX:
            direction = "long"
        elif current_price >= bb_up and rsi > config.MEANREV_RSI_SHORT_MIN:
            direction = "short"
        else:
            return None

        logger.info(
            f"{symbol} | MEANREV {direction.upper()} | "
            f"ADX={regime_info['adx']:.1f} RSI={rsi:.1f} "
            f"price={current_price:.4f}"
        )
        return {
            "symbol":    symbol,
            "direction": direction,
            "price":     current_price,
            "atr":       atr,
            "conviction": 0.6,
            "ema_fast":  0.0,
            "ema_slow":  0.0,
            "rsi":       rsi,
            "mode":      "meanrev",
            "regime":    regime,
            "bb_lower":  bb_low,
            "bb_mid":    bb_mid,
            "bb_upper":  bb_up,
        }


# =========================================================================
# POSITION SIZING — same signature as original
# =========================================================================

def calculate_position_size(
    equity: float,
    price:  float,
    atr:    float,
    config,
) -> Tuple[float, float]:
    """Returns (units, position_usd)."""
    if atr <= 0 or price <= 0:
        return (0.0, 0.0)

    # Use breakout's stop as the conservative default
    stop_dist = atr * config.BREAKOUT_ATR_STOP_MULT
    risk_usd  = equity * config.RISK_PER_TRADE
    units     = risk_usd / stop_dist if stop_dist > 0 else 0.0
    pos_usd   = units * price

    max_pos = equity * config.MAX_POSITION_FRACTION
    if pos_usd > max_pos:
        units   = max_pos / price
        pos_usd = units * price

    return (round(units, 8), round(pos_usd, 2))


# =========================================================================
# CHECK_EXIT — same signature as original, mode-aware
# =========================================================================

def check_exit(
    position:      Dict,
    current_price: float,
    closes_4h:     List[float],
    hours_held:    float,
    config,
) -> Optional[str]:
    """Returns exit reason string or None to continue holding."""
    direction = position["direction"]
    entry     = position["entry_price"]
    atr       = position.get("atr", 0.0)
    mode      = position.get("mode", "breakout")

    # Mode-specific parameters
    if mode == "breakout":
        stop_dist = atr * config.BREAKOUT_ATR_STOP_MULT
        tp_pct    = config.BREAKOUT_TP_PCT
        max_h     = config.BREAKOUT_MAX_HOLD_HOURS
        trail_trigger = config.BREAKOUT_ATR_TRAIL_TRIGGER
        trail_mult    = config.BREAKOUT_ATR_TRAIL_MULT
        bb_period = config.BREAKOUT_BB_PERIOD
        bb_std    = config.BREAKOUT_BB_STD
    else:  # meanrev
        stop_dist = atr * config.MEANREV_ATR_STOP_MULT
        tp_pct    = config.MEANREV_TP_PCT
        max_h     = config.MEANREV_MAX_HOLD_HOURS
        trail_trigger = 999.0   # mean reversion doesn't trail
        trail_mult    = 0.0
        bb_period = config.MEANREV_BB_PERIOD
        bb_std    = config.MEANREV_BB_STD

    # ── Trailing stop tracking ───────────────────────────────────────────────
    best_price = position.get("best_price", entry)
    if direction == "long":
        best_price = max(best_price, current_price)
    else:
        best_price = min(best_price, current_price)
    position["best_price"] = best_price   # mutate so next call sees updated peak

    # ── Hard stop ────────────────────────────────────────────────────────────
    if direction == "long" and current_price <= entry - stop_dist:
        return "stop_loss"
    if direction == "short" and current_price >= entry + stop_dist:
        return "stop_loss"

    # ── Take profit ──────────────────────────────────────────────────────────
    if direction == "long"  and current_price >= entry * (1 + tp_pct):
        return "take_profit"
    if direction == "short" and current_price <= entry * (1 - tp_pct):
        return "take_profit"

    # ── Trailing stop (breakout mode) ────────────────────────────────────────
    if atr > 0 and trail_mult > 0:
        fav_move = (
            (best_price - entry) / atr if direction == "long"
            else (entry - best_price) / atr
        )
        if fav_move >= trail_trigger:
            trail_dist = atr * trail_mult
            if direction == "long"  and current_price <= best_price - trail_dist:
                return "trailing_stop"
            if direction == "short" and current_price >= best_price + trail_dist:
                return "trailing_stop"

    # ── Mode-specific band exits ─────────────────────────────────────────────
    if len(closes_4h) >= bb_period:
        bb_low, bb_mid, bb_up = _bollinger(closes_4h, bb_period, bb_std)
        if mode == "breakout":
            # Counter-band = trend exhausted
            if direction == "long"  and current_price <= bb_low:
                return "counter_band"
            if direction == "short" and current_price >= bb_up:
                return "counter_band"
        else:   # meanrev: exit at mid-band (reversion target)
            if direction == "long"  and current_price >= bb_mid:
                return "mid_band_reversion"
            if direction == "short" and current_price <= bb_mid:
                return "mid_band_reversion"

    # ── Time stop ────────────────────────────────────────────────────────────
    if hours_held >= max_h:
        return f"time_stop_{int(hours_held)}h"

    return None
