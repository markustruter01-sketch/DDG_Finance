"""
microstructure.py  —  Kraken Microstructure Alpha Signals
==========================================================
Primary API: order-book / trade-bucket based (per spec).
Backward-compat API: OHLCV-based variants (suffixed _ohlcv) kept for tests.

Primary (order-book / trade-bucket)
------------------------------------
1. compute_ofi(order_book)        — OFI from ccxt fetch_order_book() snapshot
2. compute_vamp(order_book)       — Volume-Adjusted Mid Price from order book
3. build_trade_buckets(trades, $) — Transform ccxt fetch_trades() into buckets
4. compute_vpin(buckets, $)       — VPIN from fixed-dollar trade buckets

OHLCV backward-compat (suffixed _ohlcv)
-----------------------------------------
compute_ofi_ohlcv, compute_vamp_ohlcv, compute_vpin_ohlcv
All three accept [timestamp, open, high, low, close, volume] candle lists.

MicrostructureSignal dataclass
--------------------------------
  .from_orderbook(order_book, recent_trades)  — primary factory
  .from_ohlcv(candles)                        — backward-compat factory
  .entry_filter(side)                         — composite entry gate
  .is_elevated_vpin()                         — VPIN risk alert
  .to_dict()                                  — JSON serialisation

Usage (primary)
---------------
    ob    = exchange.fetch_order_book("BTC/USD")
    trades= exchange.fetch_trades("BTC/USD", limit=200)
    ms    = MicrostructureSignal.from_orderbook(ob, trades, symbol="BTC/USD")
    allowed, reason = ms.entry_filter(side="long")
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ── Entry-filter thresholds ───────────────────────────────────────────────────
OFI_LONG_MIN   =  0.02
OFI_SHORT_MAX  = -0.02

VAMP_LONG_MIN  = -0.005
VAMP_SHORT_MAX =  0.005

VPIN_HIGH_THRESH  = 0.72
VPIN_BLOCK_THRESH = 0.82

# ── Order-book / trade-bucket defaults ───────────────────────────────────────
_DEFAULT_OB_LEVELS    = 5
_DEFAULT_BUCKET_USD   = 5_000.0
_DEFAULT_VPIN_BUCKETS = 50    # number of most-recent buckets used by compute_vpin


# ══════════════════════════════════════════════════════════════════════════════
# PRIMARY API — order-book & trade-bucket functions
# ══════════════════════════════════════════════════════════════════════════════

def compute_ofi(order_book: dict, levels: int = _DEFAULT_OB_LEVELS) -> float:
    """
    Order-Flow Imbalance from a ccxt ``fetch_order_book()`` snapshot.

    Parameters
    ----------
    order_book : dict
        Standard ccxt order-book dict: ``{"bids": [[price, size], ...],
        "asks": [[price, size], ...]}``.  Bids are sorted best-first
        (highest price first); asks are sorted best-first (lowest price first).
    levels : int
        Number of top-of-book levels to aggregate (default 5).

    Returns
    -------
    float
        Normalised OFI in [-1, +1].
        +1.0 → all depth is on the buy side (strong buy pressure).
        -1.0 → all depth is on the sell side (strong sell pressure).
        0.0  → balanced or no data.
    """
    bids = order_book.get("bids") or []
    asks = order_book.get("asks") or []

    bid_depth = sum(entry[1] for entry in bids[:levels] if len(entry) >= 2)
    ask_depth = sum(entry[1] for entry in asks[:levels] if len(entry) >= 2)

    total = bid_depth + ask_depth
    if total == 0.0:
        return 0.0

    return round((bid_depth - ask_depth) / total, 6)


def compute_vamp(order_book: dict, levels: int = 10) -> float:
    """
    Volume-Adjusted Mid Price from a ccxt ``fetch_order_book()`` snapshot.

    Computes the depth-weighted average price for both bid and ask sides
    separately, then returns their average — the "true" mid-market price
    adjusted for liquidity imbalance.

    Parameters
    ----------
    order_book : dict
        Standard ccxt order-book dict (same as ``compute_ofi``).
    levels : int
        Depth levels to use on each side (default 10).

    Returns
    -------
    float
        VAMP in absolute USD terms.  Returns 0.0 when data is insufficient.
    """
    bids = order_book.get("bids") or []
    asks = order_book.get("asks") or []

    def _vwap(side: list) -> float:
        pv = sum(entry[0] * entry[1] for entry in side[:levels] if len(entry) >= 2)
        v  = sum(entry[1]             for entry in side[:levels] if len(entry) >= 2)
        return pv / v if v > 0 else 0.0

    vwap_bid = _vwap(bids)
    vwap_ask = _vwap(asks)

    if vwap_bid == 0.0 and vwap_ask == 0.0:
        return 0.0

    if vwap_bid > 0.0 and vwap_ask > 0.0:
        return round((vwap_bid + vwap_ask) / 2.0, 8)

    return round(vwap_bid or vwap_ask, 8)


def build_trade_buckets(
    recent_trades: list[dict],
    bucket_size_usd: float = _DEFAULT_BUCKET_USD,
) -> list[dict]:
    """
    Transform a ccxt ``fetch_trades()`` response into fixed-dollar volume buckets.

    Each bucket accumulates trades until the total USD cost reaches
    ``bucket_size_usd``, then is sealed and a new bucket starts.

    Parameters
    ----------
    recent_trades : list[dict]
        ccxt trade dicts.  Required fields: ``side`` ("buy"/"sell"),
        ``price`` (float), ``amount`` (float).  ``cost`` is used when
        available; otherwise ``price × amount`` is used as a fallback.
    bucket_size_usd : float
        Target dollar volume per bucket (default $5,000).

    Returns
    -------
    list[dict]
        Each bucket: ``{"buy_vol": float, "sell_vol": float, "total_vol": float}``.
        Returns an empty list when ``recent_trades`` is empty.
    """
    if not recent_trades or bucket_size_usd <= 0:
        return []

    buckets: list[dict] = []
    current: dict = {"buy_vol": 0.0, "sell_vol": 0.0, "total_vol": 0.0}

    for trade in recent_trades:
        cost  = float(trade.get("cost") or 0.0)
        if cost <= 0:
            price  = float(trade.get("price") or 0.0)
            amount = float(trade.get("amount") or 0.0)
            cost   = price * amount
        if cost <= 0:
            continue

        side = (trade.get("side") or "").lower()

        if side == "buy":
            current["buy_vol"]  += cost
        else:
            current["sell_vol"] += cost
        current["total_vol"] += cost

        if current["total_vol"] >= bucket_size_usd:
            buckets.append({
                "buy_vol":   current["buy_vol"],
                "sell_vol":  current["sell_vol"],
                "total_vol": current["total_vol"],
            })
            current = {"buy_vol": 0.0, "sell_vol": 0.0, "total_vol": 0.0}

    return buckets


def compute_vpin(
    trade_buckets: list[dict],
    bucket_size_usd: float = _DEFAULT_BUCKET_USD,
    n_buckets: int = _DEFAULT_VPIN_BUCKETS,
) -> float:
    """
    Volume-Synchronised Probability of Informed Trading from trade buckets.

    VPIN = Σ|buy_vol - sell_vol| / Σtotal_vol  across the most-recent buckets.

    Parameters
    ----------
    trade_buckets : list[dict]
        Output of ``build_trade_buckets()``.
    bucket_size_usd : float
        Nominal bucket size (used only for docstring clarity; not used in math).
    n_buckets : int
        Number of most-recent buckets to include (default 50).

    Returns
    -------
    float
        VPIN in [0.0, 1.0].  0 = perfectly balanced; 1 = entirely one-sided.
        Returns 0.0 when bucket list is empty.
    """
    if not trade_buckets:
        return 0.0

    recent = trade_buckets[-n_buckets:]
    total_vol   = sum(b["total_vol"] for b in recent)
    imbalance   = sum(abs(b["buy_vol"] - b["sell_vol"]) for b in recent)

    if total_vol == 0.0:
        return 0.0

    return round(imbalance / total_vol, 6)


# ══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPAT API — OHLCV-based (used by existing tests & fallback path)
# ══════════════════════════════════════════════════════════════════════════════

def compute_ofi_ohlcv(
    candles: list[list],
    window: int = 10,
) -> float:
    """
    OHLCV-based OFI fallback.  Approximates net buying/selling pressure from
    candle direction × volume.  Normalised to [-1, +1].

    Parameters
    ----------
    candles : list[list]
        ccxt OHLCV: each element is [ts_ms, open, high, low, close, volume].
    window : int
        Number of most-recent candles to include (default 10).
    """
    if len(candles) < 2:
        return 0.0

    recent    = candles[-window:]
    net_flow  = 0.0
    total_vol = 0.0

    for bar in recent:
        _ts, o, h, l, c, v = bar[0], bar[1], bar[2], bar[3], bar[4], bar[5]
        if v is None or v <= 0:
            continue
        direction  = 1.0 if c >= o else -1.0
        net_flow  += direction * v
        total_vol += v

    if total_vol == 0.0:
        return 0.0

    return round(net_flow / total_vol, 6)


def compute_vamp_ohlcv(
    candles: list[list],
    window: int = 20,
) -> float:
    """
    OHLCV-based VAMP fallback.  Fractional deviation of the latest close from
    the VWAP across *window* bars.

    Parameters
    ----------
    candles : list[list]
        ccxt OHLCV candles.
    window : int
        VWAP window in bars (default 20).
    """
    if len(candles) < 2:
        return 0.0

    recent   = candles[-window:]
    vwap_num = 0.0
    vwap_den = 0.0

    for bar in recent:
        _ts, o, h, l, c, v = bar[0], bar[1], bar[2], bar[3], bar[4], bar[5]
        if v is None or v <= 0:
            continue
        typical   = (h + l + c) / 3.0
        vwap_num += typical * v
        vwap_den += v

    if vwap_den == 0.0:
        return 0.0

    vwap        = vwap_num / vwap_den
    latest_close = candles[-1][4]

    if vwap == 0.0:
        return 0.0

    return round((latest_close - vwap) / vwap, 8)


def compute_vpin_ohlcv(
    candles: list[list],
    window: int = 20,
) -> float:
    """
    OHLCV-based VPIN fallback.  Estimates informed flow as |buy - sell| / total
    using the high-low fraction method.

    Parameters
    ----------
    candles : list[list]
        ccxt OHLCV candles.
    window : int
        Number of bars to use (default 20).
    """
    if len(candles) < 2:
        return 0.0

    recent   = candles[-window:]
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
            b = v * 0.5
            s = v * 0.5

        buy_vol  += b
        sell_vol += s
        total    += v

    if total == 0.0:
        return 0.0

    return round(abs(buy_vol - sell_vol) / total, 6)


# ══════════════════════════════════════════════════════════════════════════════
# MicrostructureSignal — composite dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MicrostructureSignal:
    """
    Bundles the three microstructure metrics for one symbol / cycle.

    Attributes
    ----------
    symbol : str
    ofi    : float   [-1, +1] — net buy/sell pressure
    vamp   : float   mid-price depth-weighted average (absolute USD, or 0)
    vpin   : float   [0, 1]  — adverse-selection proxy
    """

    symbol: str
    ofi:    float
    vamp:   float
    vpin:   float

    # ── Primary factory: order book + recent trades ────────────────────────────

    @classmethod
    def from_orderbook(
        cls,
        order_book: dict,
        recent_trades: list[dict],
        symbol: str = "",
        ob_levels: int = _DEFAULT_OB_LEVELS,
        bucket_size_usd: float = _DEFAULT_BUCKET_USD,
    ) -> "MicrostructureSignal":
        """
        Compute all three metrics from live order-book and trade data.

        Parameters
        ----------
        order_book     : ccxt ``fetch_order_book()`` response dict.
        recent_trades  : ccxt ``fetch_trades()`` response list.
        symbol         : Symbol label (BTC/USD etc.).
        ob_levels      : Book depth levels for OFI (default 5).
        bucket_size_usd: Bucket size for VPIN (default $5,000).
        """
        buckets = build_trade_buckets(recent_trades, bucket_size_usd=bucket_size_usd)
        return cls(
            symbol = symbol,
            ofi    = compute_ofi(order_book, levels=ob_levels),
            vamp   = compute_vamp(order_book),
            vpin   = compute_vpin(buckets, bucket_size_usd=bucket_size_usd),
        )

    # ── Backward-compat factory: OHLCV candles ────────────────────────────────

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
        Compute all three metrics from OHLCV candles (backward-compat).
        Used as a fallback when order-book / trade data are unavailable.
        """
        return cls(
            symbol = symbol,
            ofi    = compute_ofi_ohlcv(candles,  window=ofi_window),
            vamp   = compute_vamp_ohlcv(candles, window=vamp_window),
            vpin   = compute_vpin_ohlcv(candles, window=vpin_window),
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
        Gate a new entry based on microstructure conditions.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        if self.vpin >= vpin_block:
            return False, (
                f"VPIN={self.vpin:.3f} >= block_threshold={vpin_block:.2f} (toxic flow)"
            )

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
        return {
            "symbol": self.symbol,
            "ofi":    round(self.ofi,  4),
            "vamp":   round(self.vamp, 6),
            "vpin":   round(self.vpin, 4),
        }

    def __repr__(self) -> str:
        return (
            f"MicrostructureSignal(symbol={self.symbol!r}, "
            f"OFI={self.ofi:+.3f}, VAMP={self.vamp:.4f}, VPIN={self.vpin:.3f})"
        )
