from __future__ import annotations

from logic import (
    calculate_rsi,
    calculate_atr,
    calculate_ema,
    calculate_rvol,
)


def evaluate_momentum_breakout(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    current_price: float,
    lookback_candles: int = 4,
    atr_threshold: float = 1.5,
    volume_ma_period: int = 20,
    rsi_period: int = 14,
) -> dict:
    atr = calculate_atr(highs, lows, closes)
    rsi = calculate_rsi(closes, period=rsi_period)
    rvol = calculate_rvol(volumes, period=volume_ma_period)

    result = {
        "strategy": "momentum_breakout",
        "signal": None,
        "side": None,
        "conviction": 0.0,
        "rsi": rsi,
        "atr": atr,
        "rvol": rvol,
        "price": current_price,
        "momentum_move": 0.0,
        "atr_threshold_usd": 0.0,
    }

    if atr <= 0 or len(closes) < lookback_candles + 2:
        return result

    momentum_start = closes[-(lookback_candles + 1)]
    momentum_move = current_price - momentum_start
    atr_threshold_usd = atr * atr_threshold

    result["momentum_move"] = momentum_move
    result["atr_threshold_usd"] = atr_threshold_usd

    vol_avg = sum(volumes[-volume_ma_period:]) / max(len(volumes[-volume_ma_period:]), 1)
    latest_vol = volumes[-1] if volumes else 0
    volume_confirmed = latest_vol > vol_avg and vol_avg > 0

    bullish_momentum = momentum_move > atr_threshold_usd
    bearish_momentum = momentum_move < -atr_threshold_usd

    long_rsi_ok = 50 <= rsi <= 70
    short_rsi_ok = 30 <= rsi <= 50

    if bullish_momentum and long_rsi_ok and volume_confirmed:
        conviction = 0.65
        if momentum_move > atr_threshold_usd * 1.5:
            conviction += 0.10
        if rvol >= 1.5:
            conviction += 0.10
        if 55 <= rsi <= 65:
            conviction += 0.05
        conviction = min(conviction, 1.0)

        result["signal"] = "long"
        result["side"] = "long"
        result["conviction"] = round(conviction, 2)

    elif bearish_momentum and short_rsi_ok and volume_confirmed:
        conviction = 0.65
        if abs(momentum_move) > atr_threshold_usd * 1.5:
            conviction += 0.10
        if rvol >= 1.5:
            conviction += 0.10
        if 35 <= rsi <= 45:
            conviction += 0.05
        conviction = min(conviction, 1.0)

        result["signal"] = "short"
        result["side"] = "short"
        result["conviction"] = round(conviction, 2)

    return result


def evaluate_trend_following(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    current_price: float,
    ema_fast_period: int = 30,
    ema_slow_period: int = 75,
    pullback_atr_mult: float = 0.5,
    volume_ma_period: int = 20,
    rsi_period: int = 14,
) -> dict:
    atr = calculate_atr(highs, lows, closes)
    rsi = calculate_rsi(closes, period=rsi_period)

    result = {
        "strategy": "trend_following",
        "signal": None,
        "side": None,
        "conviction": 0.0,
        "rsi": rsi,
        "atr": atr,
        "price": current_price,
        "ema_fast": 0.0,
        "ema_slow": 0.0,
        "pullback_dist": 0.0,
    }

    if atr <= 0 or len(closes) < ema_slow_period + 5:
        return result

    ema_fast_vals = calculate_ema(closes, ema_fast_period)
    ema_slow_vals = calculate_ema(closes, ema_slow_period)

    if not ema_fast_vals or not ema_slow_vals:
        return result

    ema_f = ema_fast_vals[-1]
    ema_s = ema_slow_vals[-1]
    result["ema_fast"] = ema_f
    result["ema_slow"] = ema_s

    uptrend = ema_f > ema_s
    downtrend = ema_f < ema_s

    pullback_zone = atr * pullback_atr_mult
    dist_to_ema = current_price - ema_f
    result["pullback_dist"] = dist_to_ema

    rsi_ok = 40 <= rsi <= 60

    vol_avg = sum(volumes[-volume_ma_period:]) / max(len(volumes[-volume_ma_period:]), 1)
    latest_vol = volumes[-1] if volumes else 0

    if uptrend and rsi_ok:
        pulled_back_to_ema = -pullback_zone <= dist_to_ema <= pullback_zone
        if pulled_back_to_ema:
            conviction = 0.65

            ema_spread_pct = (ema_f - ema_s) / ema_s if ema_s > 0 else 0
            if ema_spread_pct > 0.005:
                conviction += 0.10
            if ema_spread_pct > 0.01:
                conviction += 0.05

            if latest_vol > vol_avg:
                conviction += 0.05

            if 45 <= rsi <= 55:
                conviction += 0.05

            prev_ema_f = ema_fast_vals[-2] if len(ema_fast_vals) >= 2 else ema_f
            if ema_f > prev_ema_f:
                conviction += 0.05

            conviction = min(conviction, 1.0)
            result["signal"] = "long"
            result["side"] = "long"
            result["conviction"] = round(conviction, 2)

    elif downtrend and rsi_ok:
        pulled_back_to_ema = -pullback_zone <= dist_to_ema <= pullback_zone
        if pulled_back_to_ema:
            conviction = 0.65

            ema_spread_pct = (ema_s - ema_f) / ema_s if ema_s > 0 else 0
            if ema_spread_pct > 0.005:
                conviction += 0.10
            if ema_spread_pct > 0.01:
                conviction += 0.05

            if latest_vol > vol_avg:
                conviction += 0.05

            if 45 <= rsi <= 55:
                conviction += 0.05

            prev_ema_f = ema_fast_vals[-2] if len(ema_fast_vals) >= 2 else ema_f
            if ema_f < prev_ema_f:
                conviction += 0.05

            conviction = min(conviction, 1.0)
            result["signal"] = "short"
            result["side"] = "short"
            result["conviction"] = round(conviction, 2)

    return result
