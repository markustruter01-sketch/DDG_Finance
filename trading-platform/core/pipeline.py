"""
Pipeline state (FLEET-V1-LIVE-SPEC.md section 5, 2 Nov 2026).

The retired LLM decision pipeline (regime analysis -> Kelly sizing -> order
execution, reachable through POST /run and the disabled intraday scheduler
job) has been removed. What remains is the read-only state the status
endpoints still report, the post-mortem reconciliation, and a symbol helper.
Trading is done only by the runner's registered sleeves (kraken-bot/runner.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from analysis.post_mortem import run_post_mortem


# Alpaca crypto position symbols (no slash) the retired after-hours cycle traded;
# kept so status endpoints can still label any such legacy position.
_AFTERHOURS_CRYPTO_SYMBOLS_NOSLASH: frozenset[str] = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD"})


def _is_alpaca_crypto_symbol(symbol: str) -> bool:
    """Return True if *symbol* is an Alpaca afterhours crypto position (e.g. BTCUSD)."""
    return symbol.upper() in _AFTERHOURS_CRYPTO_SYMBOLS_NOSLASH


_state: dict[str, Any] = {
    "last_run_utc":          None,
    "last_run_status":       "never_run",
    "last_allocation":       None,
    "last_regime":           None,
    "last_exec_result":      None,
    "run_count":             0,
    "error_count":           0,
    "cycle_interval":        "15min",
    "trading_mode":          "idle",
    "groq_using_fallback":   False,   # True when last cycle used stale cached regime
}


def get_last_run() -> dict:
    return dict(_state)


def reset_error_state() -> dict:
    """
    Clear the error/degraded state so the system reports 'online' again.
    Called by POST /system/restart.  Does NOT reset the kill switch.
    """
    _state["last_run_status"] = "restarted"
    _state["error_count"] = 0
    _state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    logger.info("Pipeline | Error state reset by operator — system resuming as 'online'")
    return dict(_state)


async def run_postmortem() -> dict:
    logger.info("Pipeline | Running post-mortem reconciliation...")
    try:
        summary = await run_post_mortem()
        updated = summary.get("wins", 0) + summary.get("losses", 0)
        result = {"status": "ok", "updated_count": updated, "detail": summary}
        logger.info(f"Post-mortem complete: {updated} trades reconciled")
        return result
    except Exception as exc:
        logger.error(f"Post-mortem failed: {exc}")
        return {"status": "error", "error": str(exc), "updated_count": 0}
