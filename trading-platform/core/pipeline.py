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

from analysis.analyzer import run_analysis_cycle, get_regime_fallback
from analysis.schemas import RegimeAnalysisOutput, CryptoAnalysisOutput
from db.postgres import insert_equity_snapshot
from analysis.post_mortem import run_post_mortem
from execution.executor import execute_allocations
from execution.kill_switch import (
    check as ks_check,
    is_tripped,
    reset as ks_reset,
    is_pending_liquidation,
    set_pending_liquidation,
)
from core.market_clock import is_market_open


_pipeline_lock = asyncio.Lock()

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
    from datetime import datetime, timezone
    _state["last_run_status"] = "restarted"
    _state["error_count"] = 0
    _state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    logger.info("Pipeline | Error state reset by operator — system resuming as 'online'")
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

    # ── Deferred emergency liquidation (set when market was closed at click-time) ──
    if is_pending_liquidation() and is_market_open():
        logger.critical(
            "Pipeline | PENDING LIQUIDATION detected — market is now open. "
            "Force-closing all non-vault positions before normal cycle."
        )
        try:
            from execution.broker import get_positions, close_position
            from config.settings import settings as _s
            VAULT = set(getattr(_s, "vault_tickers_protected", ["JEPQ"]))
            _positions = get_positions()
            _n_closed = 0
            for _pos in _positions:
                _sym = _pos["symbol"]
                if _sym in VAULT:
                    logger.info(f"Pipeline | Deferred liquidation: skipping vault {_sym}")
                    continue
                try:
                    close_position(_sym)
                    _n_closed += 1
                    logger.critical(f"Pipeline | Deferred liquidation: closed {_sym}")
                except Exception as _exc:
                    logger.error(f"Pipeline | Deferred liquidation: failed {_sym}: {_exc}")
            set_pending_liquidation(False)
            logger.critical(
                f"Pipeline | Deferred liquidation complete — {_n_closed} position(s) closed, "
                f"flag cleared."
            )
        except Exception as exc:
            logger.error(f"Pipeline | Deferred liquidation failed: {exc}")

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

    # ── Pre-dispatch Signal Guardrails (authoritative temporal gate) ──────────
    # We call run_all_guards() at this point so that:
    #   1) _last_guard_result is always written before any LLM work begins,
    #      keeping /status.signal_guard accurate even when the pipeline aborts.
    #   2) The temporal hard-block (Fri 14:00 ET → Mon 09:30 ET) is evaluated
    #      before we fetch expensive market/news data.
    #
    # NOTE: No real market_data or news_data are available at this stage, so
    # only the temporal guard (Guard 1) can meaningfully fire here.  The soft
    # guards (consensus, divergence) run a second time inside run_analysis_cycle
    # where they have the actual fetched data and do real filtering work.  This
    # pre-dispatch call is intentionally temporal-only: an empty context means
    # consensus/divergence guards see nothing to filter and pass trivially.
    #
    # For crypto_only=True the temporal guard is skipped inside run_all_guards
    # (crypto trades 24/7 through weekends and calendar events).
    if not force:
        try:
            from analysis.signal_guard import run_all_guards as _run_guards
            _guard_ctx: dict = {
                "news_data":      {"all_headlines": [], "by_category": {}},
                "market_data":    {},
                "sentiment_band": "Neutral",
                "crypto_only":    crypto_only,
            }
            _pre_guard = _run_guards(_guard_ctx)
            result["signal_guard"] = _pre_guard.to_dict()

            if _pre_guard.hard_block:
                _reason = next(
                    (r.reason for r in _pre_guard.results if not r.passed and r.severity == "hard"),
                    "temporal quarantine active",
                )
                # Temporal quarantine: prefer reusing last cached regime over
                # returning a hard error, so the dashboard still shows actionable
                # allocation data.  Only emit guardrail_blocked when no cache exists.
                try:
                    from analysis.analyzer import get_regime_fallback as _get_cached
                    _cached = _get_cached()
                except Exception:
                    _cached = None

                if _cached is not None:
                    logger.info(
                        f"SignalGuard | Temporal quarantine ({_reason}) — "
                        f"returning cached regime '{_cached.regime}' (LLM skipped)"
                    )
                    result["status"] = "completed"
                    result["signal_guard_note"] = f"quarantine active: {_reason} — cached regime used"
                    result["allocation"] = _cached.dict() if hasattr(_cached, "dict") else str(_cached)
                    _update_state(result, started)
                    return result

                msg = f"Signal guard hard block: {_reason} — no cached regime available"
                logger.info(msg)
                result["status"] = "guardrail_blocked"
                result["errors"].append(msg)
                _update_state(result, started)
                return result
        except Exception as _grd_exc:
            logger.warning(f"Pipeline | Pre-dispatch guard check failed (non-fatal): {_grd_exc}")

    try:
        from data.economic_calendar import is_blackout_active
        blackout = is_blackout_active()
        if blackout.get("active") and not force:
            msg = f"Economic blackout active: {blackout.get('event', 'unknown')} — pipeline skipped"
            logger.warning(msg)
            result["status"] = "blackout_active"
            result["errors"].append(msg)
            result["blackout"] = blackout
            _update_state(result, started)
            try:
                from notifications.discord import notify_blackout_active
                notify_blackout_active(blackout.get("event", ""), blackout.get("window_minutes", 30))
            except Exception:
                pass
            return result
    except Exception as exc:
        logger.warning(f"Pipeline | Blackout check failed: {exc} — continuing")

    allocation: Union[RegimeAnalysisOutput, CryptoAnalysisOutput, None] = None
    using_fallback = False
    try:
        logger.info("Pipeline | Step 1: Running analysis cycle...")
        allocation = await run_analysis_cycle(dry_run=dry_run, crypto_only=crypto_only)
    except Exception as exc:
        logger.error(f"Pipeline | Analysis cycle FAILED: {exc}")
        # ── Groq-specific fallback: only activate when the LLM retries themselves
        # exhausted (Groq rate-limited / 503 / token-limit).  Other failures such
        # as account-state unavailability, bad market data, or prompt-assembly
        # errors abort immediately as before — we must NOT trade on stale
        # allocations when the root cause is something other than Groq.
        #
        # Detection: _call_regime_with_retry raises:
        #   RuntimeError("Regime LLM failed after N attempts. Last error: ...")
        # Account-fetch raises:
        #   RuntimeError("Account state unavailable, analysis aborted: ...")
        # All other non-LLM failures use different messages / types.
        exc_msg = str(exc)

        # ── Data Circuit Breaker abort ────────────────────────────────────────
        # The market snapshot validator (shared/market_snapshot_validator.py)
        # raises RuntimeError("DataCircuitBreaker: ...") when the fetched data
        # has structural gaps or stale timestamps.  This is an explicit,
        # deliberate abort before any LLM tokens were consumed — handle it as
        # a first-class analysis failure with a descriptive error.
        if exc_msg.startswith("DataCircuitBreaker:"):
            result["status"] = "analysis_failed"
            result["errors"].append(f"Data integrity gate tripped: {exc}")
            logger.warning(
                f"Pipeline | DataCircuitBreaker tripped — cycle aborted "
                f"without LLM call. Reason: {exc_msg}"
            )
            _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
            return result

        is_llm_failure = (
            "Regime LLM failed after" in exc_msg
            or "Crypto LLM failed after" in exc_msg
        )
        if is_llm_failure and not crypto_only:
            # Attempt Groq regime fallback
            fallback = get_regime_fallback()
            if fallback is not None:
                using_fallback = True
                logger.warning(
                    f"Pipeline | Groq LLM exhausted — using CACHED regime '{fallback.regime}' as fallback. "
                    f"Execution will proceed with stale allocation. LLM error: {exc}"
                )
                allocation = fallback
                result["errors"].append(
                    f"Groq rate-limited ({exc.__class__.__name__}) — using cached regime '{fallback.regime}'"
                )
            else:
                # LLM failed AND no usable cache — abort
                result["status"] = "analysis_failed"
                result["errors"].append(f"Groq LLM failed, no fallback cache available: {exc}")
                _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
                return result
        else:
            # Non-LLM failure (account fetch, data fetch, etc.) — abort as before.
            # Do NOT silently trade on stale data when the root cause is unknown.
            result["status"] = "analysis_failed"
            result["errors"].append(f"Analysis failed: {exc}")
            _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
            return result

    # ── Build allocation summary (same path for fresh and fallback allocations) ──
    if isinstance(allocation, RegimeAnalysisOutput):
        stale_tag = " [STALE — cached]" if using_fallback else ""
        result["market_regime"] = f"{allocation.regime}{stale_tag}: {allocation.regime_rationale}"
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
    result["using_fallback_regime"] = using_fallback

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

    # ── Equity snapshot ─────────────────────────────────────────────────────
    # Write a time-series equity point to PostgreSQL for the equity curve chart.
    # Kraken equity is read from the bot's status.json; safe to be 0 if missing.
    try:
        import json as _j, pathlib as _pl
        _status_path = _pl.Path("../kraken-bot/status.json")
        kraken_equity = 0.0
        if _status_path.exists():
            _bot_state = _j.loads(_status_path.read_text())
            _ps = _bot_state.get("paper_summary") or {}
            kraken_equity = float(_ps.get("total_equity_usd", 0.0) or 0.0)
        alpaca_equity = float(exec_result.get("equity", 0.0) or 0.0)
        regime = _state.get("last_regime")
        insert_equity_snapshot(
            alpaca_equity=alpaca_equity,
            kraken_equity=kraken_equity,
            regime=regime,
            source="pipeline",
        )
    except Exception as _snap_exc:
        logger.warning(f"Pipeline | Equity snapshot write failed (non-fatal): {_snap_exc}")

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
    _state["last_run_utc"]        = started.isoformat()
    _state["last_run_status"]     = result["status"]
    _state["last_exec_result"]    = result.get("execution")
    _state["groq_using_fallback"] = result.get("using_fallback_regime", False)
    _state["run_count"]          += 1
    if trading_mode:
        _state["trading_mode"] = trading_mode
    if result["status"] not in ("ok", "ok_with_errors"):
        _state["error_count"] += 1
    if allocation:
        _state["last_allocation"] = result.get("allocation_summary")
        if isinstance(allocation, RegimeAnalysisOutput):
            _state["last_regime"] = allocation.regime
        else:
            _state["last_regime"] = "Crypto"

    # ── Stateful cycle memory ─────────────────────────────────────────────────
    # Record cycle outcome so CycleStateTracker can compute the confidence
    # multiplier for subsequent cycles.  Skip non-cycle exits (market closed,
    # guardrail blocks, kill-switch) so they don't pollute the quality signal.
    _CYCLE_OUTCOME_MAP = {
        "ok":               "success",
        "ok_with_errors":   "warning",
        "analysis_failed":  "failure",
        "execution_failed": "failure",
    }
    cycle_outcome = _CYCLE_OUTCOME_MAP.get(result["status"])
    if cycle_outcome:
        # Also degrade "success" to "warning" if the cycle used a cached fallback
        if cycle_outcome == "success" and result.get("using_fallback_regime"):
            cycle_outcome = "warning"
        try:
            from core.cycle_state import get_tracker as _get_tracker
            _get_tracker().record_outcome(cycle_outcome)
        except Exception as _cse:
            logger.debug(f"Pipeline | CycleStateTracker update failed (non-fatal): {_cse}")
