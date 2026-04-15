"""
pair_discovery.py — Poseidon Dynamic Pair Discovery
Screens a symbol universe for cointegrated pairs in two stages:
  1. Fast pairwise log-price correlation screening (O(n²) but cheap)
  2. ADF cointegration test on high-correlation candidates only

Runs once per 24 hours; results are used by the 15-minute cycle loop
to check Z-scores without re-running the expensive ADF step.
"""
from __future__ import annotations

import math
from itertools import combinations

from loguru import logger

from pairs_engine import ols_hedge_ratio, adf_pvalue, calculate_spread_series


# ── Helper math ───────────────────────────────────────────────────────────────

def _log_prices(prices: list[float]) -> list[float]:
    return [math.log(p) for p in prices if p > 0]


def _pearson_corr(x: list[float], y: list[float]) -> float:
    """Fast pure-Python Pearson correlation."""
    n = min(len(x), len(y))
    if n < 10:
        return 0.0
    x, y = x[-n:], y[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx < 1e-12 or dy < 1e-12:
        return 0.0
    return num / (dx * dy)


# ── Pair discovery ────────────────────────────────────────────────────────────

def discover_pairs(
    symbols: list[str],
    daily_closes: dict[str, list[float]],
    min_corr: float = 0.85,
    adf_pvalue_max: float = 0.15,
    max_pairs: int = 50,
) -> list[dict]:
    """
    Discover cointegrated pairs from a symbol universe.

    Args:
        symbols: list of ccxt symbols in the universe (e.g. ['BTC/USD', ...])
        daily_closes: mapping from symbol → list of daily close prices (30+ days)
        min_corr: minimum |log-price Pearson correlation| to advance to ADF
        adf_pvalue_max: max ADF p-value to qualify as cointegrated
        max_pairs: cap on returned pairs (sorted by ADF p-value ascending)

    Returns:
        List of pair dicts with keys:
            pair_set_id, asset_a, asset_b, description, corr, adf_p
        Ordered by adf_p ascending (most cointegrated first).
    """
    # Only keep symbols with enough data
    valid = [s for s in symbols if len(daily_closes.get(s, [])) >= 20]
    logger.info(f"Pair discovery | {len(valid)}/{len(symbols)} symbols have ≥20 daily bars")

    if len(valid) < 2:
        logger.warning("Pair discovery | Not enough symbols for pair screening")
        return []

    # Pre-compute log prices for all valid symbols
    log_prices: dict[str, list[float]] = {}
    for sym in valid:
        lp = _log_prices(daily_closes[sym])
        if len(lp) >= 20:
            log_prices[sym] = lp

    # ── Stage 1: Correlation screening ────────────────────────────────────────
    candidates: list[tuple[str, str, float]] = []
    total_pairs = len(log_prices) * (len(log_prices) - 1) // 2
    logger.info(f"Pair discovery | Screening {total_pairs:,} pairs for |corr| ≥ {min_corr}")

    for sym_a, sym_b in combinations(list(log_prices.keys()), 2):
        corr = _pearson_corr(log_prices[sym_a], log_prices[sym_b])
        if abs(corr) >= min_corr:
            candidates.append((sym_a, sym_b, corr))

    # Sort by |corr| descending — test best pairs first
    candidates.sort(key=lambda x: abs(x[2]), reverse=True)
    logger.info(
        f"Pair discovery | {len(candidates)} candidate pairs pass correlation gate | "
        f"Running ADF on all of them..."
    )

    # ── Stage 2: ADF cointegration test ───────────────────────────────────────
    tradeable: list[dict] = []
    tested = 0

    for sym_a, sym_b, corr in candidates:
        closes_a = daily_closes[sym_a]
        closes_b = daily_closes[sym_b]
        n = min(len(closes_a), len(closes_b))
        closes_a = closes_a[-n:]
        closes_b = closes_b[-n:]

        try:
            lp_a = _log_prices(closes_a)
            lp_b = _log_prices(closes_b)
            if len(lp_a) < 15 or len(lp_b) < 15:
                continue

            hedge = ols_hedge_ratio(lp_a, lp_b)
            spreads = calculate_spread_series(closes_a, closes_b, hedge)
            if len(spreads) < 15:
                continue

            adf_p = adf_pvalue(spreads)
            tested += 1

            if adf_p < adf_pvalue_max:
                tradeable.append({
                    "asset_a": sym_a,
                    "asset_b": sym_b,
                    "corr": round(corr, 4),
                    "adf_p": round(adf_p, 4),
                    "description": (
                        f"{sym_a.split('/')[0]} vs {sym_b.split('/')[0]} "
                        f"(corr={corr:.2f}, ADF={adf_p:.3f})"
                    ),
                })

        except Exception as e:
            logger.debug(f"Pair discovery | ADF failed {sym_a}/{sym_b}: {e}")

    logger.info(
        f"Pair discovery | ADF tested {tested} pairs | "
        f"{len(tradeable)} cointegrated (p < {adf_pvalue_max})"
    )

    # Sort best cointegration first, cap at max_pairs
    tradeable.sort(key=lambda x: x["adf_p"])
    result: list[dict] = []
    for i, pair in enumerate(tradeable[:max_pairs]):
        result.append({
            "pair_set_id": i + 1,
            "asset_a": pair["asset_a"],
            "asset_b": pair["asset_b"],
            "description": pair["description"],
            "corr": pair["corr"],
            "adf_p": pair["adf_p"],
        })

    return result
