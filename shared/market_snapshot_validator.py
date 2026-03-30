"""
shared/market_snapshot_validator.py  —  Market Data Integrity Gate
===================================================================
Validates an assembled market snapshot before it reaches the LLM.
If the snapshot has gaps (all tickers errored), empty bar counts, or
stale timestamps the validator returns ok=False and the caller can
abort the analysis cycle without spending a single LLM token.

This is the "Data Circuit Breaker" described in Stage 1 of the
Hybrid Agentic Architecture spec.  It is a pure function: no side
effects, no API calls, no file I/O.

Usage
-----
    import sys, os, time
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from shared.market_snapshot_validator import validate_snapshot

    result = validate_snapshot({
        "market_data":  market_data,
        "macro_data":   macro_data,
        "news_data":    news_data,
        "_snapshot_ts": time.time(),  # optional — enables staleness check
    })
    if not result.ok:
        logger.warning(f"DataCircuitBreaker: {result.reason}")
        raise RuntimeError(f"DataCircuitBreaker: {result.reason}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

MAX_STALENESS_MINUTES: int = 20
MIN_BAR_COUNT: int = 1


@dataclass(frozen=True)
class ValidationResult:
    """
    Outcome from validate_snapshot().

    Attributes
    ----------
    ok : bool
        True  → snapshot is healthy; the analysis cycle may proceed.
        False → snapshot has gaps or stale data; cycle should abort.
    reason : str
        Human-readable description of the first failure found.
        Empty string when ok=True.
    checks_passed : int
        Number of validation checks that passed.
    checks_failed : int
        Number of validation checks that failed.
    """
    ok: bool
    reason: str
    checks_passed: int = 0
    checks_failed: int = 0


def validate_snapshot(
    snapshot: dict[str, Any],
    max_staleness_minutes: int = MAX_STALENESS_MINUTES,
    min_bar_count: int = MIN_BAR_COUNT,
) -> ValidationResult:
    """
    Validate an incoming market snapshot for structural integrity and
    data freshness before the LLM is invoked.

    Parameters
    ----------
    snapshot : dict
        Expected keys:
          • ``"market_data"``  — output of yfinance_client.fetch_market_data()
          • ``"news_data"``    — output of news_client.fetch_news()
          • ``"macro_data"``   — output of fred_client.fetch_macro_data()
                                 (may be empty dict for crypto-only cycles)
          • ``"_snapshot_ts"`` — optional float (unix seconds) of when data
                                 was fetched; enables the staleness check.

    max_staleness_minutes : int
        Maximum age in minutes of the snapshot timestamp before it is
        considered stale.  Only evaluated when ``"_snapshot_ts"`` is present.
        Default: 20 minutes (covers the 15-minute intraday cycle cadence).

    min_bar_count : int
        Minimum number of tickers that must have non-error bar data.
        Default: 1 (at least one ticker must have usable price history).

    Returns
    -------
    ValidationResult
        ``ok=True``  → snapshot is healthy.
        ``ok=False`` → snapshot has issues; ``reason`` describes the first failure.
    """
    passed  = 0
    failures: list[str] = []

    market_data = snapshot.get("market_data")
    news_data   = snapshot.get("news_data")

    # ── Check 1: Required keys are present and not None ────────────────────────
    # All three data domains must be present.  macro_data may be an empty dict
    # for crypto-only cycles (FRED data not applicable), but must not be None.
    missing = [
        k for k in ("market_data", "macro_data", "news_data")
        if snapshot.get(k) is None
    ]
    if missing:
        failures.append(
            f"Missing required snapshot key(s): {', '.join(missing)}"
        )
    else:
        passed += 1

    # ── Check 2: market_data has at least min_bar_count healthy tickers ────────
    if market_data is not None:
        by_ticker = market_data.get("by_ticker", {})

        if not isinstance(by_ticker, dict) or len(by_ticker) == 0:
            failures.append(
                "market_data.by_ticker is empty — no price data available for any ticker"
            )
        else:
            healthy = [
                sym for sym, td in by_ticker.items()
                if isinstance(td, dict)
                and "error" not in td
                and len(td.get("bars", [])) >= min_bar_count
            ]
            if len(healthy) < min_bar_count:
                errors = [
                    sym for sym, td in by_ticker.items()
                    if "error" in td
                ]
                failures.append(
                    f"All {len(by_ticker)} ticker(s) have errors or zero bars "
                    f"(errored: {errors or 'none'}); "
                    f"need ≥ {min_bar_count} healthy ticker(s)"
                )
            else:
                passed += 1

    # ── Check 3: news_data has the expected structure ──────────────────────────
    # News absence is a WARNING, not an abort — the LLM can still classify
    # regime without news; it will be more conservative.
    if news_data is not None:
        if not isinstance(news_data.get("all_headlines"), list):
            failures.append(
                "news_data.all_headlines is missing or not a list"
            )
        else:
            passed += 1

    # ── Check 4: Staleness (only when _snapshot_ts is supplied) ───────────────
    snapshot_ts = snapshot.get("_snapshot_ts")
    if snapshot_ts is not None:
        age_minutes = (time.time() - float(snapshot_ts)) / 60.0
        if age_minutes > max_staleness_minutes:
            failures.append(
                f"Snapshot timestamp is stale: {age_minutes:.1f} min since fetch "
                f"(limit={max_staleness_minutes} min)"
            )
        else:
            passed += 1

    if failures:
        return ValidationResult(
            ok=False,
            reason=failures[0],
            checks_passed=passed,
            checks_failed=len(failures),
        )
    return ValidationResult(
        ok=True,
        reason="",
        checks_passed=passed,
        checks_failed=0,
    )
