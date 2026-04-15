"""
pairs_engine.py — Poseidon Pairs Trading Core Logic
Statistical arbitrage: spread calculation, Z-score, OLS hedge ratio, Hurst, ADF
"""
from __future__ import annotations

import math
import time
from typing import Optional

from loguru import logger

# ── OLS Regression ────────────────────────────────────────────────────────────

def ols_hedge_ratio(y: list[float], x: list[float]) -> float:
    """
    Ordinary Least Squares regression: y = beta * x + alpha
    Returns beta (hedge ratio).
    y = log prices of asset A, x = log prices of asset B.
    """
    n = len(y)
    if n < 10 or n != len(x):
        return 1.0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xx = sum(xi * xi for xi in x)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    denom = n * sum_xx - sum_x ** 2
    if abs(denom) < 1e-12:
        return 1.0
    beta = (n * sum_xy - sum_x * sum_y) / denom
    return max(0.01, beta)  # hedge ratio must be positive


def calculate_spread(price_a: float, price_b: float, hedge_ratio: float) -> float:
    """
    Spread = log(price_a) - hedge_ratio * log(price_b)
    """
    if price_a <= 0 or price_b <= 0:
        return 0.0
    return math.log(price_a) - hedge_ratio * math.log(price_b)


def calculate_spread_series(prices_a: list[float], prices_b: list[float], hedge_ratio: float) -> list[float]:
    return [
        calculate_spread(pa, pb, hedge_ratio)
        for pa, pb in zip(prices_a, prices_b)
        if pa > 0 and pb > 0
    ]


def calculate_zscore(spread_series: list[float], lookback: int = 60) -> Optional[float]:
    """
    Z-score of the most recent spread against rolling mean/std.
    lookback is in hours (data points).
    """
    if len(spread_series) < lookback:
        window = spread_series
    else:
        window = spread_series[-lookback:]
    if len(window) < 5:
        return None
    mean = sum(window) / len(window)
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    std = math.sqrt(variance)
    if std < 1e-10:
        return 0.0
    return (spread_series[-1] - mean) / std


# ── Hurst Exponent ────────────────────────────────────────────────────────────

def hurst_exponent(series: list[float], max_lag: int = 20) -> float:
    """
    Estimate the Hurst exponent using the R/S method.
    H < 0.5 → mean-reverting
    H = 0.5 → random walk
    H > 0.5 → trending
    """
    if len(series) < 20:
        return 0.5
    lags = range(2, min(max_lag, len(series) // 2))
    rs_list = []
    lag_list = []
    for lag in lags:
        sub = series[-lag * 2:]
        if len(sub) < lag * 2:
            continue
        chunk = sub[:lag]
        if len(chunk) < 2:
            continue
        mean = sum(chunk) / len(chunk)
        deviations = [v - mean for v in chunk]
        cumdev = []
        cumsum = 0.0
        for d in deviations:
            cumsum += d
            cumdev.append(cumsum)
        r = max(cumdev) - min(cumdev)
        variance = sum(d * d for d in deviations) / len(deviations)
        s = math.sqrt(variance) if variance > 0 else 1e-10
        rs = r / s
        if rs > 0:
            rs_list.append(math.log(rs))
            lag_list.append(math.log(lag))
    if len(lag_list) < 3:
        return 0.5
    # Linear regression on log(R/S) vs log(lag)
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


# ── ADF Test (simplified) ─────────────────────────────────────────────────────

def adf_pvalue(series: list[float]) -> float:
    """
    Simplified ADF (Augmented Dickey-Fuller) test.
    Tests the null hypothesis that the series has a unit root (non-stationary).
    Returns approximate p-value. p < 0.10 → stationary → good for pairs trading.

    Uses a simplified OLS regression: Δy_t = α + β*y_{t-1} + ε
    Then estimates the t-statistic for β and maps to approximate p-value.
    """
    if len(series) < 10:
        return 1.0
    try:
        # First differences and lagged levels
        y_lag = series[:-1]
        dy = [series[i] - series[i - 1] for i in range(1, len(series))]
        n = len(dy)
        if n < 5:
            return 1.0
        # OLS: Δy = alpha + beta * y_lag
        sum_x = sum(y_lag)
        sum_y = sum(dy)
        sum_xx = sum(xi * xi for xi in y_lag)
        sum_xy = sum(xi * yi for xi, yi in zip(y_lag, dy))
        denom = n * sum_xx - sum_x ** 2
        if abs(denom) < 1e-12:
            return 1.0
        beta = (n * sum_xy - sum_x * sum_y) / denom
        alpha = (sum_y - beta * sum_x) / n
        # Residuals and standard error
        residuals = [dy[i] - alpha - beta * y_lag[i] for i in range(n)]
        sse = sum(r * r for r in residuals)
        se_beta_sq_denom = sum((xi - sum_x / n) ** 2 for xi in y_lag)
        if se_beta_sq_denom < 1e-12:
            return 1.0
        se_beta = math.sqrt((sse / max(n - 2, 1)) / se_beta_sq_denom)
        if se_beta < 1e-12:
            return 1.0
        t_stat = beta / se_beta
        # Map ADF t-stat to approximate p-value
        # Critical values for ADF (no trend/constant):
        # 1%: -3.43, 5%: -2.86, 10%: -2.57
        if t_stat < -3.43:
            return 0.01
        elif t_stat < -2.86:
            return 0.05
        elif t_stat < -2.57:
            return 0.10
        elif t_stat < -1.95:
            return 0.20
        else:
            return 0.50
    except Exception:
        return 1.0


# ── Hedge Ratio Stability ─────────────────────────────────────────────────────

def is_hedge_ratio_stable(current_hr: float, hr_30d_avg: float, tolerance: float = 0.15) -> bool:
    """
    Check if current hedge ratio is within tolerance% of 30-day average.
    """
    if hr_30d_avg <= 0:
        return True
    deviation = abs(current_hr - hr_30d_avg) / hr_30d_avg
    return deviation <= tolerance


# ── Signal Evaluation ─────────────────────────────────────────────────────────

def evaluate_pair_signal(
    prices_a: list[float],
    prices_b: list[float],
    hedge_ratio: float,
    hr_30d_avg: float,
    zscore_entry: float = 2.0,
    zscore_lookback: int = 60,
    hurst_max: float = 0.5,
    adf_max: float = 0.10,
    hedge_stability: float = 0.15,
) -> dict:
    """
    Evaluate whether a pair is ready to trade.
    Returns a dict with all computed metrics and a 'signal' key.
    signal: 'long_a_short_b', 'short_a_long_b', or None
    """
    result = {
        "signal": None,
        "zscore": None,
        "spread": None,
        "hurst": None,
        "adf_pvalue": None,
        "hedge_ratio_stable": False,
        "passed_all": False,
    }
    if len(prices_a) < 30 or len(prices_b) < 30:
        return result

    # Compute log prices
    log_a = [math.log(p) for p in prices_a if p > 0]
    log_b = [math.log(p) for p in prices_b if p > 0]
    if len(log_a) < 30 or len(log_b) < 30:
        return result

    # Spread series
    n = min(len(log_a), len(log_b))
    spread_series = [log_a[i] - hedge_ratio * log_b[i] for i in range(n)]

    # Z-score
    zscore = calculate_zscore(spread_series, zscore_lookback)
    result["zscore"] = zscore
    result["spread"] = spread_series[-1] if spread_series else None

    # Hurst on spread
    h = hurst_exponent(spread_series)
    result["hurst"] = h

    # ADF on spread
    adf_p = adf_pvalue(spread_series)
    result["adf_pvalue"] = adf_p

    # Hedge ratio stability
    hr_stable = is_hedge_ratio_stable(hedge_ratio, hr_30d_avg, hedge_stability)
    result["hedge_ratio_stable"] = hr_stable

    # All filters
    if zscore is None:
        return result
    filters_ok = (
        abs(zscore) >= zscore_entry
        and h < hurst_max
        and adf_p < adf_max
        and hr_stable
    )
    result["passed_all"] = filters_ok

    if filters_ok:
        if zscore > zscore_entry:
            result["signal"] = "short_a_long_b"
        elif zscore < -zscore_entry:
            result["signal"] = "long_a_short_b"

    return result


# ── Position size calculation ─────────────────────────────────────────────────

def calculate_pair_sizes(equity: float, price_a: float, price_b: float, hedge_ratio: float, position_pct: float = 0.20) -> dict:
    """
    Dollar-neutral pair position sizing.
    Returns units for each leg.
    """
    position_value = equity * position_pct
    leg_a_units = position_value / price_a
    leg_b_units = (position_value * hedge_ratio) / price_b
    return {
        "position_value": position_value,
        "leg_a_units": leg_a_units,
        "leg_b_units": leg_b_units,
        "leg_a_cost": leg_a_units * price_a,
        "leg_b_cost": leg_b_units * price_b,
    }
