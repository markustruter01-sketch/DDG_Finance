"""
Regime Bias Manager — Async Background LLM Task (Stage 2)
==========================================================
Decouples the Groq LLM from the execution-critical pipeline.

Architecture:
  - A background thread runs Groq analysis on a configurable schedule
    (default: every 4 hours during market hours, daily off-hours).
  - The bias is persisted to disk as a timestamped JSON file.
  - The main pipeline reads the cached bias for instant execution
    decisions — zero LLM latency in the hot path.
  - If bias is stale (> MAX_BIAS_AGE_HOURS), pipeline falls back to
    the deterministic regime from market data signals only.

This eliminates the 2-8 second Groq latency from every 15-minute cycle,
reducing the execution loop to pure deterministic math.
"""

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

BIAS_FILE = Path(__file__).parent.parent / "data" / "regime_bias.json"
BIAS_FILE.parent.mkdir(parents=True, exist_ok=True)

MAX_BIAS_AGE_HOURS = 6.0
REFRESH_INTERVAL_HOURS = 4.0

_bias_lock = threading.Lock()
_cached_bias: Optional[dict] = None
_refresh_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def get_cached_bias() -> Optional[dict]:
    """
    Read the latest regime bias without calling the LLM.

    Returns:
        Dict with keys: regime, regime_rationale, generated_at, age_hours.
        None if no bias is cached or bias is stale (> MAX_BIAS_AGE_HOURS).
    """
    global _cached_bias

    with _bias_lock:
        if _cached_bias is not None:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(_cached_bias["generated_at"])).total_seconds() / 3600
            if age <= MAX_BIAS_AGE_HOURS:
                return {**_cached_bias, "age_hours": round(age, 2)}
            logger.info(f"RegimeBias | Cached bias is stale ({age:.1f}h > {MAX_BIAS_AGE_HOURS}h)")
            return None

    if BIAS_FILE.exists():
        try:
            raw = json.loads(BIAS_FILE.read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(raw["generated_at"])).total_seconds() / 3600
            if age <= MAX_BIAS_AGE_HOURS:
                with _bias_lock:
                    _cached_bias = raw
                return {**raw, "age_hours": round(age, 2)}
            logger.info(f"RegimeBias | Disk bias is stale ({age:.1f}h > {MAX_BIAS_AGE_HOURS}h)")
        except Exception as exc:
            logger.warning(f"RegimeBias | Could not read bias file: {exc}")

    return None


def save_bias(regime: str, rationale: str, allocation_hint: Optional[dict] = None) -> None:
    """
    Persist a new regime bias from a completed LLM analysis.
    Called after successful Groq analysis in the background thread.
    """
    global _cached_bias
    payload = {
        "regime": regime,
        "regime_rationale": rationale,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allocation_hint": allocation_hint,
    }
    with _bias_lock:
        _cached_bias = payload
    try:
        BIAS_FILE.write_text(json.dumps(payload, indent=2))
        logger.info(f"RegimeBias | Saved new bias: regime={regime}")
    except Exception as exc:
        logger.warning(f"RegimeBias | Failed to write bias file: {exc}")


def _run_bias_refresh() -> None:
    """
    Background thread: periodically call Groq for regime analysis.
    Runs independently of the execution pipeline.
    """
    logger.info("RegimeBias | Background refresh thread started")
    while not _stop_event.is_set():
        try:
            logger.info("RegimeBias | Starting async LLM regime analysis...")
            _do_llm_analysis()
        except Exception as exc:
            logger.error(f"RegimeBias | Background analysis failed: {exc}")

        wait_seconds = REFRESH_INTERVAL_HOURS * 3600
        _stop_event.wait(timeout=wait_seconds)

    logger.info("RegimeBias | Background refresh thread stopped")


def _do_llm_analysis() -> None:
    """
    Execute a full Groq regime analysis in the background thread.
    This is the expensive operation that no longer blocks the execution pipeline.
    """
    try:
        from analysis.analyzer import run_analysis_cycle
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            output = loop.run_until_complete(run_analysis_cycle(dry_run=False, crypto_only=False))
            regime = getattr(output, "regime", "Sideways")
            rationale = getattr(output, "regime_rationale", "")
            allocs = None
            if hasattr(output, "allocations"):
                allocs = [
                    {
                        "ticker": a.ticker,
                        "asset_class": a.asset_class,
                        "kelly_fraction": a.kelly_fraction,
                        "conviction_score": a.conviction_score,
                    }
                    for a in output.allocations
                ]
            save_bias(regime, rationale, allocs)
        finally:
            loop.close()

    except Exception as exc:
        logger.error(f"RegimeBias | LLM analysis error: {exc}")
        raise


def start_background_refresh() -> None:
    """Start the background regime bias refresh thread."""
    global _refresh_thread
    if _refresh_thread is not None and _refresh_thread.is_alive():
        logger.info("RegimeBias | Refresh thread already running")
        return

    _stop_event.clear()
    _refresh_thread = threading.Thread(target=_run_bias_refresh, daemon=True, name="regime-bias-refresh")
    _refresh_thread.start()
    logger.info("RegimeBias | Background refresh thread launched")


def stop_background_refresh() -> None:
    """Stop the background refresh thread."""
    _stop_event.set()
    if _refresh_thread is not None:
        _refresh_thread.join(timeout=10)
    logger.info("RegimeBias | Background refresh stopped")
