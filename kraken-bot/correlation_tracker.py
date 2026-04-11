"""
correlation_tracker.py — Stage 2: Correlation-Aware Portfolio Sizing.

When sizing a new entry, check how correlated the candidate symbol is with
each symbol already held in open_positions.  High correlation means the new
trade adds concentrated exposure to the same market factor — so we reduce size.

Penalty rules (applied after regime and pair-sizing multipliers):
  avg_corr > 0.85  →  0.50×  HIGH correlation — heavy overlap, halve the size
  avg_corr > 0.70  →  0.75×  MODERATE correlation — reduce size 25%
  avg_corr ≤ 0.70  →  1.00×  Low correlation — no adjustment

Correlation is computed from log-returns of OHLCV close prices stored in the
module-level `_closes_cache` dict, which main.py populates each cycle.
A minimum of 15 aligned return observations is required; below that threshold
the function returns 1.00× with a note (insufficient data).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Sequence

logger = logging.getLogger("correlation_tracker")

# Thresholds
HIGH_CORR_THRESHOLD     = 0.85   # → 0.50× penalty
MODERATE_CORR_THRESHOLD = 0.70   # → 0.75× penalty
MIN_OBSERVATIONS        = 15     # minimum aligned return pairs required

# How many of the most-recent closes to use for correlation
CORR_WINDOW = 50


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_returns(prices: Sequence[float], window: int = CORR_WINDOW) -> list[float]:
    """Compute log returns from the last `window` price observations."""
    tail = list(prices)[-window - 1:]   # need one extra to compute first return
    returns = []
    for i in range(1, len(tail)):
        p_prev, p_curr = tail[i - 1], tail[i]
        if p_prev > 0 and p_curr > 0:
            returns.append(math.log(p_curr / p_prev))
    return returns


def _pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation coefficient — returns None if not computable."""
    n = min(len(x), len(y))
    if n < MIN_OBSERVATIONS:
        return None

    # Use tail-aligned slice
    x = x[-n:]
    y = y[-n:]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if den_x == 0 or den_y == 0:
        return None

    corr = num / (den_x * den_y)
    # Clamp to [-1, 1] for floating-point safety
    return max(-1.0, min(1.0, corr))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_entry_correlation_penalty(
    candidate: str,
    open_symbols: list[str],
    closes_cache: dict[str, list[float]],
    window: int = CORR_WINDOW,
) -> tuple[float, str]:
    """
    Compute the correlation-based size penalty for opening a new position
    in `candidate` given the current `open_symbols`.

    Parameters
    ----------
    candidate     : symbol being considered for entry (e.g. "BTC/USD")
    open_symbols  : list of symbols currently held in open_positions
    closes_cache  : dict mapping symbol → list of recent close prices
                    (populated each cycle by main.py from OHLCV data)
    window        : number of closes to use for return computation

    Returns
    -------
    (scale_factor, reason_string)
    """
    # No open positions → nothing to correlate against
    relevant = [s for s in open_symbols if s != candidate and s in closes_cache]
    if not relevant:
        return (1.0, "No open positions to correlate against — normal sizing")

    if candidate not in closes_cache or len(closes_cache[candidate]) < MIN_OBSERVATIONS + 1:
        return (1.0, f"Insufficient price history for {candidate} — no correlation adjustment")

    cand_returns = _log_returns(closes_cache[candidate], window)
    if len(cand_returns) < MIN_OBSERVATIONS:
        return (1.0, f"Insufficient returns for {candidate} ({len(cand_returns)} obs) — no adjustment")

    pair_corrs: list[tuple[str, float]] = []
    skipped: list[str] = []

    for sym in relevant:
        sym_prices = closes_cache.get(sym, [])
        if len(sym_prices) < MIN_OBSERVATIONS + 1:
            skipped.append(sym)
            continue
        sym_returns = _log_returns(sym_prices, window)
        corr = _pearson(cand_returns, sym_returns)
        if corr is not None:
            pair_corrs.append((sym, corr))
        else:
            skipped.append(sym)

    if not pair_corrs:
        note = f" (skipped: {', '.join(skipped)})" if skipped else ""
        return (1.0, f"No valid correlation pairs for {candidate}{note} — normal sizing")

    avg_corr = sum(c for _, c in pair_corrs) / len(pair_corrs)
    max_sym, max_corr = max(pair_corrs, key=lambda kv: kv[1])
    n_pairs = len(pair_corrs)

    if avg_corr > HIGH_CORR_THRESHOLD:
        return (
            0.5,
            f"CORR-HIGH: avg={avg_corr:.2f} max={max_corr:.2f} ({max_sym}) "
            f"over {n_pairs} open pair(s) — halving position size",
        )
    elif avg_corr > MODERATE_CORR_THRESHOLD:
        return (
            0.75,
            f"CORR-MODERATE: avg={avg_corr:.2f} max={max_corr:.2f} ({max_sym}) "
            f"over {n_pairs} open pair(s) — reducing size 25%",
        )
    else:
        return (
            1.0,
            f"CORR-OK: avg={avg_corr:.2f} max={max_corr:.2f} ({max_sym}) "
            f"over {n_pairs} open pair(s) — no adjustment",
        )


def summarise_open_correlations(
    open_symbols: list[str],
    closes_cache: dict[str, list[float]],
    window: int = CORR_WINDOW,
) -> dict[str, dict]:
    """
    Compute pairwise correlations for all currently open positions.
    Used by the report section to display a correlation heatmap summary.

    Returns {symbol: {"max_corr": float, "max_with": str, "avg_corr": float}}
    """
    result: dict[str, dict] = {}
    for sym in open_symbols:
        others = [s for s in open_symbols if s != sym and s in closes_cache]
        if sym not in closes_cache or not others:
            result[sym] = {"max_corr": 0.0, "max_with": "—", "avg_corr": 0.0}
            continue

        sym_returns = _log_returns(closes_cache.get(sym, []), window)
        corrs = []
        for other in others:
            other_returns = _log_returns(closes_cache.get(other, []), window)
            c = _pearson(sym_returns, other_returns)
            if c is not None:
                corrs.append((other, c))

        if not corrs:
            result[sym] = {"max_corr": 0.0, "max_with": "—", "avg_corr": 0.0}
        else:
            avg = sum(c for _, c in corrs) / len(corrs)
            max_other, max_c = max(corrs, key=lambda kv: kv[1])
            result[sym] = {
                "max_corr": round(max_c, 3),
                "max_with": max_other,
                "avg_corr": round(avg, 3),
            }
    return result
