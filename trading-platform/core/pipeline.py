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
import sys
import os
from datetime import datetime, timezone
from typing import Any, Union

from loguru import logger

from analysis.analyzer import run_analysis_cycle, get_regime_fallback, emergency_regime_check
from analysis.schemas import RegimeAnalysisOutput, CryptoAnalysisOutput
from db.postgres import insert_equity_snapshot, get_kraken_equity
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


def _persist_emergency_regime(spy_override: bool, spy_change: float | None, cycle_num: int) -> None:
    """Write market_regime.json on early-exit paths to keep override state in sync.

    When spy_override is True: writes regime=Bear with override metadata.
    When spy_override is False: updates existing file to clear regime_override
    (prevents stale override=True from lingering after SPY recovers).
    """
    try:
        import json as _json
        from pathlib import Path as _Path
        from datetime import datetime as _dt, timezone as _tz

        _regime_path = _Path(__file__).parent.parent / "data" / "market_regime.json"
        _regime_path.parent.mkdir(parents=True, exist_ok=True)

        if spy_override:
            _payload = {
                "regime":         "Bear",
                "written_at":     _dt.now(_tz.utc).isoformat(),
                "cycle_number":   cycle_num,
                "using_fallback": False,
                "regime_override": True,
                "override_reason": f"SPY {spy_change * 100:+.1f}% intraday" if spy_change is not None else "SPY emergency",
            }
            if spy_change is not None:
                _payload["spy_change_pct"] = round(spy_change * 100, 2)
            _regime_path.write_text(_json.dumps(_payload, indent=2))
            logger.debug("Pipeline | market_regime.json written with emergency Bear override (early exit path)")
        elif _regime_path.exists():
            _existing = _json.loads(_regime_path.read_text())
            if _existing.get("regime_override"):
                _existing["regime_override"] = False
                _existing.pop("override_reason", None)
                _existing.pop("spy_change_pct", None)
                _existing["written_at"] = _dt.now(_tz.utc).isoformat()
                _existing["cycle_number"] = cycle_num
                _regime_path.write_text(_json.dumps(_existing, indent=2))
                logger.debug("Pipeline | market_regime.json: cleared stale regime_override (early exit path)")
    except Exception as _exc:
        logger.warning(f"Pipeline | emergency regime persist failed (non-fatal): {_exc}")

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

    # ── SPY emergency regime check (runs EVERY cycle, before any early return) ────
    spy_override = False
    spy_change = None
    if not crypto_only:
        try:
            spy_override, spy_change = emergency_regime_check()
            if spy_override:
                logger.warning(
                    f"Pipeline | SPY EMERGENCY active: SPY {spy_change * 100:+.1f}% — "
                    f"Bear override will be enforced on any allocation this cycle"
                )
        except Exception as _spy_exc:
            logger.warning(f"Pipeline | SPY emergency check failed (non-fatal): {_spy_exc}")

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
        _persist_emergency_regime(spy_override, spy_change, cycle_num)
        _update_state(result, started, trading_mode="kill_switch")
        return result

    if not crypto_only and not force and not is_market_open():
        msg = "Market is closed — pipeline skipped (use force=True to override)"
        logger.info(msg)
        result["status"] = "market_closed"
        result["errors"].append(msg)
        _persist_emergency_regime(spy_override, spy_change, cycle_num)
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
                    _persist_emergency_regime(spy_override, spy_change, cycle_num)
                    _update_state(result, started)
                    return result

                msg = f"Signal guard hard block: {_reason} — no cached regime available"
                logger.info(msg)
                result["status"] = "guardrail_blocked"
                result["errors"].append(msg)
                _persist_emergency_regime(spy_override, spy_change, cycle_num)
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
            _persist_emergency_regime(spy_override, spy_change, cycle_num)
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

    _regime_bias_used = False
    if not crypto_only and not dry_run:
        try:
            from analysis.regime_bias_manager import get_cached_bias
            _bias = get_cached_bias()
            if _bias is not None:
                logger.info(
                    f"Pipeline | Async regime bias available: regime={_bias['regime']} "
                    f"(age={_bias.get('age_hours', '?')}h) — skipping synchronous LLM call"
                )
                _regime_bias_used = True
                result["regime_bias_age_hours"] = _bias.get("age_hours")
        except ImportError:
            pass

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
        # raises DataCircuitBreakerError when fetched data has structural gaps
        # or stale timestamps.  This is a deliberate, pre-LLM abort — handle it
        # as a first-class analysis failure with a descriptive error message.
        try:
            _shared_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
            if _shared_root not in sys.path:
                sys.path.insert(0, _shared_root)
            from shared.market_snapshot_validator import DataCircuitBreakerError as _DCBError
            _is_dcb = isinstance(exc, _DCBError)
        except ImportError:
            _is_dcb = "DataCircuitBreaker" in exc_msg

        if _is_dcb:
            result["status"] = "analysis_failed"
            result["errors"].append(f"Data integrity gate tripped: {exc}")
            logger.warning(
                f"Pipeline | DataCircuitBreaker tripped — cycle aborted "
                f"without LLM call. Reason: {exc}"
            )
            _persist_emergency_regime(spy_override, spy_change, cycle_num)
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
                result["status"] = "analysis_failed"
                result["errors"].append(f"Groq LLM failed, no fallback cache available: {exc}")
                _persist_emergency_regime(spy_override, spy_change, cycle_num)
                _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
                return result
        else:
            result["status"] = "analysis_failed"
            result["errors"].append(f"Analysis failed: {exc}")
            _persist_emergency_regime(spy_override, spy_change, cycle_num)
            _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
            return result

    # ── SPY emergency regime override (apply to the resolved allocation) ─────
    if spy_override and allocation is not None and isinstance(allocation, RegimeAnalysisOutput):
        if allocation.regime != "Bear":
            logger.warning(
                f"Pipeline | EMERGENCY OVERRIDE: SPY {spy_change * 100:+.1f}% — "
                f"forcing regime from '{allocation.regime}' to 'Bear'"
            )
            allocation.regime = "Bear"
            allocation.regime_rationale = (
                f"EMERGENCY OVERRIDE: SPY {spy_change * 100:+.1f}% intraday drop. "
                f"Original regime overridden to Bear."
            )
            result["errors"].append(
                f"SPY emergency override active (SPY {spy_change * 100:+.1f}%) — forced Bear regime"
            )

    # ── ALGORITHMIC SIGNAL GENERATION (equity cycles only) ────────────────────
    # The LLM provides regime classification and oversight/veto.
    # The algo scanner generates the actual trade entries/allocations.
    # Crypto-only cycles still use the LLM's allocations directly (CryptoAnalysisOutput).
    if isinstance(allocation, RegimeAnalysisOutput):
        try:
            from execution.algo_scanner import run_algo_scan
            from core.veto_enforcer import load_active_vetoes

            _llm_regime = allocation.regime
            _llm_rationale = allocation.regime_rationale

            _veto_tickers = set(load_active_vetoes())

            _vix_val = None
            try:
                import json as _vj
                from pathlib import Path as _vp
                _regime_file = _vp(__file__).parent.parent / "data" / "market_regime.json"
                if _regime_file.exists():
                    _rd = _vj.loads(_regime_file.read_text())
                    _vix_val = _rd.get("vix")
            except Exception:
                pass

            _algo_result = run_algo_scan(
                regime=_llm_regime,
                vix=_vix_val,
                veto_tickers=_veto_tickers if _veto_tickers else None,
            )
            result["algo_scanner"] = {
                "scan_type": _algo_result["scan_type"],
                "active_signals": _algo_result.get("active_signals", 0),
                "activated": _algo_result["activated"],
            }

            _algo_signals = _algo_result["signals"]
            if _algo_signals:
                from analysis.schemas import RegimeAllocationSlot
                _new_allocs = []
                for s in _algo_signals:
                    _new_allocs.append(RegimeAllocationSlot.model_validate(s))
                allocation.allocations = _new_allocs
                logger.info(
                    f"Pipeline | Algo scanner replaced LLM allocations: "
                    f"{len(_new_allocs)} slots (regime={_llm_regime}, "
                    f"scan={_algo_result['scan_type']})"
                )
        except Exception as _algo_exc:
            logger.warning(
                f"Pipeline | Algo scanner failed (non-fatal), "
                f"falling back to LLM allocations: {_algo_exc}"
            )
            result.setdefault("errors", []).append(f"Algo scanner error: {_algo_exc}")
            if allocation.regime == "Bear":
                try:
                    from portfolio.allocator import (
                        _apply_bear_half_kelly,
                        _apply_bear_sgov_default,
                        normalise_kelly_fractions,
                    )
                    from analysis.schemas import RegimeAllocationSlot as _FallbackSlot
                    _raw = [a.dict() if hasattr(a, "dict") else a.model_dump() for a in allocation.allocations]
                    _raw = _apply_bear_half_kelly(_raw)
                    _raw = _apply_bear_sgov_default(_raw)
                    _raw = normalise_kelly_fractions(_raw)
                    allocation.allocations = [_FallbackSlot.model_validate(s) for s in _raw]
                    logger.info("Pipeline | Bear defensive controls applied to LLM fallback allocations")
                except Exception as _def_exc:
                    logger.warning(f"Pipeline | Bear defensive fallback also failed: {_def_exc}")

    # ── Build allocation summary (same path for fresh and fallback allocations) ──
    if isinstance(allocation, RegimeAnalysisOutput):
        stale_tag = " [STALE — cached]" if using_fallback else ""
        override_tag = " [EMERGENCY OVERRIDE]" if spy_override else ""
        result["market_regime"] = f"{allocation.regime}{stale_tag}{override_tag}: {allocation.regime_rationale}"
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
        _persist_emergency_regime(spy_override, spy_change, cycle_num)
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
        _persist_emergency_regime(spy_override, spy_change, cycle_num)
        _update_state(result, started, trading_mode=mode_label.lower().replace(" ", "_"))
        return result

    result["status"] = "ok" if not result["errors"] else "ok_with_errors"
    _update_state(result, started, allocation, trading_mode=mode_label.lower().replace(" ", "_"))

    # ── 3× Inverse ETF 5-Day Time Exit ───────────────────────────────────────
    # Force-exit SPXS/SQQQ/SRTY positions held >= 5 trading days before
    # the short scanner runs (avoids interference).
    try:
        from analysis.hardcoded_exits import check_time_exits as _check_time_exits
        from execution.broker import get_positions as _gpos
        _all_positions = _gpos()
        _time_exits = _check_time_exits(_all_positions, dry_run=dry_run)
        if _time_exits:
            result.setdefault("time_exits", []).extend(_time_exits)
            logger.warning(f"Pipeline | 5-day time exits fired: {_time_exits}")
    except Exception as _te_exc:
        logger.warning(f"Pipeline | Time-exit check failed (non-fatal): {_te_exc}")

    # ── Algorithmic Short Scanner ─────────────────────────────────────────────
    # Runs after execute_allocations. Only active in Bear/RISK-OFF regime.
    # Non-fatal: existing positions and LLM allocations are unaffected if scanner fails.
    if not crypto_only:
        try:
            from execution.short_scanner import run_scan as _run_short_scan
            _regime_for_scan = (
                allocation.regime
                if isinstance(allocation, RegimeAnalysisOutput)
                else "Crypto"
            )
            _scan_result = _run_short_scan(
                regime=_regime_for_scan,
                allocation=allocation if isinstance(allocation, RegimeAnalysisOutput) else None,
                dry_run=dry_run,
            )
            result["short_scanner"] = _scan_result
            if _scan_result.get("activated"):
                logger.info(
                    f"Pipeline | Short scanner: "
                    f"entries={len(_scan_result.get('entries', []))} "
                    f"exits={len(_scan_result.get('exits', []))} "
                    f"exposure={_scan_result.get('short_exposure_pct', 0):.1f}%"
                )
        except Exception as _ss_exc:
            logger.warning(f"Pipeline | Short scanner failed (non-fatal): {_ss_exc}")
            result.setdefault("errors", []).append(f"Short scanner error: {_ss_exc}")

    # ── Regime Sync File ──────────────────────────────────────────────────────
    # Write market_regime.json so the Kraken bot and short scanner can read
    # the current EQUITY regime.  Crypto-only cycles must NOT overwrite this
    # file — they would clobber the equity regime label ("Bear"/"Bull") with
    # "Crypto", which disables the short scanner and algo scanner.
    if allocation is not None and isinstance(allocation, RegimeAnalysisOutput):
        try:
            import json as _json
            from pathlib import Path as _Path
            from datetime import datetime as _dt, timezone as _tz

            _regime_str = allocation.regime
            _regime_path = _Path(__file__).parent.parent / "data" / "market_regime.json"
            _regime_path.parent.mkdir(parents=True, exist_ok=True)
            _regime_payload = {
                "regime":       _regime_str,
                "written_at":   _dt.now(_tz.utc).isoformat(),
                "cycle_number": _state["run_count"],
                "using_fallback": using_fallback,
                "regime_override": spy_override,
                "rationale": (
                    allocation.regime_rationale
                    if not using_fallback
                    else None
                ),
            }
            if spy_override and spy_change is not None:
                _regime_payload["override_reason"] = f"SPY {spy_change * 100:+.1f}% intraday"
                _regime_payload["spy_change_pct"] = round(spy_change * 100, 2)
            try:
                from data.fred_client import fetch_macro_data as _fetch_macro_vix
                _vix_data = await _fetch_macro_vix(lookback_days=5)
                _vix_entry = _vix_data.get("VIXCLS", {})
                _vix_val = _vix_entry.get("value")
                if _vix_val is not None:
                    _regime_payload["vix"] = round(float(_vix_val), 2)
            except Exception:
                pass
            _regime_path.write_text(_json.dumps(_regime_payload, indent=2))
            logger.debug(
                f"Pipeline | market_regime.json written: regime='{_regime_str}' "
                f"(Kraken bot will read on next cycle)"
            )
        except Exception as _rw_exc:
            logger.warning(f"Pipeline | market_regime.json write failed (non-fatal): {_rw_exc}")

    # ── Stage 3: Correlation Matrix & Independent Crypto Regime ──────────
    try:
        from analysis.correlation_matrix import (
            compute_correlation_matrix,
            get_equity_crypto_correlation,
        )
        _corr_state = compute_correlation_matrix()
        _eq_crypto_corr = get_equity_crypto_correlation()
        logger.debug(
            f"Pipeline | Correlation matrix updated — "
            f"max={_corr_state.get('max_correlation')} "
            f"shock={_corr_state.get('systemic_shock')} "
            f"eq_crypto_corr={_eq_crypto_corr:.3f}"
        )
    except Exception as _corr_exc:
        logger.warning(f"Pipeline | Correlation matrix failed (non-fatal): {_corr_exc}")
        _eq_crypto_corr = 0.0

    try:
        from analysis.crypto_regime import classify_crypto_regime
        _crypto_regime = classify_crypto_regime(
            correlation_with_equity=_eq_crypto_corr,
        )
        logger.debug(
            f"Pipeline | Crypto regime: {_crypto_regime.get('crypto_regime')} "
            f"(score={_crypto_regime.get('score')}, contagion={_crypto_regime.get('equity_contagion')})"
        )
    except Exception as _cr_exc:
        logger.warning(f"Pipeline | Crypto regime classification failed (non-fatal): {_cr_exc}")

    # ── Equity snapshot ─────────────────────────────────────────────────────
    # Write a time-series equity point to PostgreSQL for the equity curve chart.
    # Kraken equity is read from the authoritative kraken_heartbeat DB table.
    try:
        kraken_equity = get_kraken_equity()
        alpaca_equity = float(exec_result.get("equity", 0.0) or 0.0)
        regime = _state.get("last_regime")
        options_eq = 0.0
        try:
            import importlib as _il_snap
            _opts_snap = _il_snap.import_module("options_engine")
            _opts_st = _opts_snap.get_state()
            options_eq = float(_opts_st.get("paper_equity", 0))
        except Exception:
            pass
        forex_eq = 0.0
        try:
            from routes._deps import _get_forex_engine as _gfx_snap
            _fx_snap = _gfx_snap()
            if _fx_snap:
                forex_eq = float(_fx_snap.get_state().get("paper_equity", 0))
        except Exception:
            pass
        insert_equity_snapshot(
            alpaca_equity=alpaca_equity,
            kraken_equity=kraken_equity,
            regime=regime,
            source="pipeline",
            options_equity=options_eq,
            forex_equity=forex_eq,
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
