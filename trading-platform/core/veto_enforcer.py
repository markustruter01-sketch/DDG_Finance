"""
trading-platform/core/veto_enforcer.py  —  Gemini Veto Conditions Reader
=========================================================================
Reads the daily veto_conditions.json written by the Gemini self-critic
auditor (Task #26, gemini_auditor.py) and provides a fast pre-trade
lookup so the executor can block vetoed tickers before placing orders.

Safety contract
---------------
  • Returns an empty frozenset (no vetoes active) if the file does not
    exist, cannot be parsed, or if the veto window has expired.
    → Fail-open: trading proceeds normally when the auditor hasn't run.
  • Results are cached for _CACHE_TTL_SECONDS (default 5 minutes) to
    avoid repeated disk reads on every 15-minute intraday cycle.
    The veto file is written once per day at 04:15 AM ET.

Expected schema of veto_conditions.json (written by gemini_auditor.py)
-----------------------------------------------------------------------
{
    "generated_at":   "<ISO-8601 UTC>",
    "valid_until":    "<ISO-8601 UTC>",         # optional expiry timestamp
    "vetoed_tickers": ["AAPL", "TSLA"],         # uppercase ticker symbols
    "conditions": [                             # optional structured rules
        {"type": "vpin_threshold", "value": 0.7},
        {"type": "news_blacklist",  "ticker": "META"}
    ]
}

Usage
-----
    from core.veto_enforcer import is_vetoed, load_active_vetoes

    if is_vetoed("TSLA"):
        logger.warning("Veto: TSLA blocked by Gemini daily self-critic")
        # skip this allocation
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

# ── Configuration ─────────────────────────────────────────────────────────────
# The veto file sits next to the other daily logs inside trading-platform/logs/.
_VETO_FILE         = Path(__file__).parent.parent / "logs" / "veto_conditions.json"
_CACHE_TTL_SECONDS = 300           # refresh from disk at most every 5 minutes
_EMPTY_VETOES: frozenset[str] = frozenset()

# ── Module-level cache ────────────────────────────────────────────────────────
_cache_ts:         float             = 0.0
_cached_vetoes:    frozenset[str]    = _EMPTY_VETOES
_cached_conditions: list[dict]       = []


def load_active_vetoes() -> frozenset[str]:
    """
    Load and return the set of currently vetoed ticker symbols.

    Reads _VETO_FILE at most once per _CACHE_TTL_SECONDS.
    Returns an empty frozenset when:
      - the file does not exist (auditor hasn't run yet today)
      - the file is unparseable (corrupt write)
      - valid_until is in the past (yesterday's vetoes have expired)

    Returns
    -------
    frozenset[str]
        Uppercase ticker symbols that are currently blocked by the auditor.
        Empty → no vetoes active; all tickers may trade freely.
    """
    global _cache_ts, _cached_vetoes, _cached_conditions

    now = time.time()
    if now - _cache_ts < _CACHE_TTL_SECONDS:
        return _cached_vetoes          # cache hit

    # Cache miss — refresh from disk
    _cache_ts = now

    if not _VETO_FILE.exists():
        logger.debug(
            "VetoEnforcer | veto_conditions.json not found — "
            "no active vetoes (Task #26 auditor not yet deployed)"
        )
        _cached_vetoes     = _EMPTY_VETOES
        _cached_conditions = []
        return _cached_vetoes

    try:
        payload: dict[str, Any] = json.loads(_VETO_FILE.read_text())
    except Exception as exc:
        logger.debug(
            f"VetoEnforcer | Failed to parse veto_conditions.json: {exc} "
            "— treating as no vetoes (fail-open)"
        )
        _cached_vetoes     = _EMPTY_VETOES
        _cached_conditions = []
        return _cached_vetoes

    # ── Expiry check ─────────────────────────────────────────────────────────
    valid_until_str = payload.get("valid_until")
    if valid_until_str:
        try:
            valid_until = datetime.fromisoformat(valid_until_str)
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > valid_until:
                logger.debug(
                    f"VetoEnforcer | Veto conditions expired at {valid_until_str} "
                    "— no active vetoes"
                )
                _cached_vetoes     = _EMPTY_VETOES
                _cached_conditions = []
                return _cached_vetoes
        except Exception as exc:
            logger.debug(f"VetoEnforcer | Could not parse valid_until: {exc}")

    # ── Collect vetoed tickers ────────────────────────────────────────────────
    raw_tickers = payload.get("vetoed_tickers", [])
    if not isinstance(raw_tickers, list):
        raw_tickers = []

    # Also harvest tickers embedded inside conditions[].ticker entries
    extra_tickers: list[str] = []
    conditions = payload.get("conditions", [])
    if isinstance(conditions, list):
        for cond in conditions:
            if isinstance(cond, dict) and "ticker" in cond:
                extra_tickers.append(str(cond["ticker"]).upper())

    vetoed = frozenset(
        str(t).upper().strip()
        for t in raw_tickers + extra_tickers
        if t
    )

    if vetoed:
        logger.info(
            f"VetoEnforcer | {len(vetoed)} active veto(s) loaded from "
            f"{_VETO_FILE.name}: {sorted(vetoed)}"
        )
    else:
        logger.debug(
            "VetoEnforcer | veto_conditions.json present but no tickers vetoed"
        )

    _cached_vetoes     = vetoed
    _cached_conditions = conditions if isinstance(conditions, list) else []
    return _cached_vetoes


def is_vetoed(ticker: str) -> bool:
    """
    Return True if *ticker* is currently blocked by the Gemini auditor.

    Parameters
    ----------
    ticker : str
        Symbol to check (case-insensitive; "/" is stripped for crypto pairs).

    Returns
    -------
    bool
        True  → ticker is in the active veto set; skip this allocation.
        False → ticker is clear (including when the veto file is absent).
    """
    normalised = ticker.upper().replace("/", "").strip()
    return normalised in load_active_vetoes()


def get_active_conditions() -> list[dict]:
    """
    Return the raw ``conditions`` list from the current veto file.

    Useful for callers that need to check non-ticker conditions such as
    ``{"type": "vpin_threshold", "value": 0.7}``.

    Returns an empty list when no veto file is present or no conditions
    have been specified.
    """
    load_active_vetoes()   # refresh cache if stale
    return list(_cached_conditions)


def get_veto_status() -> dict:
    """
    Return a summary dict suitable for admin endpoints or the dashboard.

    Returns
    -------
    dict
        {
            "active_veto_count": int,
            "vetoed_tickers":    list[str],
            "condition_count":   int,
            "file_exists":       bool,
            "cache_age_seconds": float,
        }
    """
    vetoes = load_active_vetoes()
    return {
        "active_veto_count": len(vetoes),
        "vetoed_tickers":    sorted(vetoes),
        "condition_count":   len(get_active_conditions()),
        "file_exists":       _VETO_FILE.exists(),
        "cache_age_seconds": round(time.time() - _cache_ts, 1),
    }
