"""
logic.py  —  Kraken Bot Trading Logic & Math
=============================================
This module contains all the pure mathematical functions that power
the bot's decision-making. "Pure" means each function takes inputs,
does the math, and returns a result — no side effects, no API calls,
no file I/O. This makes the logic easy to test and reason about.

The five functions here are:
  1. calculate_rsi()       — Is the asset overbought or oversold?
  2. calculate_zscore()    — How far has price drifted from its mean?
  3. get_position_size()   — How many dollars should we put into this trade?
  4. check_circuit_breaker() — Is the market flash-crashing right now?
  5. check_stops()         — Should we exit an open position?
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timezone
from typing import Literal, Optional


# ══════════════════════════════════════════════════════════════════════════════
# 1. RSI — Relative Strength Index
# ══════════════════════════════════════════════════════════════════════════════

def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """
    Calculate the RSI (Relative Strength Index) for a list of closing prices.

    RSI is a momentum indicator that measures whether an asset is "overbought"
    (price has risen too far, too fast) or "oversold" (price has fallen too far,
    too fast). It outputs a number between 0 and 100:
      • RSI < 35  → Oversold  → Potential BUY signal (for mean reversion)
      • RSI > 65  → Overbought → Potential SHORT signal
      • RSI 35–65 → Neutral, no strong signal

    We use Wilder's smoothing method (the original formula) rather than a
    simple moving average, which is the industry standard for RSI.

    Args:
        closes: A list of closing prices, oldest first. Needs len > period + 1.
        period: The look-back window (default 14 — the standard).

    Returns:
        RSI value between 0.0 and 100.0. Returns 50.0 (neutral) if there is
        not enough data to compute a meaningful result.
    """
    # Safety check — we need at least period + 1 data points
    if len(closes) < period + 1:
        return 50.0  # Return neutral RSI if we don't have enough history

    # Calculate the day-to-day price changes (gains and losses)
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Separate into gains (positive moves) and losses (absolute value of negatives)
    gains  = [max(c, 0.0) for c in changes]
    losses = [abs(min(c, 0.0)) for c in changes]

    # Seed the Wilder smoothing with a simple average over the first 'period' values
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Apply Wilder's exponential smoothing to each subsequent period
    # (each new value = (prev * (period-1) + new_value) / period)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i])  / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    # Avoid division by zero — if there are no losses, RSI is 100 (fully overbought)
    if avg_loss == 0.0:
        return 100.0

    # The RSI formula: RS = avg_gain / avg_loss; RSI = 100 - (100 / (1 + RS))
    rs  = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Z-Score — Mean Reversion Signal
# ══════════════════════════════════════════════════════════════════════════════

def calculate_zscore(closes: list[float], window: int = 20) -> float:
    """
    Calculate how many standard deviations the latest price is away from
    its recent rolling average (z-score).

    This is the core signal of our mean-reversion strategy. The idea is:
    prices tend to drift back to their recent average. When price strays
    too far in one direction, we bet on it snapping back.

      • Z-score < -1.8  → Price is unusually LOW  → Potential LONG (buy the dip)
      • Z-score > +1.8  → Price is unusually HIGH → Potential SHORT (sell the peak)
      • -0.3 < Z < +0.3 → Price has reverted to mean → Close the position

    Args:
        closes: A list of closing prices, oldest first.
        window: How many recent candles to use for the mean and std dev.

    Returns:
        Z-score (can be negative or positive). Returns 0.0 if insufficient data.
    """
    if len(closes) < window + 1:
        return 0.0  # Not enough data — return neutral

    # Take the most recent 'window' prices
    recent = closes[-window:]

    mean   = sum(recent) / len(recent)
    # Standard deviation (how spread out the prices are)
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    std_dev  = math.sqrt(variance)

    # Avoid division by zero — if price hasn't moved at all, z-score is 0
    if std_dev == 0.0:
        return 0.0

    # The latest price (the one we're evaluating)
    latest_price = closes[-1]

    # Z-score: how many standard deviations is the latest price from the mean?
    z = (latest_price - mean) / std_dev
    return round(z, 4)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Position Sizing — How Much to Invest Per Trade
# ══════════════════════════════════════════════════════════════════════════════

def get_position_size(
    total_equity:          float,
    entry_price:           float,
    deployed_usd:          float,
    risk_fraction:         float = 0.01,
    stop_loss_pct:         float = 0.02,
    max_position_fraction: float = 0.30,
    cash_reserve:          float = 0.20,
) -> float:
    """
    Calculate how many USD to allocate to a new trade using a three-constraint
    fixed-fractional risk model. The position size is the SMALLEST of three limits:

      Limit 1 — Risk-based size:
        We risk exactly 'risk_fraction' of our total equity on each trade.
        Formula: (total_equity × risk_fraction) / stop_loss_pct
        Example: ($10,000 × 1%) / 2% = $5,000 position size
        → If this position hits the stop loss, we lose exactly 1% of account.

      Limit 2 — Single-position concentration cap:
        No single position can be more than 'max_position_fraction' of equity.
        Example: 30% of $10,000 = max $3,000 per position.
        → Prevents over-betting on one asset.

      Limit 3 — Deployable cash ceiling:
        We always keep 'cash_reserve' of equity as untouchable buffer.
        Available = total_equity × (1 - cash_reserve) - already deployed
        → Prevents deploying more than we can afford.

    Args:
        total_equity:          Current total account balance in USD.
        entry_price:           The price we're buying/shorting at.
        deployed_usd:          Total USD currently tied up in open positions.
        risk_fraction:         Fraction of equity to risk per trade (default 1%).
        stop_loss_pct:         Our stop-loss distance (default 2%).
        max_position_fraction: Max single-position size as fraction of equity.
        cash_reserve:          Fraction of equity to always keep as cash.

    Returns:
        The position size in USD. Returns 0.0 if no capital is available.
    """
    # Limit 1: Risk-based sizing
    # "How big can this position be if we're only willing to lose 1% of equity?"
    risk_amount   = total_equity * risk_fraction
    size_by_risk  = risk_amount / stop_loss_pct if stop_loss_pct > 0 else 0.0

    # Limit 2: Concentration cap
    # "Never put more than 30% of the account in a single trade"
    size_by_cap   = total_equity * max_position_fraction

    # Limit 3: Available cash (after reserve and already-open positions)
    # "We can only deploy what we actually have available"
    deployable    = (total_equity * (1.0 - cash_reserve)) - deployed_usd
    size_by_cash  = max(deployable, 0.0)  # Can't be negative

    # The final size is the most conservative (smallest) of all three limits
    position_usd  = min(size_by_risk, size_by_cap, size_by_cash)

    # Return 0.0 if the result is negligibly small (not worth trading)
    return round(max(position_usd, 0.0), 2)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Circuit Breaker — Flash Crash Detector
# ══════════════════════════════════════════════════════════════════════════════

def check_circuit_breaker(
    price_history: deque,
    drop_threshold: float = 0.10,
    window_minutes: int   = 5,
) -> bool:
    """
    Detect a flash crash by checking if price has dropped more than
    'drop_threshold' (default 10%) within the last 'window_minutes' minutes.

    A "flash crash" is a sudden, extreme price drop — often caused by
    a whale liquidation, exchange glitch, or panic selling — that can
    make technical indicators produce wildly wrong signals. The circuit
    breaker says: "Something abnormal is happening. Stop trading and wait."

    Args:
        price_history: A collections.deque of (timestamp_utc, price) tuples.
                       We add a new entry every trading cycle.
        drop_threshold: How large a price drop triggers the breaker (default 10%).
        window_minutes: How far back to look for the high-water mark (default 5).

    Returns:
        True  → Circuit breaker TRIGGERED — stop trading immediately.
        False → No crash detected — safe to trade normally.
    """
    if len(price_history) < 2:
        return False  # Not enough history to compare — assume safe

    now_utc = datetime.now(tz=timezone.utc)
    current_price = price_history[-1][1]  # The most recent price

    # Find the highest price seen within the look-back window
    high_price_in_window = None
    for ts, price in price_history:
        # Only look at prices within the last 'window_minutes' minutes
        age_minutes = (now_utc - ts).total_seconds() / 60.0
        if age_minutes <= window_minutes:
            if high_price_in_window is None or price > high_price_in_window:
                high_price_in_window = price

    if high_price_in_window is None or high_price_in_window == 0:
        return False

    # How much has the price dropped from that peak?
    drop_pct = (high_price_in_window - current_price) / high_price_in_window

    # If the drop exceeds our threshold, trigger the circuit breaker
    return drop_pct >= drop_threshold


# ══════════════════════════════════════════════════════════════════════════════
# 5. Stop & Trail Check — Should We Exit This Position?
# ══════════════════════════════════════════════════════════════════════════════

def check_stops(
    side:        Literal["long", "short"],
    entry_price: float,
    current_price: float,
    best_price:  float,
    stop_loss_pct: float = 0.02,
    trail_pct:   float   = 0.05,
) -> Optional[Literal["stop", "trail"]]:
    """
    Decide whether an open position should be closed based on:
      (a) Hard stop loss  — "Cut the loss now, it's 2% against us."
      (b) Trailing profit — "We've made 5%+, trail the stop to lock in gains."

    The function works for both LONG positions (we bought and hope price rises)
    and SHORT positions (we sold and hope price falls).

    Args:
        side:          "long" or "short"
        entry_price:   The price we entered the trade at.
        current_price: The current market price.
        best_price:    The best price seen since we entered (highest for long,
                       lowest for short). The caller updates this each cycle.
        stop_loss_pct: How far against us before we cut the loss (default 2%).
        trail_pct:     How far below the best price we allow before trailing
                       stops us out (default 5%).

    Returns:
        "stop"  → Exit immediately — hard stop loss triggered.
        "trail" → Exit immediately — trailing profit target triggered.
        None    → Hold the position — neither stop is triggered.
    """
    if side == "long":
        # ── LONG position: we want price to GO UP ─────────────────────────────

        # Hard stop loss: exit if price fell more than stop_loss_pct from entry
        # Example: entry=$50,000 stop=2% → exit if price < $49,000
        stop_price = entry_price * (1.0 - stop_loss_pct)
        if current_price <= stop_price:
            return "stop"

        # Trailing take-profit: once we're 5% in profit, the "best price" starts
        # to matter. We exit if price drops trail_pct below that best price.
        # Example: best=$60,000 trail=5% → exit if price < $57,000
        if best_price > entry_price:  # Only trail if we're actually in profit
            trail_stop = best_price * (1.0 - trail_pct)
            if current_price <= trail_stop:
                return "trail"

    elif side == "short":
        # ── SHORT position: we want price to GO DOWN ──────────────────────────

        # Hard stop loss: exit if price rose more than stop_loss_pct above entry
        # Example: entry=$50,000 stop=2% → exit if price > $51,000
        stop_price = entry_price * (1.0 + stop_loss_pct)
        if current_price >= stop_price:
            return "stop"

        # Trailing take-profit: exit if price rises trail_pct above the lowest
        # price seen (best for a short = lowest price touched)
        # Example: best=$40,000 trail=5% → exit if price > $42,000
        if best_price < entry_price:  # Only trail if we're in profit
            trail_stop = best_price * (1.0 + trail_pct)
            if current_price >= trail_stop:
                return "trail"

    # Neither stop triggered — hold the position
    return None
