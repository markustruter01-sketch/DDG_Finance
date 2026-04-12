"""
hurst_filter.py — Hurst Exponent + ADF Stationarity Pre-Entry Filter
=====================================================================
Addition 1: Academic research-validated mean-reversion quality gate.

Before a new entry is evaluated, the bot checks:
  1. Hurst exponent (R/S method) on last 100 hourly OHLCV closes.
     H < 0.5  → mean-reverting  → ALLOW entry (pass to existing Z/VPIN/RSI checks)
     H >= 0.5 → trending/random → BLOCK entry
  2. ADF (Augmented Dickey-Fuller) stationarity test.
     p < 0.15  → stationary     → ALLOW
     p >= 0.15 → non-stationary → BLOCK

Results are cached per pair with a 4-hour TTL to avoid recalculating every
60-second cycle.  If fewer than 100 candles are available, both filters are
skipped and entry is allowed (fail-open to preserve existing behaviour).
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

MIN_CANDLES = 100
HURST_THRESHOLD = 0.5
ADF_PVALUE_THRESHOLD = 0.15
CACHE_TTL_SECONDS = 4 * 3600


class _CacheEntry:
    __slots__ = ("hurst", "adf_pvalue", "expires_at")

    def __init__(self, hurst: float, adf_pvalue: float, ttl: float = CACHE_TTL_SECONDS):
        self.hurst = hurst
        self.adf_pvalue = adf_pvalue
        self.expires_at = time.monotonic() + ttl


class HurstADFCache:
    """
    Per-pair cache for Hurst + ADF results with a configurable TTL.

    Usage:
        cache = HurstADFCache()
        allowed, reason, hurst, adf_p = cache.check(symbol, closes)
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def _is_valid(self, symbol: str) -> bool:
        entry = self._cache.get(symbol)
        return entry is not None and time.monotonic() < entry.expires_at

    def invalidate(self, symbol: str) -> None:
        self._cache.pop(symbol, None)

    def check(
        self,
        symbol: str,
        closes: list[float],
    ) -> tuple[bool, str, Optional[float], Optional[float]]:
        """
        Returns (allow_entry, reason, hurst_value, adf_pvalue).

        allow_entry=True  → pass to existing Z/VPIN/RSI gates
        allow_entry=False → block entry, reason explains why
        hurst_value / adf_pvalue may be None if skipped (insufficient data).

        Cache is checked first — a valid cached result is returned immediately
        without requiring sufficient closes.  The insufficient-data early-return
        only fires when the cache is cold AND the provided closes are too few.
        """
        if self._is_valid(symbol):
            entry = self._cache[symbol]
            return _evaluate(symbol, entry.hurst, entry.adf_pvalue)

        if len(closes) < MIN_CANDLES:
            return (
                True,
                f"Hurst/ADF SKIP: only {len(closes)} candles (need {MIN_CANDLES}) — proceeding",
                None,
                None,
            )

        prices = np.asarray(closes[-MIN_CANDLES:], dtype=np.float64)
        hurst = _calculate_hurst(prices)
        adf_p = _run_adf(prices)

        self._cache[symbol] = _CacheEntry(hurst, adf_p, self._ttl)
        return _evaluate(symbol, hurst, adf_p)

    def get_cached(self, symbol: str) -> tuple[Optional[float], Optional[float]]:
        """Return (hurst, adf_pvalue) if the cache is valid, else (None, None)."""
        entry = self._cache.get(symbol)
        if entry is None or time.monotonic() >= entry.expires_at:
            return None, None
        return entry.hurst, entry.adf_pvalue


def _evaluate(
    symbol: str,
    hurst: float,
    adf_p: float,
) -> tuple[bool, str, float, float]:
    if hurst >= HURST_THRESHOLD:
        return (
            False,
            f"HURST BLOCK: {symbol} H={hurst:.3f} — trending/random, skipping mean reversion entry",
            hurst,
            adf_p,
        )
    if adf_p >= ADF_PVALUE_THRESHOLD:
        return (
            False,
            f"ADF BLOCK: {symbol} p={adf_p:.3f} — non-stationary, skipping entry",
            hurst,
            adf_p,
        )
    return (
        True,
        f"Hurst/ADF PASS: {symbol} H={hurst:.3f} p={adf_p:.3f} — mean-reverting and stationary",
        hurst,
        adf_p,
    )


def _calculate_hurst(prices: np.ndarray, min_lags: int = 10, max_lags: int = 50) -> float:
    """
    R/S (Rescaled Range) Hurst Exponent.
    Returns H clipped to [0, 1]. Defaults to 0.5 (random walk) on failure.
    """
    lags = range(min_lags, max_lags)
    rs_values: list[tuple[int, float]] = []

    for lag in lags:
        chunks = [prices[i : i + lag] for i in range(0, len(prices) - lag, lag)]
        if len(chunks) < 2:
            continue
        rs_list: list[float] = []
        for chunk in chunks:
            mean = np.mean(chunk)
            deviations = np.cumsum(chunk - mean)
            r = float(np.max(deviations) - np.min(deviations))
            s = float(np.std(chunk))
            if s > 0:
                rs_list.append(r / s)
        if rs_list:
            rs_values.append((lag, float(np.mean(rs_list))))

    if len(rs_values) < 2:
        return 0.5

    lags_log = np.log([x[0] for x in rs_values])
    rs_log   = np.log([x[1] for x in rs_values])
    H = float(np.polyfit(lags_log, rs_log, 1)[0])
    return float(np.clip(H, 0.0, 1.0))


def _run_adf(prices: np.ndarray) -> float:
    """
    ADF stationarity test. Returns p-value. Returns 1.0 on any failure
    (conservative: treats as non-stationary so block is applied only if
    Hurst also passed — but since Hurst block is first, ADF block with p=1.0
    would only trigger if hurst < 0.5 somehow failed).
    """
    try:
        from statsmodels.tsa.stattools import adfuller
        result = adfuller(prices, maxlag=5, autolag="AIC")
        return float(result[1])
    except Exception:
        return 1.0
