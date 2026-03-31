"""
logic.py  —  Kraken Bot Trading Logic & Math
=============================================
This module contains all the pure mathematical functions that power
the bot's decision-making. "Pure" means each function takes inputs,
does the math, and returns a result — no side effects, no API calls,
no file I/O. This makes the logic easy to test and reason about.

Functions in this module:
  1. calculate_rsi()          — Is the asset overbought or oversold?
  2. calculate_zscore()       — How far has price drifted from its mean?
  3. calculate_atr()          — How volatile is the market RIGHT NOW? (NEW)
  4. get_volatility_tier()    — Which volatility bracket are we in? (NEW)
  5. get_atr_stop_price()     — ATR-calibrated absolute stop price (NEW)
  6. get_position_size()      — How much to invest? (UPGRADED with ATR sizing)
  7. build_tranche_orders()   — Split entry into 3 scaling tranches (NEW)
  8. check_circuit_breaker()  — Is the market flash-crashing right now?
  9. check_stops()            — Should we exit? (UPGRADED with ATR stop)

──────────────────────────────────────────────────────────────────────
  HOW THE NEW MATH PREVENTS BLOWING UP THE ACCOUNT
  ─────────────────────────────────────────────────
  The original system had a fixed 2% stop-loss for every trade.  That
  sounds safe, but in a volatile crypto market it is actually DANGEROUS:

  Problem 1 — "Whipsaw stops" in high volatility:
    BTC's normal hourly candle range might be 1.2%.  Our 2% stop is
    very close, so random noise stops us out constantly even when our
    thesis is correct.  We get chopped to pieces paying fees each time.

  Problem 2 — Silent risk creep in high volatility:
    We buy $10,000 of BTC with a 2% stop → we risk $200 per trade.
    Fine.  But what if ATR has tripled because the market is panicking?
    The price can swing 6% in an hour.  A 10% position cap means we
    have $10,000 deployed, which can *move* $600 against us in one candle
    even if the stop saves us.  Our apparent "1% account risk" is
    actually much higher in real dollar terms on the path to the stop.

  The ATR-based system fixes both problems:
    • Stop distance grows with actual market noise → far fewer whipsaws.
    • Position size SHRINKS automatically when volatility rises → the
      dollar amount at risk stays capped at roughly 1% of equity
      regardless of whether ATR is $200 or $2,000.
    • Tranche entries average our cost down if price dips further after
      initial entry, reducing the effective entry price.

  The Golden Rule (unchanged):
    Risk-based sizing formula guarantees that if the stop is hit:
      loss = equity × RISK_FRACTION (1%)
    ATR changes WHERE the stop is, not HOW MUCH we risk per trade.
"""

from __future__ import annotations

import math
import os
import sys
from collections import deque
from datetime import datetime, timezone
from typing import Literal, Optional

# ── Shared core library ────────────────────────────────────────────────────────
_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from shared.circuit_breaker import check_circuit_breaker as _shared_check_circuit_breaker


# ══════════════════════════════════════════════════════════════════════════════
# VOLATILITY TIER CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
#
# These define three market-volatility brackets expressed as ATR-as-a-percentage-
# of-price.  We use ATR% (not raw ATR) because the same $200 ATR means very
# different things for a $1,000 coin (20%!) vs. a $50,000 coin (0.4%).
#
#   NORMAL   → ATR < 2% of price   → market is calm
#   HIGH     → ATR 2%–4% of price  → elevated volatility (earnings-like event,
#                                     macro news, funding rate spike)
#   EXTREME  → ATR > 4% of price   → market is in panic / mania mode
#
# In NORMAL conditions the bot runs at full position-size allowance.
# In HIGH conditions the allowance is halved — trades are still taken but
# with half the capital so the dollar-risk stays the same.
# In EXTREME conditions the allowance drops to the minimum — the bot still
# participates but with a very small footprint.
#
# Why these numbers?  On-chain crypto research shows that hourly ATR for
# BTC/ETH averages 0.8%–1.5% in calm regimes and can spike to 4%–8% during
# flash crashes or major news events.  The 2% and 4% thresholds create
# meaningful distinctions between calm, elevated, and panic regimes.

ATR_PERIOD:          int   = 14     # Standard Wilder ATR look-back
ATR_MULTIPLIER:      float = 1.5    # Stop = entry ± (ATR_MULTIPLIER × ATR)

# Volatility tier thresholds (ATR as % of price)
VOL_TIER_HIGH_PCT:    float = 0.02  # 2%  → transition NORMAL → HIGH
VOL_TIER_EXTREME_PCT: float = 0.04  # 4%  → transition HIGH   → EXTREME

# Maximum position fraction per volatility tier.
# These override the caller-supplied max_position_fraction when ATR is provided,
# but can never RAISE the cap — only lower it.  This prevents the bot from
# accidentally taking a larger position than its regime config allows.
VOL_TIER_NORMAL_MAX_FRAC:  float = 1.0   # multiplier (no change in normal)
VOL_TIER_HIGH_MAX_FRAC:    float = 0.50  # halved in high vol
VOL_TIER_EXTREME_MAX_FRAC: float = 0.33  # one-third in extreme vol

# Tranche entry configuration
TRANCHE_COUNT:   int   = 3     # Always three tranches
TRANCHE_STEP_PCT: float = 0.01  # Each tranche 1% deeper (long=lower, short=higher)
TRANCHE_SIZES:   tuple = (0.33, 0.33, 0.34)  # Fractions for T1, T2, T3


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
    if len(closes) < period + 1:
        return 50.0  # Return neutral RSI if we don't have enough history

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(c, 0.0) for c in changes]
    losses = [abs(min(c, 0.0)) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i])  / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0

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
        return 0.0

    recent = closes[-window:]
    mean   = sum(recent) / len(recent)
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    std_dev  = math.sqrt(variance)

    if std_dev == 0.0:
        return 0.0

    latest_price = closes[-1]
    z = (latest_price - mean) / std_dev
    return round(z, 4)


# ══════════════════════════════════════════════════════════════════════════════
# 3. ATR — Average True Range  (NEW)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_atr(
    highs:  list[float],
    lows:   list[float],
    closes: list[float],
    period: int = ATR_PERIOD,
) -> float:
    """
    Calculate the ATR (Average True Range) using Wilder's smoothing method.

    ATR is the single best measure of "how much is this market moving right now?"
    It tells us the average size of each price swing over the last N candles,
    taking into account gaps between candles.

    What is "True Range"?
    ---------------------
    For each candle, the True Range is the LARGEST of these three distances:
      (a) High − Low            → the range within this candle
      (b) |High − Prev Close|  → did we gap UP at the open?
      (c) |Low  − Prev Close|  → did we gap DOWN at the open?

    We use the max because any of these can be the "true" volatility event.
    A big overnight gap followed by a narrow intraday range is still highly
    volatile — the standard High-Low would miss it.

    ATR = Wilder's exponential moving average of True Range over 'period' bars.
    Wilder's smoothing: each new ATR = (prev_ATR × (period−1) + new_TR) / period
    This means recent candles carry more weight than older ones.

    Args:
        highs:  List of candle high prices, oldest first.
        lows:   List of candle low prices, oldest first.
        closes: List of candle close prices, oldest first.
        period: Look-back window (default 14 — Wilder's original standard).

    Returns:
        ATR value in the same units as price (e.g., USD).
        Returns 0.0 if there is not enough data (< period + 1 candles).

    Example:
        If BTC's 14-period ATR is $1,200, it means BTC has been moving
        about $1,200 per candle on average over the last 14 periods.
        Our 1.5× ATR stop would be $1,800 below entry.
    """
    # Need at least period+1 candles: one extra for the first prev_close
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return 0.0

    # Step 1: Calculate True Range for each candle (skipping the very first
    #         since we need a previous close to compare against)
    true_ranges: list[float] = []
    for i in range(1, len(closes)):
        high_low   = highs[i]  - lows[i]
        high_pclose = abs(highs[i]  - closes[i - 1])
        low_pclose  = abs(lows[i]   - closes[i - 1])
        # The True Range is whichever distance is largest
        tr = max(high_low, high_pclose, low_pclose)
        true_ranges.append(tr)

    # Step 2: Need at least 'period' true range values to seed the ATR
    if len(true_ranges) < period:
        return 0.0

    # Step 3: Seed ATR with a simple average of the first 'period' true ranges
    # (This is Wilder's prescribed initialisation — a plain average for the seed)
    atr = sum(true_ranges[:period]) / period

    # Step 4: Apply Wilder's exponential smoothing to all subsequent bars
    # Each new bar slightly updates the ATR, with recent bars weighted more
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period

    return round(atr, 8)  # Return full precision (price units vary widely by asset)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Volatility Tier — Which Bracket Are We In?  (NEW)
# ══════════════════════════════════════════════════════════════════════════════

def get_volatility_tier(
    atr:             float,
    reference_price: float,
) -> tuple[str, float, float]:
    """
    Classify the current volatility regime and return the corresponding
    position-size multiplier and ATR-as-a-percentage-of-price.

    The three tiers work like a speed governor on a car: when the road gets
    icy (high volatility), we automatically slow down (reduce position size)
    so the total dollar-amount-at-risk stays roughly constant.

    Args:
        atr:             The 14-period ATR in price units (from calculate_atr).
        reference_price: The current market price (used to compute ATR%).

    Returns:
        A tuple of (tier_name, size_multiplier, atr_pct) where:
          tier_name      → "normal", "high", or "extreme"
          size_multiplier → how much to scale the max_position_fraction
                            (1.0 = no change, 0.50 = halve it, 0.33 = one-third)
          atr_pct         → ATR expressed as a fraction of price (e.g. 0.025 = 2.5%)

    Example:
        ATR = $1,500, BTC price = $60,000 → ATR% = 2.5% → HIGH tier
        A 10% max position is scaled to 10% × 0.50 = 5% max position.
        At $100,000 equity: max position drops from $10,000 → $5,000.
        If stop is hit (1.5 × ATR = 3.75%), dollar loss = $5,000 × 3.75% = $187.
        Without the size reduction it would have been $10,000 × 3.75% = $375 — 2× more.
    """
    if reference_price <= 0 or atr <= 0:
        # Can't compute a meaningful tier — treat as normal and do not penalise
        return ("normal", VOL_TIER_NORMAL_MAX_FRAC, 0.0)

    # Express ATR as a fraction of the current price (dimensionless ratio)
    atr_pct = atr / reference_price

    if atr_pct < VOL_TIER_HIGH_PCT:
        # NORMAL: market is calm, standard position sizing applies
        return ("normal", VOL_TIER_NORMAL_MAX_FRAC, atr_pct)

    elif atr_pct < VOL_TIER_EXTREME_PCT:
        # HIGH: elevated volatility — halve the allowed position size
        return ("high", VOL_TIER_HIGH_MAX_FRAC, atr_pct)

    else:
        # EXTREME: panic / mania — reduce position to one-third of normal
        return ("extreme", VOL_TIER_EXTREME_MAX_FRAC, atr_pct)


# ══════════════════════════════════════════════════════════════════════════════
# 5. ATR Stop Price — Where Exactly Is the Stop?  (NEW)
# ══════════════════════════════════════════════════════════════════════════════

def get_atr_stop_price(
    side:        Literal["long", "short"],
    entry_price: float,
    atr:         float,
    multiplier:  float = ATR_MULTIPLIER,
) -> float:
    """
    Compute the absolute stop-loss price based on the ATR.

    Instead of "stop 2% below entry" (which ignores actual market conditions),
    we place the stop a fixed number of ATR units away.  This means:
      • In a calm market (small ATR): stop is tight but appropriate.
      • In a wild market (large ATR): stop is wider, giving the trade
        room to breathe through normal noise without getting stopped out.

    The multiplier of 1.5 means: "only stop me out if price moves more than
    1.5 average-candle-ranges against me".  One average candle of normal noise
    would not trigger the stop; it takes a real adverse move.

    Args:
        side:        "long" (we bought, want price to go up) or
                     "short" (we sold, want price to go down).
        entry_price: The price at which we entered the trade.
        atr:         The 14-period ATR value (in price units).
        multiplier:  ATR multiplier — default 1.5 means stop is 1.5 × ATR
                     away from entry.  Higher = wider stop, fewer whipsaws
                     but larger potential loss per hit.

    Returns:
        The absolute stop price (in USD).  Compare current_price against
        this level in check_stops() to decide whether to exit.

    Examples (BTC long, entry=$60,000, ATR=$1,000, multiplier=1.5):
        stop_distance = 1.5 × $1,000 = $1,500
        stop_price    = $60,000 − $1,500 = $58,500
        → We hold the long unless BTC falls below $58,500.

    Examples (BTC short, entry=$60,000, ATR=$1,000, multiplier=1.5):
        stop_price = $60,000 + $1,500 = $61,500
        → We hold the short unless BTC rises above $61,500.
    """
    stop_distance = multiplier * atr

    if side == "long":
        # For a long position we lose money when price falls, so stop is BELOW entry
        return round(entry_price - stop_distance, 8)
    else:
        # For a short position we lose money when price rises, so stop is ABOVE entry
        return round(entry_price + stop_distance, 8)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Position Sizing — How Much to Invest Per Trade  (UPGRADED)
# ══════════════════════════════════════════════════════════════════════════════

def get_position_size(
    total_equity:          float,
    entry_price:           float,
    deployed_usd:          float,
    risk_fraction:         float = 0.01,
    stop_loss_pct:         float = 0.02,
    max_position_fraction: float = 0.30,
    cash_reserve:          float = 0.20,
    # NEW: optional ATR-based volatility adjustment
    atr:                   Optional[float] = None,
    atr_multiplier:        float = ATR_MULTIPLIER,
) -> tuple[float, str, float]:
    """
    Calculate how many USD to allocate to a new trade.

    UPGRADED: when 'atr' is provided the function applies two automatic
    adjustments that keep the account risk constant regardless of volatility:

      Adjustment A — ATR-based stop distance (replaces static stop_loss_pct):
        stop_pct = (atr_multiplier × ATR) / entry_price
        This is the REAL distance to our stop, expressed as a fraction.
        It feeds directly into the risk-based sizing formula so that a wider
        stop (higher ATR) automatically produces a SMALLER position.

      Adjustment B — Volatility-tier cap (layered on top of A):
        In HIGH volatility the max_position_fraction is halved.
        In EXTREME volatility it's cut to one-third.
        This provides a second, independent guardrail — if the ATR-based
        stop is somehow miscalibrated the cap still limits exposure.

    The three-limit architecture (unchanged from original):
      Limit 1 — Risk-based size:  risk_amount / effective_stop_pct
      Limit 2 — Concentration cap: total_equity × adjusted_max_frac
      Limit 3 — Available cash:   deployable cash after reserve + open positions

    The final position size is always the SMALLEST of all three.

    Args:
        total_equity:          Current account balance in USD.
        entry_price:           Price we'll enter the trade at.
        deployed_usd:          USD currently in open positions.
        risk_fraction:         Fraction of equity to risk per trade (default 1%).
        stop_loss_pct:         FALLBACK static stop-loss distance (default 2%).
                               Used when 'atr' is not provided (legacy mode).
        max_position_fraction: Max single-position as fraction of equity.
        cash_reserve:          Fraction of equity always kept as cash.
        atr:                   14-period ATR in price units.  When provided,
                               activates ATR-based stop and vol-tier scaling.
        atr_multiplier:        How many ATRs to set the stop away (default 1.5).

    Returns:
        A tuple: (position_size_usd, vol_tier_name, effective_stop_pct)
          position_size_usd → how many USD to allocate (0.0 if no capital)
          vol_tier_name     → "normal" / "high" / "extreme" / "static"
          effective_stop_pct → the stop distance used (fraction, e.g. 0.025)

    Backward-compatible: if 'atr' is None, behaves exactly like the
    original get_position_size() but returns a tuple instead of a float.
    Callers that only need the size can do:  size, _, _ = get_position_size(...)
    """
    # ── Determine effective stop distance ─────────────────────────────────────
    if atr is not None and atr > 0 and entry_price > 0:
        # ATR MODE: stop distance is derived from actual market volatility
        #
        # stop_pct = (multiplier × ATR) / entry_price
        # Example: ATR=$1,000, entry=$60,000, mult=1.5
        #   stop_pct = (1.5 × 1,000) / 60,000 = 2.5%
        #   A $60k position risks $60k × 2.5% = $1,500 at the stop.
        effective_stop_pct = (atr_multiplier * atr) / entry_price

        # Apply the volatility-tier size multiplier on top
        vol_tier, size_multiplier, atr_pct = get_volatility_tier(atr, entry_price)

        # The adjusted max fraction can only be LOWER than what was passed in,
        # never higher — we only cut, never increase.
        adjusted_max_frac = max_position_fraction * size_multiplier

    else:
        # STATIC MODE (legacy / fallback): use the fixed percentage stop
        effective_stop_pct = stop_loss_pct
        vol_tier           = "static"
        adjusted_max_frac  = max_position_fraction

    # Guard: stop must be positive and non-trivially small
    # (a 0% stop would produce an infinite position size)
    if effective_stop_pct <= 0.001:
        effective_stop_pct = 0.001

    # ── Limit 1: Risk-based sizing ────────────────────────────────────────────
    # "How big can this position be if we only want to lose risk_fraction of
    #  equity when the stop is hit?"
    #
    # risk_amount  = equity × 1%  (the dollar amount we're willing to lose)
    # size_by_risk = risk_amount / stop_pct
    #              = the position size that loses exactly risk_amount at the stop
    #
    # If stop gets WIDER (higher ATR → higher stop_pct), this formula
    # automatically makes size_by_risk SMALLER — perfect risk invariance.
    risk_amount  = total_equity * risk_fraction
    size_by_risk = risk_amount / effective_stop_pct

    # ── Limit 2: Concentration cap ────────────────────────────────────────────
    # "Never put more than adjusted_max_frac of the account in a single trade"
    # In high volatility this cap is automatically reduced (see above).
    size_by_cap = total_equity * adjusted_max_frac

    # ── Limit 3: Available cash ───────────────────────────────────────────────
    # "Only deploy what we actually have after keeping the cash reserve"
    deployable   = (total_equity * (1.0 - cash_reserve)) - deployed_usd
    size_by_cash = max(deployable, 0.0)

    # ── Final size: most conservative of all three limits ─────────────────────
    position_usd = min(size_by_risk, size_by_cap, size_by_cash)
    position_usd = round(max(position_usd, 0.0), 2)

    return (position_usd, vol_tier, round(effective_stop_pct, 6))


# ══════════════════════════════════════════════════════════════════════════════
# 7. Tranche Orders — Scaling Into a Position  (NEW)
# ══════════════════════════════════════════════════════════════════════════════

def build_tranche_orders(
    side:           Literal["long", "short"],
    total_size_usd: float,
    entry_price:    float,
    step_pct:       float = TRANCHE_STEP_PCT,
) -> list[dict]:
    """
    Split a full position into three staggered entry tranches.

    WHAT IS SCALING IN?
    Instead of betting everything at one price level ("all-in at the signal"),
    we divide the total position into three smaller orders that execute at
    progressively better prices IF the market continues to move in our direction.

    WHY DOES THIS HELP?
    When a mean-reversion signal fires, the price has already moved far from
    its average.  Often it moves even FURTHER before bouncing.  By scaling in,
    we get a better average entry price on those deeper dips/peaks.

    For a LONG (buying the dip):
      T1 (33%) → Buy immediately at the signal price          (the early bird)
      T2 (33%) → Buy if price drops another 1% below T1      (getting cheaper)
      T3 (34%) → Buy if price drops another 2% below T1      (maximum dip)
      Average entry = (33% × p) + (33% × p×0.99) + (34% × p×0.98)
                    = ~0.993 × p  (we save ~0.7% vs. all-in at the signal)

    For a SHORT (selling the peak):
      T1 (33%) → Sell immediately at the signal price
      T2 (33%) → Sell if price rises another 1% above T1     (even more overbought)
      T3 (34%) → Sell if price rises another 2% above T1     (extreme overbought)

    HOW THE STOP INTERACTS:
    The ATR stop is calculated from the FIRST tranche entry price and applies
    to the whole position.  If the hard stop fires before T2/T3, we exit only
    T1 — the pending tranches are cancelled.  We lose less than if we had
    gone all-in.

    Args:
        side:           "long" or "short"
        total_size_usd: The total position size in USD (from get_position_size).
        entry_price:    The current price when the signal fires (T1 target price).
        step_pct:       Price step between tranches (default 1%).  At 1%, T2 is
                        1% deeper than T1, T3 is 2% deeper than T1.

    Returns:
        A list of 3 dicts, one per tranche:
        {
          "tranche":      1 / 2 / 3,         # order in the sequence
          "size_usd":     float,              # dollars to deploy at this tranche
          "price_target": float,              # target fill price for this tranche
          "filled":       False,              # True after we actually execute it
          "side":         "long" / "short",
        }

    Example (LONG, $3,000 total, BTC at $60,000, step=1%):
        T1: $990   @ $60,000  (entry — execute immediately)
        T2: $990   @ $59,400  (1% lower — execute if BTC falls here)
        T3: $1,020 @ $58,800  (2% lower — execute if BTC falls here)
        Average cost if all three fill: $59,400  (saves $600 vs all-in)
    """
    tranches: list[dict] = []

    for i, fraction in enumerate(TRANCHE_SIZES):
        # Calculate how deep this tranche's price target is
        # Tranche i=0 → 0% offset (at signal), i=1 → 1%, i=2 → 2%
        depth_pct = i * step_pct

        if side == "long":
            # Longs want to buy LOWER → each tranche is at a lower price
            price_target = entry_price * (1.0 - depth_pct)
        else:
            # Shorts want to sell HIGHER → each tranche is at a higher price
            price_target = entry_price * (1.0 + depth_pct)

        tranches.append({
            "tranche":      i + 1,                          # 1-indexed for readability
            "size_usd":     round(total_size_usd * fraction, 2),
            "price_target": round(price_target, 8),
            "filled":       False,                          # Set to True after execution
            "side":         side,
        })

    return tranches


# ══════════════════════════════════════════════════════════════════════════════
# 8. Circuit Breaker — Flash Crash Detector
# ══════════════════════════════════════════════════════════════════════════════

def check_circuit_breaker(
    price_history: deque,
    drop_threshold: float = 0.10,
    window_minutes: int   = 5,
) -> bool:
    """
    Detect a flash crash by checking if price has dropped more than
    'drop_threshold' (default 10%) within the last 'window_minutes' minutes.

    Delegates to the canonical implementation in shared/circuit_breaker.py.
    This function is kept here so callers in kraken-bot do not need to change
    their import statements.

    Args:
        price_history: A collections.deque of (timestamp_utc, price) tuples.
        drop_threshold: How large a price drop triggers the breaker (default 10%).
        window_minutes: How far back to look for the high-water mark (default 5).

    Returns:
        True  → Circuit breaker TRIGGERED — stop trading immediately.
        False → No crash detected — safe to trade normally.
    """
    return _shared_check_circuit_breaker(
        price_history=price_history,
        drop_threshold=drop_threshold,
        window_minutes=window_minutes,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 9. Stop & Trail Check — Should We Exit This Position?  (UPGRADED)
# ══════════════════════════════════════════════════════════════════════════════

def check_stops(
    side:            Literal["long", "short"],
    entry_price:     float,
    current_price:   float,
    best_price:      float,
    stop_loss_pct:   float = 0.02,
    trail_pct:       float = 0.05,
    # NEW: optional ATR-based absolute stop price (overrides stop_loss_pct)
    atr_stop_price:  Optional[float] = None,
) -> Optional[Literal["stop", "trail"]]:
    """
    Decide whether an open position should be closed based on:
      (a) Hard stop loss  — "Price has moved far enough against us — cut it."
      (b) Trailing profit — "We've banked a good profit; trail it to lock in gains."

    UPGRADED: the 'atr_stop_price' parameter lets the caller supply an ABSOLUTE
    stop-loss price level (computed once at entry using get_atr_stop_price) rather
    than a percentage.  This is the preferred mode when ATR data is available.

    Why an absolute price vs. a percentage?
    ─────────────────────────────────────────
    The percentage stop (e.g. 2%) is relative to entry price and never changes.
    The ATR stop is also set at entry (entry ± 1.5×ATR) but it REFLECTS the
    actual market noise at the time we entered.  Using an absolute price means:
      • No recomputation of ATR every cycle (ATR can fluctuate → confusing)
      • The stop is stable — it does not drift as ATR changes post-entry
      • Identical logic to a real exchange stop order (a fixed price level)

    The TRAILING stop is unchanged — it still tracks 'trail_pct' below/above
    the best price seen.  ATR does not affect the trail because the trail
    is meant to lock in profits dynamically as price runs in our favour.

    Args:
        side:           "long" or "short"
        entry_price:    Price at which we entered.
        current_price:  Current market price.
        best_price:     Best price seen since entry (high for long, low for short).
        stop_loss_pct:  FALLBACK percentage stop.  Used ONLY when atr_stop_price
                        is None.  Default 2%.
        trail_pct:      Trailing distance as fraction of best_price.  Default 5%.
        atr_stop_price: PREFERRED: absolute stop price set at entry via
                        get_atr_stop_price().  When provided, overrides the
                        stop_loss_pct percentage calculation entirely.

    Returns:
        "stop"  → Exit immediately — hard stop loss triggered.
        "trail" → Exit immediately — trailing profit target triggered.
        None    → Hold the position — neither stop is triggered.
    """
    if side == "long":
        # ── LONG position: we bought, want price to rise ───────────────────────

        # Determine the hard stop price level
        if atr_stop_price is not None:
            # PREFERRED: use the pre-computed ATR-based absolute level
            # Example: atr_stop_price = $58,500 set at entry
            stop_price = atr_stop_price
        else:
            # FALLBACK: classic percentage stop below entry
            # Example: entry=$60,000, stop_loss_pct=2% → stop=$58,800
            stop_price = entry_price * (1.0 - stop_loss_pct)

        # Hard stop: exit if current price has dropped to or below the stop level
        if current_price <= stop_price:
            return "stop"

        # Trailing take-profit: we only trail once we're IN profit (best > entry)
        # Exit if price pulls back trail_pct below the highest price seen
        # Example: best=$65,000, trail=5% → trail_stop=$61,750
        #          If price drops to $61,750 → "trail"
        if best_price > entry_price:
            trail_stop = best_price * (1.0 - trail_pct)
            if current_price <= trail_stop:
                return "trail"

    elif side == "short":
        # ── SHORT position: we sold, want price to fall ────────────────────────

        if atr_stop_price is not None:
            stop_price = atr_stop_price
        else:
            stop_price = entry_price * (1.0 + stop_loss_pct)

        # Hard stop: exit if price has risen to or above the stop level
        if current_price >= stop_price:
            return "stop"

        # Trailing take-profit for shorts: best = lowest price seen
        # Exit if price rallies trail_pct above the lowest price seen
        # Example: best=$55,000, trail=5% → trail_stop=$57,750
        if best_price < entry_price:
            trail_stop = best_price * (1.0 + trail_pct)
            if current_price >= trail_stop:
                return "trail"

    return None  # Neither stop triggered — hold
