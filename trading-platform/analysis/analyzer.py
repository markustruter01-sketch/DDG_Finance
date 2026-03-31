"""
Intraday Analysis Cycle — Regime-Switching Architecture
---------------------------------------------------------
v4.0 — Dynamic Regime-Switching & Adaptive Allocation

Called every market session (or 15-min for crypto off-hours):

  Full Market (Regime) mode:
    1. Query Alpaca for account state (buying power + positions).
    2. Run RAG feedback injection (recent wins, losses, slippage).
    3. Fetch 6-month data: FRED macro (cached 1hr) + Alpaca market prices
       (fresh, includes 3mo/6mo MA signals) + NewsAPI (cached 1hr).
    4. Assemble system prompt + user prompt with momentum signals.
    5. Call Groq (llama-3.3-70b-versatile) for regime-switching JSON.
    6. Validate with Pydantic (RegimeAnalysisOutput).
    7. Apply even-weighting override and normalise Kelly fractions.
    8. Return final RegimeAnalysisOutput.

  Crypto-Only mode (off-hours):
    Same pipeline with crypto-only universe: BTC/USD, ETH/USD, ATOM/USD.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Union

from loguru import logger

from analysis.feedback_injection import build_system_prompt_with_feedback
from analysis.groq_client import build_user_prompt, call_groq
from analysis.schemas import RegimeAnalysisOutput, CryptoAnalysisOutput
from data.cache import fred_cache, news_cache
from data.fred_client import fetch_macro_data
from data.news_client import fetch_news
from data.yfinance_client import fetch_market_data
from portfolio.allocator import process_regime_llm_output, process_crypto_llm_output


# ══════════════════════════════════════════════════════════════════════════════
# GROQ REGIME FALLBACK CACHE
# Persists the last successful regime analysis to disk so the pipeline can
# continue operating when Groq is rate-limited (100k TPD shared budget).
# ══════════════════════════════════════════════════════════════════════════════

_REGIME_CACHE_FILE = Path(__file__).parent.parent / "data" / "last_regime_cache.json"
# Max age is loaded from settings so it can be tuned via env var without code edits.
# Default: 4 hours (see config/settings.py: regime_fallback_max_age_hours).
from config.settings import settings as _settings
REGIME_FALLBACK_MAX_AGE_SECONDS = int(_settings.regime_fallback_max_age_hours * 3600)

# In-memory cache dict: {"regime": str, "saved_at": float, "output": {...}}
_last_regime_cache: dict | None = None
_last_crypto_cache: dict | None = None


def _load_regime_cache() -> None:
    """Load the persisted regime cache from disk on startup."""
    global _last_regime_cache
    if _REGIME_CACHE_FILE.exists():
        try:
            raw = json.loads(_REGIME_CACHE_FILE.read_text())
            _last_regime_cache = raw
            age_min = (time.time() - raw.get("saved_at", 0)) / 60
            logger.info(
                f"Regime cache | Loaded from disk — regime={raw.get('regime', '?')} "
                f"saved {age_min:.0f}min ago"
            )
        except Exception as exc:
            logger.warning(f"Regime cache | Failed to load from disk: {exc}")


def _save_crypto_cache(output: "CryptoAnalysisOutput") -> None:
    """Save the last successful crypto LLM output in-memory for budget throttle fallback."""
    global _last_crypto_cache
    _last_crypto_cache = {
        "saved_at": time.time(),
        "output": output.model_dump(),
    }
    logger.info("Crypto cache | Updated in-memory (budget throttle fallback)")


def get_crypto_fallback() -> "CryptoAnalysisOutput | None":
    """Return the cached CryptoAnalysisOutput if available and not stale."""
    if _last_crypto_cache is None:
        return None
    age = time.time() - _last_crypto_cache.get("saved_at", 0)
    if age > REGIME_FALLBACK_MAX_AGE_SECONDS:
        logger.warning(
            f"Crypto cache | Too stale ({age / 3600:.1f}h > "
            f"{_settings.regime_fallback_max_age_hours}h) — will not use as fallback"
        )
        return None
    try:
        from analysis.schemas import CryptoAnalysisOutput
        return CryptoAnalysisOutput.model_validate(_last_crypto_cache["output"])
    except Exception as exc:
        logger.warning(f"Crypto cache | Failed to deserialise: {exc}")
        return None


def _save_regime_cache(output: RegimeAnalysisOutput) -> None:
    """Atomically save a successful regime analysis to disk."""
    global _last_regime_cache
    try:
        _REGIME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "regime":   output.regime,
            "saved_at": time.time(),
            "output":   output.model_dump(),
        }
        tmp = str(_REGIME_CACHE_FILE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cache_data, f, indent=2)
        os.replace(tmp, str(_REGIME_CACHE_FILE))
        _last_regime_cache = cache_data
        logger.info(f"Regime cache | Saved to disk (regime={output.regime})")
    except Exception as exc:
        logger.warning(f"Regime cache | Failed to save to disk: {exc}")


def get_regime_fallback() -> RegimeAnalysisOutput | None:
    """
    Return the last-good regime as a RegimeAnalysisOutput if the cache is fresh
    enough (< REGIME_FALLBACK_MAX_AGE_SECONDS), else return None.

    Called by pipeline.py when run_analysis_cycle() raises (Groq rate-limited).
    """
    if _last_regime_cache is None:
        return None
    age = time.time() - _last_regime_cache.get("saved_at", 0)
    if age > REGIME_FALLBACK_MAX_AGE_SECONDS:
        logger.warning(
            f"Regime cache | Cache is stale ({age / 3600:.1f}h > "
            f"{REGIME_FALLBACK_MAX_AGE_SECONDS / 3600:.0f}h limit) — rejecting fallback"
        )
        return None
    try:
        output = RegimeAnalysisOutput.model_validate(_last_regime_cache["output"])
        return output
    except Exception as exc:
        logger.warning(f"Regime cache | Cannot reconstruct RegimeAnalysisOutput: {exc}")
        return None


def get_groq_status() -> dict:
    """
    Return a status dict for the /status endpoint.
    Shows when the last successful Groq call happened and whether the cache is usable.
    """
    if _last_regime_cache is None:
        return {
            "last_success_at": None,
            "cache_age_min":   None,
            "cache_valid":     False,
            "regime":          None,
        }
    age_s = time.time() - _last_regime_cache.get("saved_at", 0)
    from datetime import datetime, timezone
    saved_at_ts = _last_regime_cache.get("saved_at", 0)
    last_success_at = datetime.fromtimestamp(saved_at_ts, tz=timezone.utc).isoformat()
    return {
        "last_success_at": last_success_at,
        "cache_age_min":   round(age_s / 60, 1),
        "cache_valid":     age_s < REGIME_FALLBACK_MAX_AGE_SECONDS,
        "regime":          _last_regime_cache.get("regime"),
    }


# Load the persisted cache on module import so it's ready before the first cycle
_load_regime_cache()


def _fetch_account_state() -> dict[str, Any]:
    from execution.broker import get_account, get_positions
    acct = get_account()
    positions = get_positions()
    held_symbols = [p["symbol"] for p in positions]
    state = {
        "buying_power": acct["buying_power"],
        "equity":       acct["equity"],
        "cash":         acct["cash"],
        "held_symbols": held_symbols,
        "held_values":  {p["symbol"]: p["market_value"] for p in positions},
    }
    logger.info(
        f"Account state | equity=${state['equity']:,.2f} "
        f"buying_power=${state['buying_power']:,.2f} "
        f"held={held_symbols or 'none'}"
    )
    return state


async def run_analysis_cycle(
    lookback_days_macro: int = 90,
    market_period: str = "1y",
    news_lookback_days: int = 3,
    n_loss_feedback: int = 5,
    dry_run: bool = False,
    crypto_only: bool = False,
) -> Union[RegimeAnalysisOutput, CryptoAnalysisOutput]:
    mode_label = "CRYPTO-ONLY" if crypto_only else "REGIME-SWITCHING FULL MARKET"
    logger.info("=" * 60)
    logger.info(f"ANALYSIS CYCLE STARTING ({mode_label})")
    logger.info("=" * 60)

    logger.info("Step 1/5 | Querying Alpaca for account state (buying power + positions)...")
    loop = asyncio.get_event_loop()
    try:
        account_state = await loop.run_in_executor(None, _fetch_account_state)
    except Exception as exc:
        logger.error(f"ABORTING analysis — cannot fetch account state: {exc}")
        raise RuntimeError(f"Account state unavailable, analysis aborted: {exc}") from exc

    _snapshot_fetch_ts = time.time()   # timestamp of when the data fetch began (used by Data Circuit Breaker staleness check)

    if crypto_only:
        logger.info("Step 2/5 | Fetching data (Crypto 6mo + MA signals | News cached 1hr)...")
        market_data, news_data = await asyncio.gather(
            fetch_market_data(period=market_period, crypto_only=True),
            news_cache.get_or_fetch(fetch_news, lookback_days=news_lookback_days),
        )
        macro_data = {}
    else:
        logger.info("Step 2/5 | Fetching data (FRED cached 1hr | Market 6mo + MA signals | News cached 1hr)...")
        macro_data, market_data, news_data = await asyncio.gather(
            fred_cache.get_or_fetch(fetch_macro_data, lookback_days=lookback_days_macro),
            fetch_market_data(period=market_period),
            news_cache.get_or_fetch(fetch_news, lookback_days=news_lookback_days),
        )

    if crypto_only:
        market_ok = sum(1 for v in market_data["by_ticker"].values() if "error" not in v)
        news_ok   = len(news_data["all_headlines"])
        logger.info(f"  Data snapshot: Crypto={market_ok}/2 tickers | News={news_ok} headlines")
    else:
        macro_ok  = sum(1 for v in macro_data.values() if v.get("value") is not None)
        market_ok = sum(1 for v in market_data["by_ticker"].values() if "error" not in v)
        news_ok   = len(news_data["all_headlines"])
        logger.info(
            f"  Data snapshot: FRED={macro_ok}/10 | "
            f"Market={market_ok}/{len(market_data['by_ticker'])} tickers | "
            f"News={news_ok} headlines"
        )

    # ── Data Circuit Breaker ──────────────────────────────────────────────────
    # Validate structural integrity of the freshly-fetched snapshot BEFORE
    # spending any LLM tokens.  A failed validation aborts the cycle with a
    # RuntimeError that pipeline.py will catch and classify as analysis_failed
    # (allowing it to record the outcome in CycleStateTracker).
    try:
        import sys as _sys
        _shared_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        if _shared_root not in _sys.path:
            _sys.path.insert(0, _shared_root)
        from shared.market_snapshot_validator import (
            validate_snapshot as _validate_snapshot,
            DataCircuitBreakerError as _DataCircuitBreakerError,
        )
        _validation = _validate_snapshot({
            "market_data":  market_data,
            "macro_data":   macro_data if not crypto_only else {},
            "news_data":    news_data,
            "_snapshot_ts": _snapshot_fetch_ts,
        })
        if not _validation.ok:
            logger.warning(
                f"DataCircuitBreaker | Aborting cycle — {_validation.reason} "
                f"(checks passed={_validation.checks_passed} "
                f"failed={_validation.checks_failed})"
            )
            raise _DataCircuitBreakerError(_validation.reason)
        logger.debug(
            f"DataCircuitBreaker | Snapshot OK "
            f"({_validation.checks_passed} checks passed)"
        )
    except _DataCircuitBreakerError:
        raise   # re-raise typed exception so pipeline.py can isinstance-check it
    except Exception as _vexc:
        # Fail-closed: if the validator itself cannot run (import error, shape error,
        # etc.), abort the cycle rather than silently continuing to the LLM.
        logger.error(
            f"DataCircuitBreaker | Validator raised unexpected error — aborting cycle: {_vexc}"
        )
        try:
            from shared.market_snapshot_validator import DataCircuitBreakerError as _DCBError
            raise _DCBError(f"validator error — {_vexc}") from _vexc
        except ImportError:
            raise RuntimeError(f"DataCircuitBreaker: validator error — {_vexc}") from _vexc

    # ── Step 3: Pre-LLM Signal Guardrails ────────────────────────────────────
    # Run BEFORE building any prompts so guards can gate and adjust all inputs.
    #
    # Authoritative weekend/calendar hard-block lives in pipeline.py — by the
    # time we reach here for full-market mode the pipeline has already cleared
    # that gate.  For crypto_only=True the temporal quarantine is intentionally
    # bypassed (crypto trades 24/7 including weekends).
    #
    # MultiSourceConsensus (soft): filters noisy single-source headlines.
    # PriceToSentimentDivergence (soft, full-market only): adjusts market
    # sentiment band when SPY volume conviction is absent.
    logger.info("Step 3/5 | Running pre-LLM signal guardrails...")
    from analysis.signal_guard import run_all_guards as _run_guards
    headlines_for_llm = news_data["all_headlines"]
    adjusted_sentiment: str | None = None
    try:
        _sentiment_band = "Neutral"
        try:
            from data.sentiment import get_sentiment as _get_sentiment
            _sent = _get_sentiment()
            _sentiment_band = (
                _sent.get("market_fear_greed", {}).get("label", "Neutral") or "Neutral"
            )
        except Exception as _se:
            logger.debug(f"SignalGuard | Could not fetch sentiment band: {_se}")

        guard_result = _run_guards({
            "news_data":      news_data,
            "market_data":    market_data,
            "sentiment_band": _sentiment_band,
            # Signal to run_all_guards: skip temporal hard-block for crypto
            "crypto_only":    crypto_only,
        })

        headlines_for_llm = guard_result.filtered_headlines
        adjusted_sentiment = guard_result.adjusted_sentiment

        if guard_result.hard_block:
            # Temporal quarantine fired.  In normal operation the pipeline
            # pre-screens this before calling run_analysis_cycle(); this path is
            # only reached on a direct force-run or during testing.
            # For full-market mode, return the cached regime if one exists; this
            # mirrors the pipeline's own fallback behavior so force-runs still
            # surface actionable data when the LLM is intentionally skipped.
            # For crypto_only (which never hits this branch because temporal guard
            # is bypassed in run_all_guards when crypto_only=True), raise cleanly.
            _reason = next(
                (r.reason for r in guard_result.results if not r.passed and r.severity == "hard"),
                "temporal quarantine active",
            )
            logger.warning(f"SignalGuard | HARD BLOCK: {_reason}")
            if not crypto_only:
                cached_regime = get_regime_fallback()
                if cached_regime is not None:
                    logger.info(
                        f"SignalGuard | Returning cached regime '{cached_regime.regime}' "
                        "(LLM call skipped — temporal quarantine)"
                    )
                    return cached_regime
            raise RuntimeError(
                f"Signal guard hard block: {_reason}. No cached regime available — "
                "pipeline must skip this cycle."
            )
        else:
            logger.info(
                f"SignalGuard | All guards passed — "
                f"headlines {news_ok} → {len(headlines_for_llm)} after consensus filter"
                + (f" | sentiment adjusted: {_sentiment_band} → {adjusted_sentiment}" if adjusted_sentiment else "")
            )
    except RuntimeError:
        raise   # propagate hard-block guardrail errors unchanged
    except Exception as _guard_exc:
        logger.warning(
            f"SignalGuard | Guard evaluation failed (non-fatal): {_guard_exc} — "
            "using raw headlines and original sentiment"
        )
        headlines_for_llm = news_data["all_headlines"]
        adjusted_sentiment = None

    # ── Step 4: Build RAG-enhanced system prompt (sentiment already adjusted) ─
    # System prompt is built AFTER guards so the sentiment_override (if any)
    # is silently substituted before the LLM ever sees it.
    logger.info("Step 4/5 | Building RAG-enhanced system prompt (post-guard)...")
    system_prompt = build_system_prompt_with_feedback(
        n_losses=n_loss_feedback,
        buying_power=account_state["buying_power"],
        held_symbols=account_state["held_symbols"],
        crypto_only=crypto_only,
        sentiment_override=adjusted_sentiment,  # None = use live sentiment as-is
    )

    logger.info("Step 5/5 | Calling Groq LLM (llama-3.3-70b-versatile)...")
    # Build algo short context for Bear regime LLM awareness
    _algo_short_ctx: dict | None = None
    if not crypto_only:
        try:
            from execution.broker import get_positions as _gpos_llm
            _positions_now = _gpos_llm()
            # Source of truth: all short-side positions in the account (survives restarts)
            _open_shorts_raw = [
                p for p in _positions_now
                if str(p.get("side", "long")).lower() == "short"
                and p.get("symbol") in {"SPY", "QQQ", "XLK", "XLF", "XLE", "IWM"}
            ]
            if _open_shorts_raw:
                _equity_now = float(account_state.get("equity", 1.0)) or 1.0
                _total_short_usd = sum(abs(float(p.get("market_value", 0.0))) for p in _open_shorts_raw)
                _open_shorts_fmt = []
                for _p in _open_shorts_raw:
                    _ep  = float(_p.get("avg_entry_price") or _p.get("current_price", 0.0))
                    _cp  = float(_p.get("current_price", 0.0))
                    _qty = abs(float(_p.get("qty", 0.0)))
                    _pl  = float(_p.get("unrealized_pl", 0.0))
                    _plpc = float(_p.get("unrealized_plpc", 0.0)) * 100
                    _mv  = abs(float(_p.get("market_value", 0.0)))
                    _open_shorts_fmt.append({
                        "symbol":        _p.get("symbol"),
                        "side":          "short",
                        "qty":           _qty,
                        "entry_price":   round(_ep, 4),
                        "current_price": round(_cp, 4),
                        "unrealized_pl": round(_pl, 2),
                        "unrealized_plpc": round(_plpc, 2),
                        "market_value":  round(_mv, 2),
                        "exposure_pct":  round(_mv / _equity_now * 100, 2),
                    })
                _algo_short_ctx = {
                    "activated":          True,
                    "open_shorts":        _open_shorts_fmt,
                    "short_exposure_usd": round(_total_short_usd, 2),
                    "short_exposure_pct": round(_total_short_usd / _equity_now * 100, 2),
                }
        except Exception as _ctx_exc:
            logger.debug(f"Analyzer | Algo short context build failed (non-fatal): {_ctx_exc}")

    user_prompt = build_user_prompt(
        macro_data,
        market_data,
        headlines_for_llm,
        account_state=account_state,
        crypto_only=crypto_only,
        algo_short_context=_algo_short_ctx,
    )

    if dry_run:
        logger.warning("DRY RUN: skipping actual Groq API call, returning mock output")
        if crypto_only:
            raw_json = _mock_crypto_llm_response()
            output = process_crypto_llm_output(raw_json)
        else:
            raw_json = _mock_regime_llm_response()
            output = process_regime_llm_output(raw_json)
    else:
        from analysis.groq_budget import budget as _budget

        from analysis.llm_response_cache import llm_cache as _llm_cache

        if crypto_only:
            if not _budget.can_call_crypto():
                cached_crypto = get_crypto_fallback()
                if cached_crypto is not None:
                    age_min = round(
                        (time.time() - (_last_crypto_cache or {}).get("saved_at", 0)) / 60
                    )
                    logger.info(
                        f"Groq budget | Crypto call throttled — returning cached "
                        f"CryptoAnalysisOutput ({age_min}min old)"
                    )
                    return cached_crypto
                logger.warning(
                    "Groq budget | Crypto call throttled but no cache available — "
                    "proceeding with LLM call to avoid empty allocation"
                )
            cache_key = _llm_cache.make_key("crypto", market_data)
            hits_before = _llm_cache._hits
            output = _call_crypto_with_retry(
                system_prompt, user_prompt, cache_key=cache_key
            )
            if _llm_cache._hits == hits_before:   # no cache hit → real Groq call
                _budget.record_crypto_call()
            else:
                logger.debug("LLMResponseCache | Crypto cache hit — skipping budget call counter")
        else:
            if not _budget.can_call_regime():
                cached_regime = get_regime_fallback()
                if cached_regime is not None:
                    logger.info(
                        "Groq budget | Full-regime call throttled — returning cached regime "
                        f"(age={round((time.time() - (_last_regime_cache or {}).get('saved_at', 0)) / 60)}min)"
                    )
                    return cached_regime
                logger.warning(
                    "Groq budget | Full-regime call throttled but no cache available — "
                    "proceeding with LLM call to avoid empty allocation"
                )
            cache_key = _llm_cache.make_key("regime", market_data)
            hits_before = _llm_cache._hits
            output = _call_regime_with_retry(
                system_prompt, user_prompt, cache_key=cache_key
            )
            if _llm_cache._hits == hits_before:   # no cache hit → real Groq call
                _budget.record_regime_call()
            else:
                logger.debug("LLMResponseCache | Regime cache hit — skipping budget call counter")

    logger.info("=" * 60)
    logger.info(f"ANALYSIS CYCLE COMPLETE ({mode_label})")
    logger.info(output.summary())
    logger.info("=" * 60)

    return output


MAX_LLM_RETRIES = 3


def _call_regime_with_retry(
    system_prompt: str,
    user_prompt: str,
    cache_key: str | None = None,
) -> RegimeAnalysisOutput:
    """
    Execute the regime LLM call with retry logic and response caching.

    Uses `llm_cache.get_or_call(cache_key, call_fn, ttl_minutes=90)` as the
    single cache integration point: on a cache hit the inner call_fn is never
    invoked, so no Groq tokens are consumed; on a miss the full self-correcting
    retry loop runs and the validated raw_json is stored for future hits.
    """
    from analysis.llm_response_cache import llm_cache as _llm_cache

    def _fetch_raw_regime_json() -> str:
        """Full self-correcting retry loop; returns validated raw_json string."""
        last_error: Exception | None = None
        current_prompt = user_prompt

        for attempt in range(1, MAX_LLM_RETRIES + 1):
            logger.info(f"Step 5/5 | Regime LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
            try:
                raw_json = call_groq(
                    system_prompt=system_prompt,
                    user_prompt=current_prompt,
                    temperature=0.2,
                    max_tokens=2048,
                    call_type="regime",
                )
                process_regime_llm_output(raw_json)   # validate — raises on bad JSON
                if attempt > 1:
                    logger.info(f"  LLM self-corrected on attempt {attempt}")
                return raw_json

            except Exception as exc:
                last_error = exc
                error_msg = str(exc)
                logger.warning(f"  Attempt {attempt} failed: {error_msg[:300]}")

                if attempt < MAX_LLM_RETRIES:
                    current_prompt = (
                        f"{user_prompt}\n\n"
                        f"--- CORRECTION REQUIRED (attempt {attempt} was invalid) ---\n"
                        f"Your previous JSON output failed validation with this error:\n"
                        f"  {error_msg}\n\n"
                        f"Please fix and return corrected JSON only. Key rules:\n"
                        f"  - 'regime' must be exactly 'Bull', 'Bear', or 'Sideways'\n"
                        f"  - Bull: 3-7 slots of equity/crypto_spot/commodity with positive momentum\n"
                        f"  - Bear: 1-4 slots of safe_haven (TLT, IEF, GLD, SLV) with positive momentum, else SGOV\n"
                        f"  - Sideways: 0-3 mean-reversion slots (any class), or single SGOV slot\n"
                        f"  - Only approved tickers: SPY, QQQ, XLK, XLF, XLV, XLE, IWM, "
                        f"TLT, IEF, GLD, SLV, USO, PDBC, BTC/USD, ETH/USD, SGOV\n"
                        f"  - Slots numbered 1, 2, 3 ... sequentially\n"
                        f"  - kelly_fraction sum (excluding SGOV) must not exceed 1.0\n"
                        f"  - asset_class must match ticker:\n"
                        f"      equity→SPY/QQQ/XLK/XLF/XLV/XLE/IWM\n"
                        f"      safe_haven→TLT/IEF/GLD/SLV\n"
                        f"      commodity→USO/PDBC\n"
                        f"      crypto_spot→BTC/USD/ETH/USD\n"
                        f"      cash→SGOV\n"
                        f"  - Each position is capped at 10% of equity by the executor. "
                        f"Plan allocations with this in mind: use 10 slots at 10% each to deploy 100%.\n"
                        f"  - stop_loss_pct: -0.07, take_profit_pct: 0.15 (use exactly these placeholder values)\n"
                    )

        raise RuntimeError(
            f"Regime LLM failed after {MAX_LLM_RETRIES} attempts. Last error: {last_error}"
        )

    # ── Cache integration via get_or_call ─────────────────────────────────────
    if cache_key:
        raw_json = _llm_cache.get_or_call(cache_key, _fetch_raw_regime_json, ttl_minutes=90)
    else:
        raw_json = _fetch_raw_regime_json()

    output = process_regime_llm_output(raw_json)
    _save_regime_cache(output)
    try:
        from analysis.learning_journal import record_cycle_learnings
        record_cycle_learnings(output)
    except Exception as _lj_exc:
        logger.warning(f"Learning journal | Regime record failed (non-fatal): {_lj_exc}")
    return output


def _call_crypto_with_retry(
    system_prompt: str,
    user_prompt: str,
    cache_key: str | None = None,
) -> CryptoAnalysisOutput:
    """
    Execute the crypto LLM call with retry logic and response caching.

    Uses `llm_cache.get_or_call(cache_key, call_fn, ttl_minutes=90)` as the
    single cache integration point: on a cache hit the inner call_fn is never
    invoked, so no Groq tokens are consumed; on a miss the full self-correcting
    retry loop runs and the validated raw_json is stored for future hits.
    """
    from analysis.llm_response_cache import llm_cache as _llm_cache

    def _fetch_raw_crypto_json() -> str:
        """Full self-correcting retry loop; returns validated raw_json string."""
        last_error: Exception | None = None
        current_prompt = user_prompt

        for attempt in range(1, MAX_LLM_RETRIES + 1):
            logger.info(f"Step 5/5 | Crypto LLM call attempt {attempt}/{MAX_LLM_RETRIES}...")
            try:
                raw_json = call_groq(
                    system_prompt=system_prompt,
                    user_prompt=current_prompt,
                    temperature=0.2,
                    max_tokens=2048,
                    call_type="crypto",
                )
                process_crypto_llm_output(raw_json)   # validate — raises on bad JSON
                if attempt > 1:
                    logger.info(f"  LLM self-corrected on attempt {attempt}")
                return raw_json

            except Exception as exc:
                last_error = exc
                error_msg = str(exc)
                logger.warning(f"  Attempt {attempt} failed: {error_msg[:300]}")

                if attempt < MAX_LLM_RETRIES:
                    current_prompt = (
                        f"{user_prompt}\n\n"
                        f"--- CORRECTION REQUIRED (attempt {attempt} was invalid) ---\n"
                        f"Your previous JSON output failed validation with this error:\n"
                        f"  {error_msg}\n\n"
                        f"Please fix and return corrected JSON only. Rules:\n"
                        f"  - Only approved tickers: BTC/USD, ETH/USD, SGOV (ATOM/USD is NOT valid)\n"
                        f"  - asset_class: 'crypto_spot' for BTC/USD and ETH/USD, 'cash' for SGOV\n"
                        f"  - 1 to 2 slots, numbered sequentially from 1\n"
                        f"  - kelly_fraction sum (excluding SGOV) <= 1.0\n"
                        f"  - Only allocate to crypto with POSITIVE momentum. Default SGOV if uncertain.\n"
                        f"  - stop_loss_pct: -0.07, take_profit_pct: 0.15 (use exactly these placeholder values)\n"
                    )

        raise RuntimeError(
            f"Crypto LLM failed after {MAX_LLM_RETRIES} attempts. Last error: {last_error}"
        )

    # ── Cache integration via get_or_call ─────────────────────────────────────
    if cache_key:
        raw_json = _llm_cache.get_or_call(cache_key, _fetch_raw_crypto_json, ttl_minutes=90)
    else:
        raw_json = _fetch_raw_crypto_json()

    output = process_crypto_llm_output(raw_json)
    _save_crypto_cache(output)
    try:
        from analysis.learning_journal import record_cycle_learnings
        record_cycle_learnings(output)
    except Exception as _lj_exc:
        logger.warning(f"Learning journal | Crypto record failed (non-fatal): {_lj_exc}")
    return output


def _mock_regime_llm_response() -> str:
    return json.dumps({
        "regime": "Bear",
        "regime_rationale": (
            "Elevated VIX above 25, inverted yield curve normalising from deeply negative levels, "
            "Fed holding rates higher-for-longer with no pivot signal. Equity momentum is negative "
            "on both 3-month and 6-month MAs. Safe havens showing positive momentum."
        ),
        "allocations": [
            {
                "slot": 1,
                "ticker": "GLD",
                "asset_class": "safe_haven",
                "conviction_score": 0.88,
                "kelly_fraction": 0.25,
                "thesis": "Gold breaking out above key resistance. Real rates declining as inflation "
                          "expectations remain elevated. Momentum positive on both MAs.",
                "stop_loss_pct": -0.05,
                "take_profit_pct": 0.12,
            },
            {
                "slot": 2,
                "ticker": "TLT",
                "asset_class": "safe_haven",
                "conviction_score": 0.82,
                "kelly_fraction": 0.25,
                "thesis": "Long-duration Treasuries benefiting from flight-to-quality. Momentum positive "
                          "on both MAs as recession risk increases and Fed nears peak rates.",
                "stop_loss_pct": -0.05,
                "take_profit_pct": 0.10,
            },
            {
                "slot": 3,
                "ticker": "IEF",
                "asset_class": "safe_haven",
                "conviction_score": 0.78,
                "kelly_fraction": 0.25,
                "thesis": "Intermediate Treasuries offer lower duration risk with positive momentum. "
                          "Defensive positioning appropriate given elevated VIX.",
                "stop_loss_pct": -0.04,
                "take_profit_pct": 0.08,
            },
            {
                "slot": 4,
                "ticker": "SLV",
                "asset_class": "safe_haven",
                "conviction_score": 0.75,
                "kelly_fraction": 0.25,
                "thesis": "Silver following gold higher as inflation hedge demand increases. "
                          "Positive momentum on 3-month MA signal.",
                "stop_loss_pct": -0.06,
                "take_profit_pct": 0.15,
            },
        ],
    })


def _mock_crypto_llm_response() -> str:
    return json.dumps({
        "market_regime": (
            "Crypto markets consolidating with BTC holding key support. "
            "ETH showing relative strength with positive momentum on both MAs."
        ),
        "allocations": [
            {
                "slot": 1,
                "ticker": "BTC/USD",
                "asset_class": "crypto_spot",
                "conviction_score": 0.85,
                "kelly_fraction": 0.50,
                "thesis": "Bitcoin holding key support with strong institutional inflows. "
                          "3-month and 6-month momentum both positive.",
                "stop_loss_pct": -0.08,
                "take_profit_pct": 0.18,
            },
            {
                "slot": 2,
                "ticker": "ETH/USD",
                "asset_class": "crypto_spot",
                "conviction_score": 0.80,
                "kelly_fraction": 0.50,
                "thesis": "Ethereum showing relative strength with growing staking yields "
                          "and DeFi TVL recovery. Positive momentum on both MAs.",
                "stop_loss_pct": -0.09,
                "take_profit_pct": 0.20,
            },
        ],
    })
