"""
pairs_engine.py — Poseidon Pairs Trading Core Logic
Statistical arbitrage: spread calculation, Z-score, OLS hedge ratio, ADF
Hurst exponent is computed for logging only — NOT used as an entry gate.
ADF is the sole stationarity gate (tests the spread directly).
"""
from __future__ import annotations

import math
import time
from typing import Optional

try:
    import numpy as _np
    _NUMPY_OK = True
except ImportError:
    _NUMPY_OK = False

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

    Two corrections applied vs. the original implementation:
    1. Out-of-sample window: mean and std are computed on spread_series[-(lookback+1):-1]
       (the PRIOR lookback bars), so the current bar is scored against a distribution
       that does NOT include itself.  Including the current bar in its own distribution
       artificially shrinks extreme z-scores (self-referential bias).
    2. Bessel's correction (N-1 denominator) for sample standard deviation.
    """
    n = len(spread_series)
    if n < 6:
        return None
    # Use prior bars only (exclude the current bar from the reference window)
    history = spread_series[-(lookback + 1):-1] if n > lookback else spread_series[:-1]
    if len(history) < 5:
        return None
    mean = sum(history) / len(history)
    # Sample variance with Bessel's correction
    variance = sum((v - mean) ** 2 for v in history) / max(len(history) - 1, 1)
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

def adf_pvalue(series: list[float], max_lags: int = 4) -> float:
    """
    Augmented Dickey-Fuller test with lag selection by AIC.

    Regression: Δy_t = α + β·y_{t-1} + Σ γ_j·Δy_{t-j} + ε  (j = 1..lags)

    The augmented lags whiten the residuals, making the t-statistic for β
    asymptotically valid.  The original implementation used only 1 lag, which
    inflated the t-statistic for autocorrelated spread series and caused false
    signals of stationarity.

    Lag count is selected by AIC (min over 0..max_lags).
    Uses numpy for OLS; falls back to 0-lag OLS if numpy unavailable.

    Returns approximate p-value mapping of MacKinnon critical values
    (with constant, no trend).
    """
    if len(series) < 20:
        return 1.0
    try:
        dy = [series[i] - series[i - 1] for i in range(1, len(series))]
        y_lag = series[:-1]
        n_full = len(dy)

        if _NUMPY_OK:
            best_aic = float("inf")
            best_t = 0.0

            for lags in range(0, min(max_lags + 1, n_full // 5)):
                # Trim to aligned sample: skip first `lags` rows
                n = n_full - lags
                if n < 10:
                    break

                Y = _np.array(dy[lags:], dtype=float)
                # Design: [1, y_lag, Δy_{t-1}, ..., Δy_{t-lags}]
                cols = [_np.ones(n), _np.array(y_lag[lags:], dtype=float)]
                for j in range(1, lags + 1):
                    cols.append(_np.array(dy[lags - j: n_full - j], dtype=float))
                X = _np.column_stack(cols)

                try:
                    B, _, _, _ = _np.linalg.lstsq(X, Y, rcond=None)
                except _np.linalg.LinAlgError:
                    continue

                residuals = Y - X @ B
                sse = float(_np.dot(residuals, residuals))
                k = X.shape[1]
                if sse <= 0 or n <= k:
                    continue

                aic = n * math.log(sse / n) + 2 * k
                if aic < best_aic:
                    best_aic = aic
                    # Var(β) = s² · [(X'X)⁻¹]_{11}
                    s2 = sse / (n - k)
                    try:
                        XtX_inv = _np.linalg.inv(X.T @ X)
                        var_beta = s2 * float(XtX_inv[1, 1])
                    except _np.linalg.LinAlgError:
                        continue
                    if var_beta <= 0:
                        continue
                    best_t = float(B[1]) / math.sqrt(var_beta)

            t_stat = best_t

        else:
            # Pure-Python fallback: 0-lag OLS (original behaviour)
            n = n_full
            sum_x = sum(y_lag)
            sum_y = sum(dy)
            sum_xx = sum(xi * xi for xi in y_lag)
            sum_xy = sum(xi * yi for xi, yi in zip(y_lag, dy))
            denom = n * sum_xx - sum_x ** 2
            if abs(denom) < 1e-12:
                return 1.0
            beta = (n * sum_xy - sum_x * sum_y) / denom
            alpha = (sum_y - beta * sum_x) / n
            residuals = [dy[i] - alpha - beta * y_lag[i] for i in range(n)]
            sse = sum(r * r for r in residuals)
            se_denom = sum((xi - sum_x / n) ** 2 for xi in y_lag)
            if se_denom < 1e-12:
                return 1.0
            se_beta = math.sqrt((sse / max(n - 2, 1)) / se_denom)
            t_stat = beta / se_beta if se_beta > 1e-12 else 0.0

        # MacKinnon (1994) approximate critical values — with constant, no trend
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
    zscore_entry: float = 1.5,
    zscore_lookback: int = 60,
    hurst_max: float = 1.0,   # kept for backward-compat signature but NOT used in filters_ok
    adf_max: float = 0.20,
    hedge_stability: float = 0.25,
) -> dict:
    """
    Evaluate whether a pair is ready to trade.
    Returns a dict with all computed metrics and a 'signal' key.
    signal: 'long_a_short_b', 'short_a_long_b', or None

    Entry gates (in order):
      1. |Z-score| >= zscore_entry (spread divergence)
      2. ADF p-value < adf_max    (spread stationarity — the ONLY stationarity gate)
      3. Hedge ratio within hedge_stability% of 30d avg
    Hurst is computed and returned for observability but does NOT block entry.
    Applying Hurst to the spread is double-filtering: ADF already tests stationarity
    of the spread directly. Hurst on individual asset prices makes sense for
    single-asset mean reversion bots (Kraken, Blackbeard) but not pairs trading.
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

    # All filters — Hurst intentionally excluded (ADF is the sole stationarity gate)
    if zscore is None:
        return result
    filters_ok = (
        abs(zscore) >= zscore_entry
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
