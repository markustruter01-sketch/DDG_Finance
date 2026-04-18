"""
core/metrics.py — Single source of truth for all performance metric calculations.

Every route, report section, and summary endpoint must import from here.
No ad-hoc win-rate, profit-factor, or risk-ratio logic outside this module.

Functions
---------
win_rate(trades, pnl_field)           → float | None   (percentage, e.g. 55.2)
profit_factor(trades, pnl_field)      → float | None
risk_metrics(returns, ...)            → dict  (Sharpe, Sortino, drawdown, Calmar, vol)
max_drawdown_pct(equity_curve)        → float
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Threshold constants (single place to change platform-wide)
# ---------------------------------------------------------------------------
WIN_THRESHOLD: float = 0.0          # pnl must be strictly ABOVE this to count as a win
RF_ANNUAL: float = 0.05             # 5% annual risk-free rate
PERIODS_DAILY: int = 252            # trading days per year
PERIODS_HOURLY: int = 8_760         # hours per year
MIN_PERIODS_RATIOS: int = 10        # minimum data points before Sharpe/Sortino are reported
MIN_PERIODS_ANNUALISED: int = 30    # minimum data points before annualised return is reported


# ---------------------------------------------------------------------------
# 1. Win Rate
# ---------------------------------------------------------------------------
def win_rate(
    trades: list[dict[str, Any]],
    pnl_field: str = "pnl_usd",
    threshold: float = WIN_THRESHOLD,
) -> float | None:
    """
    Return win rate as a percentage (0–100), or None if there are no trades.

    A trade is a "win" when its PnL is strictly greater than *threshold*
    (default 0 — breakeven trades count as losses, consistent with standard
    quant reporting).

    Args:
        trades:     List of trade dicts (e.g. rows from kraken_trades).
        pnl_field:  Column/key that holds the realised PnL value.
        threshold:  PnL must exceed this value to count as a win.
    """
    if not trades:
        return None
    wins = sum(1 for t in trades if float(t.get(pnl_field) or 0) > threshold)
    return wins / len(trades) * 100.0


def win_rate_from_counts(wins: int, total: int) -> float | None:
    """
    Return win rate as a percentage (0–100) from pre-aggregated win/total counts.

    Use when individual trade rows are not available (e.g. SQL GROUP BY results).
    Returns None when total is zero.
    """
    if total == 0:
        return None
    return round(wins / total * 100.0, 2)


# ---------------------------------------------------------------------------
# 2. Profit Factor
# ---------------------------------------------------------------------------
def profit_factor(
    trades: list[dict[str, Any]],
    pnl_field: str = "pnl_usd",
) -> float | None:
    """
    Return gross-profit / gross-loss, or None when there are no trades or no losses.

    Returns None (not inf) when there are zero losing trades so callers can
    display "N/A" or "∞" without special-casing float infinity.
    """
    if not trades:
        return None
    gross_profit = sum(
        float(t.get(pnl_field) or 0)
        for t in trades
        if float(t.get(pnl_field) or 0) > 0
    )
    gross_loss = abs(sum(
        float(t.get(pnl_field) or 0)
        for t in trades
        if float(t.get(pnl_field) or 0) < 0
    ))
    if gross_loss == 0:
        return None
    return round(gross_profit / gross_loss, 3)


# ---------------------------------------------------------------------------
# 3. Risk Metrics  (Sharpe, Sortino, Max Drawdown, Calmar, Volatility)
# ---------------------------------------------------------------------------
def risk_metrics(
    returns: list[float],
    rf_annual: float = RF_ANNUAL,
    periods_per_year: float = PERIODS_DAILY,
    min_periods_ratios: int = MIN_PERIODS_RATIOS,
    min_periods_annualised: int = MIN_PERIODS_ANNUALISED,
    equity_curve: list[float] | None = None,
) -> dict[str, Any]:
    """
    Compute annualised risk/return metrics from a series of per-period returns.

    Uses unbiased standard deviation (ddof=1) consistently across all callers.
    Sharpe and Sortino are suppressed (→ None) until min_periods_ratios is met.
    Annualised return and Calmar are suppressed until min_periods_annualised is met.

    Args:
        returns:              Per-period return fractions (e.g. 0.01 = +1 %).
        rf_annual:            Annual risk-free rate (default 5 %).
        periods_per_year:     252 for daily, 8760 for hourly, 12 for monthly, etc.
        min_periods_ratios:   Gate for Sharpe/Sortino/vol.
        min_periods_annualised: Gate for annualised return/Calmar.
        equity_curve:         Optional equity curve for a more accurate max drawdown.

    Returns:
        Dict with keys: sharpe_ratio, sortino_ratio, max_drawdown_pct,
        calmar_ratio, volatility_annual_pct, annualised_return_pct,
        data_points, insufficient_data.
    """
    n = len(returns)
    _empty: dict[str, Any] = {
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "max_drawdown_pct": None,
        "calmar_ratio": None,
        "volatility_annual_pct": None,
        "annualised_return_pct": None,
        "data_points": n,
        "insufficient_data": True,
    }
    if n < 2:
        return _empty

    arr = np.array(returns, dtype=float)
    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr, ddof=1))          # unbiased — consistent across all callers
    rf_per_period = rf_annual / periods_per_year

    enough_ratios = n >= min_periods_ratios
    enough_annualised = n >= min_periods_annualised
    sqrt_ppy = math.sqrt(periods_per_year)

    # Sharpe
    sharpe: float | None = (
        float((mean_r - rf_per_period) / std_r * sqrt_ppy)
        if std_r > 0
        else None
    )

    # Sortino (downside std, ddof=1)
    downside = arr[arr < 0]
    downside_std: float | None = (
        float(np.std(downside, ddof=1)) if len(downside) > 1 else None
    )
    sortino: float | None = (
        float((mean_r - rf_per_period) / downside_std * sqrt_ppy)
        if downside_std and downside_std > 0
        else None
    )

    # Max Drawdown — use equity curve if available, else cumulative-product reconstruction
    if equity_curve and len(equity_curve) >= 2:
        peak = equity_curve[0]
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd
    else:
        cum = np.cumprod(1.0 + arr)
        peaks = np.maximum.accumulate(cum)
        raw_dd = (peaks - cum) / np.where(peaks > 0, peaks, 1) * 100.0
        max_dd = float(np.max(raw_dd)) if len(raw_dd) > 0 else 0.0

    ann_return = round(mean_r * periods_per_year * 100.0, 2) if enough_annualised else None
    vol_annual = (
        round(std_r * sqrt_ppy * 100.0, 2) if (enough_ratios and std_r > 0) else None
    )
    calmar = (
        round(ann_return / max_dd, 3)
        if (enough_annualised and ann_return is not None and max_dd > 0)
        else None
    )

    return {
        "sharpe_ratio": round(sharpe, 3) if (enough_ratios and sharpe is not None) else None,
        "sortino_ratio": round(sortino, 3) if (enough_ratios and sortino is not None) else None,
        "max_drawdown_pct": round(max_dd, 2),
        "calmar_ratio": calmar,
        "volatility_annual_pct": vol_annual,
        "annualised_return_pct": ann_return,
        "data_points": n,
        "insufficient_data": not enough_annualised,
    }


# ---------------------------------------------------------------------------
# 4. Max Drawdown (standalone, for equity-curve-only callers)
# ---------------------------------------------------------------------------
def max_drawdown_pct(equity_curve: list[float]) -> float:
    """
    Return the peak-to-trough maximum drawdown as a positive percentage.
    Returns 0.0 if the curve has fewer than 2 points.
    """
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)
