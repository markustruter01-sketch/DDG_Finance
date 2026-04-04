from __future__ import annotations

from typing import Optional

from logic import (
    calculate_ema_ribbon,
    calculate_rvol,
    calculate_keltner_channels,
    calculate_vwap,
    calculate_rsi,
    calculate_atr,
    calculate_ema,
)


def evaluate_momentum_wave(
    candles: list,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    current_price: float,
    ema_fast: int = 8,
    ema_mid: int = 13,
    ema_slow: int = 21,
    rvol_threshold: float = 1.5,
    rvol_period: int = 20,
    rsi_period: int = 14,
) -> dict:
    ribbon = calculate_ema_ribbon(closes, fast=ema_fast, mid=ema_mid, slow=ema_slow)
    rvol = calculate_rvol(volumes, period=rvol_period)
    rsi = calculate_rsi(closes, period=rsi_period)
    atr = calculate_atr(highs, lows, closes)

    result = {
        "strategy": "momentum_wave",
        "signal": None,
        "side": None,
        "conviction": 0.0,
        "ribbon": ribbon,
        "rvol": rvol,
        "rsi": rsi,
        "atr": atr,
        "price": current_price,
    }

    volume_confirmed = rvol >= rvol_threshold
    strong_volume = rvol >= rvol_threshold * 1.5

    if ribbon["signal"] == "bullish_cross" and volume_confirmed:
        conviction = 0.7
        if strong_volume:
            conviction += 0.1
        if rsi < 55:
            conviction += 0.1
        if ribbon["spread"] > 0.001:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "long"
        result["side"] = "long"
        result["conviction"] = round(conviction, 2)

    elif ribbon["signal"] == "bullish" and volume_confirmed and ribbon["spread"] > 0.0003:
        conviction = 0.55
        if rsi < 50:
            conviction += 0.1
        if ribbon["spread"] > 0.001:
            conviction += 0.1
        if strong_volume:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "long"
        result["side"] = "long"
        result["conviction"] = round(conviction, 2)

    elif ribbon["signal"] == "bearish_cross" and volume_confirmed:
        conviction = 0.7
        if strong_volume:
            conviction += 0.1
        if rsi > 45:
            conviction += 0.1
        if ribbon["spread"] > 0.001:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "short"
        result["side"] = "short"
        result["conviction"] = round(conviction, 2)

    elif ribbon["signal"] == "bearish" and volume_confirmed and ribbon["spread"] > 0.0003:
        conviction = 0.55
        if rsi > 50:
            conviction += 0.1
        if ribbon["spread"] > 0.001:
            conviction += 0.1
        if strong_volume:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "short"
        result["side"] = "short"
        result["conviction"] = round(conviction, 2)

    elif ribbon["aligned_bearish"] and ribbon["spread"] > 0.0002:
        conviction = 0.50
        if rsi > 55:
            conviction += 0.1
        if ribbon["spread"] > 0.001:
            conviction += 0.1
        if volume_confirmed:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "short"
        result["side"] = "short"
        result["conviction"] = round(conviction, 2)

    elif ribbon["aligned_bullish"] and ribbon["spread"] > 0.0002:
        conviction = 0.50
        if rsi < 45:
            conviction += 0.1
        if ribbon["spread"] > 0.001:
            conviction += 0.1
        if volume_confirmed:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "long"
        result["side"] = "long"
        result["conviction"] = round(conviction, 2)

    else:
        ema_fast_vals = calculate_ema(closes, ema_fast)
        ema_slow_vals = calculate_ema(closes, ema_slow)
        if ema_fast_vals and ema_slow_vals and len(ema_fast_vals) >= 1 and len(ema_slow_vals) >= 1:
            f_val = ema_fast_vals[-1]
            s_val = ema_slow_vals[-1]
            if s_val > 0:
                gap_pct = (f_val - s_val) / s_val

                if gap_pct < -0.0005 and rsi > 50:
                    conviction = 0.50
                    if rsi > 60:
                        conviction += 0.1
                    if gap_pct < -0.001:
                        conviction += 0.1
                    if volume_confirmed:
                        conviction += 0.1
                    conviction = min(conviction, 1.0)
                    result["signal"] = "short"
                    result["side"] = "short"
                    result["conviction"] = round(conviction, 2)

                elif gap_pct > 0.0005 and rsi < 50:
                    conviction = 0.50
                    if rsi < 40:
                        conviction += 0.1
                    if gap_pct > 0.001:
                        conviction += 0.1
                    if volume_confirmed:
                        conviction += 0.1
                    conviction = min(conviction, 1.0)
                    result["signal"] = "long"
                    result["side"] = "long"
                    result["conviction"] = round(conviction, 2)

    return result


def evaluate_liquidity_scout(
    candles: list,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    current_price: float,
    keltner_ema_period: int = 20,
    keltner_atr_mult: float = 1.5,
    vwap_proximity_pct: float = 0.002,
    rsi_period: int = 14,
) -> dict:
    keltner = calculate_keltner_channels(
        highs, lows, closes,
        ema_period=keltner_ema_period,
        atr_mult=keltner_atr_mult,
    )
    vwap = calculate_vwap(candles)
    rsi = calculate_rsi(closes, period=rsi_period)
    atr = calculate_atr(highs, lows, closes)

    result = {
        "strategy": "liquidity_scout",
        "signal": None,
        "side": None,
        "conviction": 0.0,
        "keltner": keltner,
        "vwap": vwap,
        "rsi": rsi,
        "atr": atr,
        "price": current_price,
    }

    if keltner["mid"] <= 0 or vwap <= 0:
        return result

    vwap_dist_pct = abs(current_price - vwap) / vwap
    near_vwap = vwap_dist_pct <= vwap_proximity_pct

    at_lower_band = keltner["position"] <= 0.20
    at_upper_band = keltner["position"] >= 0.80

    if at_lower_band and current_price <= vwap:
        conviction = 0.55
        if near_vwap:
            conviction += 0.10
        if vwap_dist_pct <= vwap_proximity_pct * 0.5:
            conviction += 0.05
        if rsi < 35:
            conviction += 0.15
        elif rsi < 45:
            conviction += 0.05
        if keltner["width"] > 0.005:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "long"
        result["side"] = "long"
        result["conviction"] = round(conviction, 2)

    elif at_upper_band and current_price >= vwap:
        conviction = 0.55
        if near_vwap:
            conviction += 0.10
        if vwap_dist_pct <= vwap_proximity_pct * 0.5:
            conviction += 0.05
        if rsi > 65:
            conviction += 0.15
        elif rsi > 55:
            conviction += 0.05
        if keltner["width"] > 0.005:
            conviction += 0.1

        conviction = min(conviction, 1.0)
        result["signal"] = "short"
        result["side"] = "short"
        result["conviction"] = round(conviction, 2)

    return result
