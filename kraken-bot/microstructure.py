"""
microstructure.py  —  Kraken Microstructure Alpha Signals
==========================================================
Pure-function implementations of three microstructure indicators derived
from standard 1-hour OHLCV candles (no live Level-2 order book required).
All three are parameterised so they can be adjusted via config or tests.

Indicators
----------
1. OFI  — Order-Flow Imbalance
   Approximates the net buying / selling pressure in each bar using
   the close-open midpoint spread and volume.

     OFI_bar = sign(close - open) × volume
     OFI_N   = rolling sum of OFI_bar over the last N bars (default 10)
     normalised OFI ∈ [-1, +1] via dividing by total volume in window

2. VAMP — Volume-Adjusted Momentum Price
   Measures price momentum weighted by volume.  A positive VAMP means
   buying volume is pushing price upward; negative means selling pressure.

     VWAP     = Σ(typical_price × volume) / Σ(volume)  over window N
     VAMP     = (latest_close - VWAP) / VWAP    (fractional deviation)

3. VPIN — Volume-Synchronised Probability of Informed Trading
   A simplified VPIN using OHLCV candles.  Estimates the fraction of
   volume attributable to informed (directional) traders by comparing
   buy-side and sell-side volume proxies in a rolling bucket window.

     buy_vol_bar  = volume × (close - low)  / (high - low)  [if range > 0]
     sell_vol_bar = volume × (high - close) / (high - low)  [if range > 0]
     VPIN = |Σbuy_vol - Σsell_vol| / Σtotal_vol   ∈ [0, 1]

Usage
-----
    from microstructure import compute_ofi, compute_vamp, compute_vpin, MicrostructureSignal

    candles = exchange.fetch_ohlcv("BTC/USD", "1h", limit=50)
    ms = MicrostructureSignal.from_ohlcv(candles)
    entry_allowed = ms.entry_filter(side="long")
    logger.info(f"OFI={ms.ofi:.3f} VAMP={ms.vamp:.4f} VPIN={ms.vpin:.3f}")

Design Notes
------------
- All three functions return float values and never raise on short arrays
  (they return neutral values when there is insufficient data).
- The MicrostructureSignal dataclass bundles all three + provides a
  composite entry_filter() that boosts or blocks entry signals.
- No external dependencies beyond the standard library + math.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ── Thresholds for the entry filter ───────────────────────────────────────────
# OFI: positive means net buying pressure.
OFI_LONG_MIN   =  0.05   # require weakly positive OFI for long entries
OFI_SHORT_MAX  = -0.05   # require weakly negative OFI for short entries

# VAMP: deviation of last close from volume-weighted mean
VAMP_LONG_MIN  = -0.005  # allow longs even with slight negative VAMP (mean-rev)
VAMP_SHORT_MAX =  0.005  # allow shorts even with slight positive VAMP (mean-rev)

# VPIN: high VPIN (> HIGH_THRESH) suggests informed trading — consider blocking
VPIN_HIGH_THRESH  = 0.65  # above this → spread risk, tighten or skip
VPIN_BLOCK_THRESH = 0.80  # above this → skip entry entirely (too toxic)


# ══════════════════════════════════════════════════════════════════════════════
# 1. OFI — Order-Flow Imbalance
# ══════════════════════════════════════════════════════════════════════════════

def compute_ofi(
    candles: list[list],
    window: int = 10,
) -> float:
    """
    Compute normalised Order-Flow Imbalance over the last *window* bars.

    Parameters
    ----------
    candles : list[list]
        OHLCV candles from ccxt — each element is:
        [timestamp_ms, open, high, low, close, volume]
    window : int
        Number of most-recent candles to include (default 10).

    Returns
    -------
    float
        Normalised OFI in [-1, +1].
        +1.0 → all volume is buy-side (strong bullish pressure).
        -1.0 → all volume is sell-side (strong bearish pressure).
        0.0  → neutral (or insufficient data).
    """
    if len(candles) < 2:
        return 0.0

    recent = candles[-window:]
    net_flow  = 0.0
    total_vol = 0.0

    for bar in recent:
        _ts, o, h, l, c, v = bar[0], bar[1], bar[2], bar[3], bar[4], bar[5]
        if v is None or v <= 0:
            continue
        direction = 1.0 if c >= o else -1.0
        net_flow  += direction * v
        total_vol += v

    if total_vol == 0.0:
        return 0.0

    return round(net_flow / total_vol, 6)


# ══════════════════════════════════════════════════════════════════════════════
# 2. VAMP — Volume-Adjusted Momentum Price
# ══════════════════════════════════════════════════════════════════════════════

def compute_vamp(
    candles: list[list],
    window: int = 20,
) -> float:
    """
    Compute Volume-Adjusted Momentum Price — fractional deviation of the
    latest close from the volume-weighted average price (VWAP) over *window*.

    Parameters
    ----------
    candles : list[list]
        OHLCV candles (same format as compute_ofi).
    window : int
        Rolling VWAP window in bars (default 20).

    Returns
    -------
    float
        VAMP value (unbounded, but typically in [-0.05, +0.05] for crypto).
        Positive  → latest close is ABOVE the volume-weighted mean (momentum up).
        Negative  → latest close is BELOW the volume-weighted mean (momentum down).
        0.0       → neutral or insufficient data.
    """
    if len(candles) < 2:
        return 0.0

    recent = candles[-window:]

    vwap_num = 0.0
    vwap_den = 0.0

    for bar in recent:
        _ts, o, h, l, c, v = bar[0], bar[1], bar[2], bar[3], bar[4], bar[5]
        if v is None or v <= 0:
            continue
        typical = (h + l + c) / 3.0
        vwap_num += typical * v
        vwap_den += v

    if vwap_den == 0.0:
        return 0.0

    vwap        = vwap_num / vwap_den
    latest_close = candles[-1][4]

    if vwap == 0.0:
        return 0.0

    return round((latest_close - vwap) / vwap, 8)


# ══════════════════════════════════════════════════════════════════════════════
# 3. VPIN — Volume-Synchronised Probability of Informed Trading
# ══════════════════════════════════════════════════════════════════════════════

def compute_vpin(
    candles: list[list],
    window: int = 20,
) -> float:
    """
    Compute a simplified VPIN (Volume-Synchronised Probability of Informed
    Trading) using OHLCV candles.

    Informed traders are proxied by directional volume imbalance within
    each candle.  High VPIN indicates one side (buy or sell) is dominating —
    a sign of adverse selection risk.

    Parameters
    ----------
    candles : list[list]
        OHLCV candles (same format as compute_ofi).
    window : int
        Number of bars to use for the rolling bucket (default 20).

    Returns
    -------
    float
        VPIN in [0.0, 1.0].
        0.0  → perfectly balanced two-sided flow (low adverse selection).
        1.0  → entirely one-sided flow (high adverse selection / toxic flow).
    """
    if len(candles) < 2:
        return 0.0

    recent = candles[-window:]

    buy_vol  = 0.0
    sell_vol = 0.0
    total    = 0.0

    for bar in recent:
        _ts, o, h, l, c, v = bar[0], bar[1], bar[2], bar[3], bar[4], bar[5]
        if v is None or v <= 0:
            continue

        bar_range = h - l
        if bar_range > 0:
            b = v * (c - l) / bar_range
            s = v * (h - c) / bar_range
        else:
            # Zero-range candle (gap or halted) — split 50/50
            b = v * 0.5
            s = v * 0.5

        buy_vol  += b
        sell_vol += s
        total    += v

    if total == 0.0:
        return 0.0

    imbalance = abs(buy_vol - sell_vol)
    return round(imbalance / total, 6)


# ══════════════════════════════════════════════════════════════════════════════
# MicrostructureSignal — composite dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MicrostructureSignal:
    """
    Bundles the three microstructure metrics for a single symbol / cycle.

    Attributes
    ----------
    symbol : str
    ofi    : float   Normalised OFI ∈ [-1, +1]
    vamp   : float   Fractional VWAP deviation (unbounded)
    vpin   : float   Adverse-selection proxy ∈ [0, 1]
    """

    symbol: str
    ofi:    float
    vamp:   float
    vpin:   float

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_ohlcv(
        cls,
        candles: list[list],
        symbol:  str  = "",
        ofi_window:  int = 10,
        vamp_window: int = 20,
        vpin_window: int = 20,
    ) -> "MicrostructureSignal":
        """
        Compute all three metrics from a raw OHLCV candle list and return
        a MicrostructureSignal instance.
        """
        return cls(
            symbol = symbol,
            ofi    = compute_ofi(candles,  window=ofi_window),
            vamp   = compute_vamp(candles, window=vamp_window),
            vpin   = compute_vpin(candles, window=vpin_window),
        )

    # ── Entry filter ──────────────────────────────────────────────────────────

    def entry_filter(
        self,
        side: str,
        ofi_min_long:  float = OFI_LONG_MIN,
        ofi_max_short: float = OFI_SHORT_MAX,
        vpin_block:    float = VPIN_BLOCK_THRESH,
    ) -> tuple[bool, str]:
        """
        Decide whether a new entry in *side* direction is allowed based on
        the current microstructure readings.

        Parameters
        ----------
        side            : "long" or "short"
        ofi_min_long    : Minimum OFI required for a long entry.
        ofi_max_short   : Maximum (most negative) OFI allowed for a short.
        vpin_block      : VPIN above this level blocks all entries.

        Returns
        -------
        (allowed: bool, reason: str)
            allowed=True  → entry is microstructure-confirmed.
            allowed=False → entry should be skipped / reduced.
        """
        if self.vpin >= vpin_block:
            return False, f"VPIN={self.vpin:.3f} >= block_threshold={vpin_block:.2f} (toxic flow)"

        if side == "long":
            if self.ofi < ofi_min_long:
                return False, (
                    f"OFI={self.ofi:.3f} < min_long={ofi_min_long:.2f} "
                    f"(sell-side pressure — skip long)"
                )
        elif side == "short":
            if self.ofi > ofi_max_short:
                return False, (
                    f"OFI={self.ofi:.3f} > max_short={ofi_max_short:.2f} "
                    f"(buy-side pressure — skip short)"
                )

        return True, "microstructure confirmed"

    def is_elevated_vpin(self, threshold: float = VPIN_HIGH_THRESH) -> bool:
        """Return True if VPIN is above the elevated-risk threshold."""
        return self.vpin >= threshold

    def to_dict(self) -> dict:
        """Serialise for status.json / dashboard."""
        return {
            "symbol": self.symbol,
            "ofi":    round(self.ofi,  4),
            "vamp":   round(self.vamp, 6),
            "vpin":   round(self.vpin, 4),
        }

    def __repr__(self) -> str:
        return (
            f"MicrostructureSignal(symbol={self.symbol!r}, "
            f"OFI={self.ofi:+.3f}, VAMP={self.vamp:+.4f}, VPIN={self.vpin:.3f})"
        )
