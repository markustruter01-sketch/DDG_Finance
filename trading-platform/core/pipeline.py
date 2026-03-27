"""
Trading Pipeline — 15-Minute Cycle (Full Market + Crypto-Only)
----------------------------------------------------------------
Orchestrates a complete analysis + execution cycle every 15 minutes:

  Full Market mode (stock market hours):
    1. Execution lock    — skip if a previous cycle is still running.
    2. Kill switch guard — abort if already tripped today.
    3. Market clock guard — abort if market is closed (unless forced).
    4. Analysis cycle    — RAG → data fetch (cached FRED/News) → Groq → Kelly.
    5. Execution cycle   — close stale → size → place orders → journal.

  Crypto-Only mode (off-hours, 24/7):
    1. Execution lock    — skip if a previous cycle is still running.
    2. Kill switch guard — abort if already tripped today.
    3. Analysis cycle    — RAG → crypto data + news → Groq → Kelly (6 slots).
    4. Execution cycle   — close stale crypto → size → place orders → journal.

This module is called by the APScheduler jobs AND by the manual
POST /run API endpoint.  All results are stored in _last_run so the
GET /status endpoint can expose them without re-running.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Union

from loguru import logger

from analysis.analyzer import run_analysis_cycle
from analysis.schemas import RegimeAnalysisOutput, CryptoAnalysisOutput
from analysis.post_mortem import run_post_mortem
from execution.executor import execute_allocations
from execution.kill_switch import check as ks_check, is_tripped, reset as ks_reset
from core.market_clock import is_market_open


_pipeline_lock = asyncio.Lock()

_state: dict[str, Any] = {
    "last_run_utc":     None,
    "last_run_status":  "never_run",
    "last_allocation":  None,
    "last_exec_result": None,
    "run_count":        0,
    "error_count":      0,
    "cycle_interval":   "15min",
    "trading_mode":     "idle",
}


def get_last_run() -> dict:
    return dict(_state)


async def run_pipeline(
    *,
    force: bool = False,
    dry_run: bool = False,
    crypto_only: bool = False,
) -> dict[str, Any]:
    if _pipeline_lock.locked():
        logger.warning("Pipeline lock held — skipping this cycle (previous still running)")
        return {
            "status": "skipped_locked",
            "errors": ["Previous cycle still running"],
            "run_count": _state["run_count"],
        }

    async with _pipeline_lock:
        return await _run_pipeline_inner(force=force, dry_run=dry_run, crypto_only=crypto_only)


async def _run_pipeline_inner(
    *,
    force: bool = False,
    dry_run: bool = False,
    crypto_only: bool = False,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    cycle_num = _state["run_count"] + 1
    mode_label = "CRYPTO-ONLY" if crypto_only else "FULL MARKET"
    logger.info("=" * 60)
    logger.info(f"PIPELINE CYCLE #{cycle_num} | mode={mode_label} force={force} dry_run={dry_run}")
    logger.info("=" * 60)

    result: dict[str, Any] = {
        "started_utc": started.isoformat(),
        "dry_run":     dry_run,
        "crypto_only": crypto_only,
        "status":      "ok",
        "errors":      [],
    }

    if is_tripped():
        msg = "Kill switch is tripped — pipeline aborted for today"
        logger.warning(msg)
        result["status"] = "kill_switch_tripped"
        result["errors"].append(msg)
        _update_state(result, started, trading_mode="kill_switch")
        return result

    if not crypto_only and not force and not is_market_open():
        msg = "Market is closed — pipeline skipped (use force=True to override)"
        logger.info(msg)
        result["status"] = "market_closed"
        result["errors"].append(msg)
        _update_state(result, started)
        return result

    allocation: Union[RegimeAnalysisOutput, CryptoAnalysisOutput, None] = None
    try:
        logger.info("Pipeline | Step 1: Running analysis cycle...")
        allocation = await run_analysis_cycle(dry_run=dry_run, crypto_only=crypto_only)
        if isinstance(allocation, RegimeAnalysisOutput):
            result["market_regime"] = f"{allocation.regime}: {allocation.regime_rationale}"
        else:
            result["market_regime"] = allocation.market_regime
        result["allocation_summary"] = [
            {
                "slot":             a.slot,
                "ticker":           a.ticker,
                "asset_class":      a.asset_class,
                "conviction_score": a.conviction_score,
                "kelly_fraction":   a.kelly_fraction,
                "stop_loss_pct":    a.stop_loss_pct,
                "take_profit_pct":  a.take_profit_pct,
                "thesis":           a.thesis,
            }
            for a in sorted(allocation.allocations, key=lambda x: x.slot)
        ]
    except Exception as exc:
        logger.error(f"Pipeline | Analysis cycle FAILED: {exc}")
        result["status"] = "analysis_failed"
        result["errors"].append(f"Analysis failed: {exc}")
        _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
        return result

    if ks_check():
        msg = "Kill switch tripped mid-pipeline — execution aborted"
        logger.warning(msg)
        result["status"] = "kill_switch_tripped"
        result["errors"].append(msg)
        _update_state(result, started, trading_mode="kill_switch")
        return result

    try:
        logger.info("Pipeline | Step 2: Executing allocations...")
        exec_result = execute_allocations(allocation, dry_run=dry_run)
        result["execution"] = {
            "placed":  len(exec_result["placed"]),
            "closed":  len(exec_result["closed"]),
            "skipped": len(exec_result["skipped"]),
            "errors":  len(exec_result["errors"]),
            "equity":  exec_result["equity"],
            "details": exec_result,
        }
        if exec_result["errors"]:
            result["errors"].extend(
                [f"Execution error: {e}" for e in exec_result["errors"]]
            )
    except Exception as exc:
        logger.error(f"Pipeline | Execution FAILED: {exc}")
        result["status"] = "execution_failed"
        result["errors"].append(f"Execution failed: {exc}")
        _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
        return result

    result["status"] = "ok" if not result["errors"] else "ok_with_errors"
    _update_state(result, started, allocation, trading_mode=mode_label.lower().replace(" ", "_"))

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(f"PIPELINE COMPLETE in {elapsed:.1f}s | status={result['status']} mode={mode_label}")
    return result


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


def _update_state(
    result: dict,
    started: datetime,
    allocation: Union[RegimeAnalysisOutput, CryptoAnalysisOutput, None] = None,
    trading_mode: str | None = None,
) -> None:
    _state["last_run_utc"]    = started.isoformat()
    _state["last_run_status"] = result["status"]
    _state["last_exec_result"] = result.get("execution")
    _state["run_count"]       += 1
    if trading_mode:
        _state["trading_mode"] = trading_mode
    if result["status"] not in ("ok", "ok_with_errors"):
        _state["error_count"] += 1
    if allocation:
        _state["last_allocation"] = result.get("allocation_summary")
