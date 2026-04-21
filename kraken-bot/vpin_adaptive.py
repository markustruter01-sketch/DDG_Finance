"""
vpin_adaptive.py — Dynamic VPIN Threshold (Stage 2)
=====================================================
Replaces hardcoded VPIN_BLOCK_THRESH (0.82) with a rolling 30-day mean
derived from empirical VPIN observations.

Architecture:
  - Every cycle, the bot logs the current VPIN for each symbol
  - The rolling window stores up to 30 days of VPIN observations
  - The dynamic threshold = rolling_mean + 1.5 * rolling_stddev
  - Floor: 0.60 (never lower than this)
  - Ceiling: 0.95 (never higher than this)
  - If insufficient data (< 100 observations), returns the legacy 0.82

This prevents two failure modes:
  1. In calm markets where VPIN rarely exceeds 0.50, the old 0.82
     threshold was never reached — wasting the filter entirely.
  2. In volatile markets where VPIN routinely sits at 0.70-0.80,
     the old 0.82 was too tight — blocking valid entries constantly.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Optional

from loguru import logger

VPIN_HISTORY_FILE = Path(__file__).parent / "_vpin_history.json"
MAX_HISTORY_ENTRIES = 30 * 24 * 60
MIN_OBSERVATIONS = 100
STDDEV_MULTIPLIER = 1.5
FLOOR_THRESHOLD = 0.60
CEILING_THRESHOLD = 0.95
LEGACY_THRESHOLD = 0.82

_lock = Lock()
_observations: deque[dict] = deque(maxlen=MAX_HISTORY_ENTRIES)
_cached_threshold: Optional[float] = None
_last_recalc: float = 0.0
RECALC_INTERVAL = 300


def _load_history() -> None:
    global _observations
    if VPIN_HISTORY_FILE.exists():
        try:
            raw = json.loads(VPIN_HISTORY_FILE.read_text())
            cutoff = time.time() - (30 * 24 * 3600)
            filtered = [o for o in raw if o.get("ts", 0) > cutoff]
            _observations = deque(filtered, maxlen=MAX_HISTORY_ENTRIES)
            logger.info(f"VPINAdaptive | Loaded {len(_observations)} historical observations")
        except Exception as exc:
            logger.warning(f"VPINAdaptive | Could not load history: {exc}")


def _save_history() -> None:
    try:
        data = list(_observations)[-10000:]
        VPIN_HISTORY_FILE.write_text(json.dumps(data))
    except Exception as exc:
        logger.debug(f"VPINAdaptive | Save failed: {exc}")


def record_vpin(symbol: str, vpin: float) -> None:
    with _lock:
        _observations.append({
            "symbol": symbol,
            "vpin": round(vpin, 6),
            "ts": time.time(),
        })

    if len(_observations) % 100 == 0:
        _save_history()


def get_dynamic_threshold(symbol: Optional[str] = None) -> float:
    """
    Compute the adaptive VPIN entry-block threshold.

    Uses a rolling 30-day mean + 1.5σ approach:
      threshold = mean(VPIN_30d) + 1.5 * stddev(VPIN_30d)

    Args:
        symbol: If provided, compute threshold for this symbol only.
                If None, compute across all symbols (fleet-wide).

    Returns:
        Dynamic threshold in [FLOOR_THRESHOLD, CEILING_THRESHOLD].
        Returns LEGACY_THRESHOLD if insufficient data.
    """
    global _cached_threshold, _last_recalc

    now = time.time()
    if _cached_threshold is not None and (now - _last_recalc) < RECALC_INTERVAL:
        return _cached_threshold

    with _lock:
        cutoff = now - (30 * 24 * 3600)
        if symbol:
            values = [o["vpin"] for o in _observations if o["ts"] > cutoff and o["symbol"] == symbol]
        else:
            values = [o["vpin"] for o in _observations if o["ts"] > cutoff]

    if len(values) < MIN_OBSERVATIONS:
        return LEGACY_THRESHOLD

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
    stddev = math.sqrt(variance)

    threshold = mean + STDDEV_MULTIPLIER * stddev
    threshold = max(FLOOR_THRESHOLD, min(threshold, CEILING_THRESHOLD))
    threshold = round(threshold, 4)

    _cached_threshold = threshold
    _last_recalc = now

    logger.debug(
        f"VPINAdaptive | Recalculated: mean={mean:.4f} σ={stddev:.4f} "
        f"threshold={threshold:.4f} (n={len(values)})"
    )

    return threshold


def get_stats() -> dict:
    with _lock:
        cutoff = time.time() - (30 * 24 * 3600)
        values = [o["vpin"] for o in _observations if o["ts"] > cutoff]

    if not values:
        return {
            "observations": 0,
            "mean": 0.0,
            "stddev": 0.0,
            "dynamic_threshold": LEGACY_THRESHOLD,
            "using_legacy": True,
        }

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
    stddev = math.sqrt(variance)

    return {
        "observations": len(values),
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "dynamic_threshold": get_dynamic_threshold(),
        "using_legacy": len(values) < MIN_OBSERVATIONS,
    }


_load_history()
