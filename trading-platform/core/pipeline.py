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

# ── Afterhours crypto watchlist ───────────────────────────────────────────────
# Symbols in the format used by Alpaca's CryptoHistoricalDataClient.
_AFTERHOURS_CRYPTO_WATCHLIST: list[str] = [
    "BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD",
]

# Internal symbol format (no slash) used by Alpaca's position API
_AFTERHOURS_CRYPTO_SYMBOLS_NOSLASH: frozenset[str] = frozenset(
    s.replace("/", "") for s in _AFTERHOURS_CRYPTO_WATCHLIST
)

# How many positions to open simultaneously during afterhours (max 4)
_AFTERHOURS_MAX_POSITIONS: int = 4

# Minimum notional per afterhours crypto order (USD)
_AFTERHOURS_MIN_NOTIONAL: float = 25.0

# Z-Score threshold for mean-reversion entry (buy when oversold)
_AFTERHOURS_Z_ENTRY: float = -1.0   # z-score ≤ -1.0 → oversold
_AFTERHOURS_RSI_ENTRY: float = 45.0  # RSI ≤ 45 → still weak, room to recover

# Per-position cap (10% of total equity — mirrors equity mode cap)
_AFTERHOURS_MAX_POSITION_PCT: float = 0.10


def _is_alpaca_crypto_symbol(symbol: str) -> bool:
    """Return True if *symbol* is an Alpaca afterhours crypto position (e.g. BTCUSD)."""
    return symbol.upper() in _AFTERHOURS_CRYPTO_SYMBOLS_NOSLASH


async def run_afterhours_crypto_cycle(dry_run: bool = False) -> dict:
    """
    Oracle Afterhours Crypto Cycle
    --------------------------------
    Runs when the NYSE is closed.  No LLM call — uses a lightweight
    Z-Score + RSI mean-reversion signal to select and size crypto entries.

    Steps:
      1. Capital guard: compute idle cash via get_afterhours_available_cash().
      2. Skip if insufficient capital or kill switch tripped.
      3. Fetch recent OHLCV bars for each symbol in the watchlist via
         Alpaca CryptoHistoricalDataClient.
      4. Compute Z-Score (price vs 20-bar mean/std) and RSI(14) for each.
      5. Select symbols meeting the mean-reversion entry signal.
      6. Size each position: equal-weight across selected symbols, capped at
         AFTERHOURS_MAX_POSITION_PCT of equity and AFTERHOURS_CASH_CAP of cash.
      7. Place GTC buy orders via the existing broker.place_order().
      8. Apply all existing circuit breakers: per-position 10% cap, VaR guard,
         daily drawdown kill switch.
    """
    logger.info("=" * 60)
    logger.info("AFTERHOURS CRYPTO CYCLE STARTING")
    logger.info("=" * 60)

    result: dict = {
        "status":           "ok",
        "afterhours":       True,
        "afterhours_mode":  "crypto_mean_reversion",
        "errors":           [],
        "placed":           [],
        "skipped":          [],
        "signals":          [],
    }

    from execution.broker import get_positions, get_account, place_order
    from execution.kill_switch import is_tripped as _ks_tripped, check as _ks_check_ah
    from execution.executor import get_afterhours_available_cash, AFTERHOURS_CASH_CAP

    # Run live drawdown evaluation (ks_check) first, then check persisted state.
    # ks_check() evaluates intraday drawdown and may trip the switch.
    if _ks_check_ah():
        msg = "Afterhours cycle: kill switch tripped (live drawdown check) — skipping"
        logger.warning(msg)
        result["status"] = "kill_switch_tripped"
        result["errors"].append(msg)
        return result

    if _ks_tripped():
        msg = "Afterhours cycle: kill switch tripped — skipping"
        logger.warning(msg)
        result["status"] = "kill_switch_tripped"
        result["errors"].append(msg)
        return result

    available_cash = get_afterhours_available_cash()
    if available_cash < _AFTERHOURS_MIN_NOTIONAL:
        msg = f"Afterhours cycle: insufficient cash (${available_cash:.2f}) — skipping"
        logger.info(msg)
        result["status"] = "insufficient_cash"
        result["errors"].append(msg)
        return result

    acct = get_account()
    equity = acct["equity"]
    max_position_usd = round(equity * _AFTERHOURS_MAX_POSITION_PCT, 2)

    all_positions = get_positions()
    existing_positions = {p["symbol"] for p in all_positions}

    # ── VaR Circuit Breaker ────────────────────────────────────────────────
    # Mirror the equity-mode VaR gate: if 1-day 95% historical VaR across
    # current positions exceeds the daily loss limit (5% of equity), block
    # all NEW entries this cycle.  Existing positions are unaffected.
    try:
        from portfolio.var_calculator import compute_daily_var as _compute_var
        _SAFE_SET = frozenset({"SGOV", "JEPQ"})
        _risk_positions = [
            {"symbol": p["symbol"], "market_value": p.get("market_value", 0.0)}
            for p in all_positions
            if p.get("symbol") not in _SAFE_SET
        ]
        _invested_usd = sum(abs(float(p.get("market_value", 0.0) or 0.0)) for p in _risk_positions)
        _var_pct = _compute_var(_risk_positions, confidence=0.95) if _risk_positions else 0.0
        _var_usd = _var_pct * _invested_usd
        _var_limit_usd = 0.05 * equity
        if _var_limit_usd > 0 and _var_usd > _var_limit_usd:
            msg = (
                f"Afterhours cycle: VaR circuit breaker tripped — "
                f"1-day 95% VaR=${_var_usd:,.2f} > limit=${_var_limit_usd:,.2f} — "
                f"no new afterhours entries this cycle"
            )
            logger.warning(msg)
            result["status"] = "var_circuit_breaker"
            result["errors"].append(msg)
            return result
        if _var_usd > 0:
            logger.info(
                f"Afterhours cycle: VaR=${_var_usd:,.2f} within limit=${_var_limit_usd:,.2f}"
            )
    except Exception as _var_exc:
        logger.debug(f"Afterhours cycle: VaR check failed (non-fatal, proceeding): {_var_exc}")

    from config.settings import settings as _cfg
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
        import pandas as pd
        from datetime import datetime, timezone, timedelta

        data_client = CryptoHistoricalDataClient(
            api_key=_cfg.alpaca_api_key,
            secret_key=_cfg.alpaca_secret_key,
        )
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=5)

        req = CryptoBarsRequest(
            symbol_or_symbols=_AFTERHOURS_CRYPTO_WATCHLIST,
            timeframe=TimeFrame.Hour,
            start=start_dt,
            end=end_dt,
        )
        bars_response = data_client.get_crypto_bars(req)

        # Build a per-symbol dict of close-price Series from the BarSet.
        # The Alpaca SDK `BarSet` maps symbol → list[Bar].  We extract close
        # prices into a plain pandas Series for each symbol.
        _symbol_closes: dict[str, "pd.Series"] = {}
        for _sym in _AFTERHOURS_CRYPTO_WATCHLIST:
            try:
                _bar_list = bars_response[_sym]
                if _bar_list:
                    _closes_arr = [float(b.close) for b in _bar_list]
                    _symbol_closes[_sym] = pd.Series(_closes_arr, dtype=float)
                    logger.debug(
                        f"Afterhours | {_sym}: got {len(_closes_arr)} bars "
                        f"(last close={_closes_arr[-1]:.4f})"
                    )
            except (KeyError, TypeError):
                logger.debug(f"Afterhours | {_sym}: no bars returned")

    except Exception as exc:
        msg = f"Afterhours cycle: failed to fetch crypto bars: {exc}"
        logger.error(msg)
        result["status"] = "data_fetch_failed"
        result["errors"].append(msg)
        return result

    def _compute_signal(symbol: str) -> dict | None:
        """Compute Z-Score and RSI for a symbol. Returns signal dict or None."""
        try:
            closes = _symbol_closes.get(symbol)
            if closes is None or len(closes) < 20:
                logger.debug(f"Afterhours | {symbol}: insufficient bars ({len(closes) if closes is not None else 0})")
                return None

            price = float(closes.iloc[-1])

            mean_20 = float(closes.rolling(20).mean().iloc[-1])
            std_20 = float(closes.rolling(20).std().iloc[-1])
            z_score = (price - mean_20) / std_20 if std_20 > 0 else 0.0

            # Wilder's EMA RSI — consistent with forex-engine/indicators.py and
            # all Kraken bots. Rolling SMA (.rolling(14).mean()) gives different
            # values; Wilder's is the industry standard used everywhere else.
            _rsi_period = 14
            _cl = closes.tolist()
            if len(_cl) < _rsi_period + 1:
                rsi = 50.0
            else:
                _ch = [_cl[i] - _cl[i - 1] for i in range(1, len(_cl))]
                _g  = [max(c, 0.0) for c in _ch]
                _l  = [abs(min(c, 0.0)) for c in _ch]
                _ag = sum(_g[:_rsi_period]) / _rsi_period
                _al = sum(_l[:_rsi_period]) / _rsi_period
                for _i in range(_rsi_period, len(_g)):
                    _ag = (_ag * (_rsi_period - 1) + _g[_i]) / _rsi_period
                    _al = (_al * (_rsi_period - 1) + _l[_i]) / _rsi_period
                rsi = 100.0 if _al == 0.0 else round(100.0 - 100.0 / (1.0 + _ag / _al), 2)

            return {
                "symbol": symbol,
                "price": price,
                "z_score": round(z_score, 3),
                "rsi_14": round(rsi, 2),
                "mean_20h": round(mean_20, 4),
                "std_20h": round(std_20, 4),
                "bars": len(closes),
            }
        except Exception as exc:
            logger.debug(f"Afterhours | {symbol}: signal computation failed: {exc}")
            return None

    signals = []
    for sym in _AFTERHOURS_CRYPTO_WATCHLIST:
        sig = _compute_signal(sym)
        if sig is not None:
            signals.append(sig)
            logger.info(
                f"Afterhours | {sym}: price={sig['price']:.4f} "
                f"z={sig['z_score']:+.3f} rsi={sig['rsi_14']:.1f}"
            )

    result["signals"] = signals

    entry_candidates = [
        s for s in signals
        if s["z_score"] <= _AFTERHOURS_Z_ENTRY and s["rsi_14"] <= _AFTERHOURS_RSI_ENTRY
    ]

    entry_candidates.sort(key=lambda s: s["z_score"])
    entry_candidates = entry_candidates[:_AFTERHOURS_MAX_POSITIONS]

    if not entry_candidates:
        logger.info("Afterhours cycle: no mean-reversion signals — holding cash")
        result["status"] = "no_signals"
        return result

    logger.info(
        f"Afterhours cycle: {len(entry_candidates)} entry candidate(s): "
        f"{[s['symbol'] for s in entry_candidates]}"
    )

    n_entries = len(entry_candidates)
    per_position_usd = min(
        available_cash / n_entries,
        max_position_usd,
    )

    remaining_cash = available_cash

    for sig in entry_candidates:
        sym_pair = sig["symbol"]
        sym_flat = sym_pair.replace("/", "")

        if sym_flat in existing_positions:
            logger.info(f"Afterhours | {sym_pair}: already have position — skipping")
            result["skipped"].append({"symbol": sym_pair, "reason": "already_open"})
            continue

        notional = min(per_position_usd, remaining_cash)
        if notional < _AFTERHOURS_MIN_NOTIONAL:
            logger.info(f"Afterhours | {sym_pair}: notional ${notional:.2f} below minimum — skipping")
            result["skipped"].append({"symbol": sym_pair, "reason": "below_min_notional", "notional": notional})
            continue

        if dry_run:
            logger.info(f"Afterhours | DRY RUN: would buy {sym_pair} ${notional:,.2f} GTC")
            result["placed"].append({
                "symbol": sym_pair,
                "notional_usd": notional,
                "z_score": sig["z_score"],
                "rsi_14": sig["rsi_14"],
                "dry_run": True,
            })
            remaining_cash -= notional
            continue

        try:
            order = place_order(ticker=sym_pair, notional_usd=notional)
            logger.info(
                f"Afterhours | Placed GTC buy {sym_pair} ${notional:,.2f} "
                f"(z={sig['z_score']:+.3f} rsi={sig['rsi_14']:.1f}) "
                f"order_id={order['id']}"
            )
            result["placed"].append({
                "symbol":       sym_pair,
                "notional_usd": notional,
                "order_id":     order["id"],
                "z_score":      sig["z_score"],
                "rsi_14":       sig["rsi_14"],
            })
            remaining_cash -= notional
        except Exception as exc:
            logger.error(f"Afterhours | Failed to place order for {sym_pair}: {exc}")
            result["errors"].append(f"Order failed for {sym_pair}: {exc}")

    result["cash_deployed"] = round(available_cash - remaining_cash, 2)
    result["cash_remaining"] = round(remaining_cash, 2)
    result["positions_opened"] = len(result["placed"])

    logger.info("=" * 60)
    logger.info(
        f"AFTERHOURS CRYPTO CYCLE COMPLETE | "
        f"placed={result['positions_opened']} "
        f"skipped={len(result['skipped'])} "
        f"errors={len(result['errors'])} "
        f"deployed=${result['cash_deployed']:,.2f}"
    )
    logger.info("=" * 60)
    return result


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
    # ── Fleet halt check — cross-process emergency stop ───────────────────────
    from core.fleet_halt import is_halted as _is_fleet_halted
    if _is_fleet_halted():
        logger.warning(
            "Pipeline | FLEET HALT ACTIVE — skipping all pipeline logic. "
            "Use POST /trading-api/fleet/resume to clear."
        )
        return {
            "status": "fleet_halted",
            "message": "Fleet emergency halt is active — no trades executed",
        }

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

    # Conflict guard: when SPY emergency Bear override is active, suppress Oracle long entries
    # to prevent Oracle longs and short scanner Bear shorts fighting on the same account.
    _suppress_oracle_longs = spy_override
    if _suppress_oracle_longs:
        logger.warning(
            "Pipeline | SPY emergency override active — Oracle long entries suppressed "
            "to prevent conflict with short scanner Bear positions."
        )

    # ── Market Reopen: Exit all afterhours crypto positions ───────────────────
    # At the start of each equity cycle (market is open), check for any open
    # Alpaca crypto positions (identified by BTCUSD/ETHUSD/SOLUSD/AVAXUSD).
    # Protocol:
    #   1. Issue GTC sell orders for all open afterhours crypto positions.
    #   2. Poll (up to 60s) until each position is cleared.
    #   3. Positions that remain open after polling are persisted in pipeline
    #      state (_state["afterhours_unresolved"]) so that subsequent cycles
    #      continue to enforce the block.
    #   4. Equity deployment cash is reduced by the notional value of any
    #      unresolved crypto exits — this value is stored in result as
    #      "afterhours_reserved_cash" and is read by the executor cash gate.
    if not crypto_only and is_market_open():
        try:
            import time as _time_ah
            from execution.broker import get_positions as _gpos_ah, close_position_gtc as _close_ah

            _all_pos = _gpos_ah()
            _crypto_positions = [
                p for p in _all_pos
                if _is_alpaca_crypto_symbol(p["symbol"])
            ]

            # Also handle any previously-unresolved exits from prior cycles
            _prev_unresolved: set = set(_state.get("afterhours_unresolved", []))

            if _crypto_positions or _prev_unresolved:
                logger.info(
                    f"Pipeline | Market reopen: found {len(_crypto_positions)} afterhours crypto "
                    f"position(s); {len(_prev_unresolved)} previously unresolved: "
                    f"{[p['symbol'] for p in _crypto_positions]}"
                )

                # Issue exit orders for all currently-open crypto positions
                _exit_attempted: dict[str, float] = {}
                for _cpos in _crypto_positions:
                    _sym = _cpos["symbol"]
                    _mv = _cpos.get("market_value", 0.0)
                    try:
                        _close_ah(_sym)
                        _exit_attempted[_sym] = _mv
                        logger.info(
                            f"Pipeline | Market reopen: exit order placed for {_sym} "
                            f"(value=${_mv:,.2f})"
                        )
                    except Exception as _ce:
                        logger.warning(
                            f"Pipeline | Market reopen: could not submit exit for {_sym}: {_ce} "
                            f"— capital reserved until resolved"
                        )
                        _exit_attempted[_sym] = _mv

                # Poll until positions are flat (max 60 seconds, 5s intervals)
                # Use asyncio.sleep to avoid blocking the event loop.
                import asyncio as _asyncio_ah
                _poll_deadline = _time_ah.time() + 60
                _unresolved_syms: set = set(_exit_attempted.keys())
                while _unresolved_syms and _time_ah.time() < _poll_deadline:
                    await _asyncio_ah.sleep(5)
                    try:
                        _remaining = {
                            p["symbol"] for p in _gpos_ah()
                            if _is_alpaca_crypto_symbol(p["symbol"])
                        }
                        _just_cleared = _unresolved_syms - _remaining
                        for _cleared in _just_cleared:
                            logger.info(f"Pipeline | Market reopen: {_cleared} cleared")
                        _unresolved_syms &= _remaining
                    except Exception as _poll_exc:
                        logger.debug(f"Pipeline | Market reopen poll error (retrying): {_poll_exc}")

                # Persist unresolved set so future cycles also skip those slots
                if _unresolved_syms:
                    logger.warning(
                        f"Pipeline | Market reopen: {len(_unresolved_syms)} position(s) still open "
                        f"after 60s: {_unresolved_syms} — capital reserved this cycle and onwards"
                    )
                    _state["afterhours_unresolved"] = list(_unresolved_syms)
                else:
                    logger.info("Pipeline | Market reopen: all afterhours crypto positions cleared")
                    _state["afterhours_unresolved"] = []

                # Compute reserved notional (unresolved exits + previously-unresolved)
                # Previously-unresolved symbols carry their stored notional from the
                # prior cycle — fall back to that if they didn't appear in the fresh
                # exit attempt (e.g. order was already pending from last cycle).
                _prev_notional: dict = _state.get("afterhours_unresolved_notional", {})
                _reserved_notional = sum(
                    _exit_attempted.get(sym, _prev_notional.get(sym, 0.0))
                    for sym in _unresolved_syms
                )
                _reserved_notional = max(_reserved_notional, 0.0)

                # Persist unresolved notional so future cycles can reserve accurately
                _state["afterhours_unresolved_notional"] = {
                    sym: _exit_attempted.get(sym, _prev_notional.get(sym, 0.0))
                    for sym in _unresolved_syms
                }

                result["afterhours_exit"] = {
                    "attempted":         len(_exit_attempted),
                    "unresolved":        list(_unresolved_syms),
                    "reserved_cash_usd": round(_reserved_notional, 2),
                }
                if _reserved_notional > 0:
                    result.setdefault("errors", []).append(
                        f"Afterhours crypto exit unresolved for {list(_unresolved_syms)} "
                        f"(${_reserved_notional:,.2f} reserved — equity slots skipped)"
                    )
                result["afterhours_reserved_cash"] = _reserved_notional

        except Exception as _ae:
            logger.warning(f"Pipeline | Market reopen crypto exit check failed (non-fatal): {_ae}")

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
        # Oracle only trades NYSE market hours — no afterhours activity.
        logger.info("Pipeline | Oracle | Market closed — skipping cycle (no afterhours trading)")
        result["status"] = "market_closed"
        result["market_regime"] = "Market closed — Oracle only trades NYSE hours"
        _update_state(result, started, trading_mode="market_closed")
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
            return result
    except Exception as exc:
        logger.warning(f"Pipeline | Blackout check failed: {exc} — continuing")

    # ── Oracle Pure Momentum Scan (replaces LLM analysis cycle) ─────────────
    # Deterministic trend-following scan — no Groq/Gemini LLM calls.
    # Strategy: Stock Trend Follower v1.0 (EMA20/EMA50 + ADX + ATR sizing).
    # Regime = "Sideways" is used as the schema label (passes validator for
    # non-LETF / non-bear-hedge tickers; momentum_equity asset_class bypasses
    # the ticker-universe check entirely).
    allocation: Union[RegimeAnalysisOutput, CryptoAnalysisOutput, None] = None
    using_fallback = False
    _oracle_short_signals: list = []
    _oracle_stf_protected: frozenset[str] = frozenset()  # open trend positions to preserve

    try:
        logger.info("Pipeline | Oracle STF Step 1: Fetching positions + momentum universe...")
        from execution.broker import get_positions as _scan_gpos, get_account as _scan_acct
        from analysis.schemas import RegimeAnalysisOutput as _ScanRAO, RegimeAllocationSlot as _ScanRAS
        from execution.algo_scanner import run_algo_scan as _run_scan

        _open_pos  = _scan_gpos()
        _open_syms = {p["symbol"] for p in _open_pos}

        # ── One-time STF activation: liquidate all legacy Oracle positions ────
        # On the very first cycle after deploying Stock Trend Follower v1.0,
        # close every open Alpaca position so the new strategy starts clean.
        # A flag file ensures this runs exactly once and never again.
        def _stf_activated() -> bool:
            try:
                from db.postgres import get_conn, is_pg_available
                if not is_pg_available():
                    return True  # fail-safe: if DB down, assume activated to prevent liquidation
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM stf_activation_flags WHERE flag_key = 'stf_v1_activated' LIMIT 1"
                        )
                        return cur.fetchone() is not None
            except Exception:
                return True  # fail-safe

        def _mark_stf_activated() -> None:
            try:
                from db.postgres import get_conn, is_pg_available
                if is_pg_available():
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                CREATE TABLE IF NOT EXISTS stf_activation_flags (
                                    flag_key TEXT PRIMARY KEY,
                                    activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                                )
                            """)
                            cur.execute(
                                "INSERT INTO stf_activation_flags (flag_key) VALUES ('stf_v1_activated') ON CONFLICT DO NOTHING"
                            )
                        conn.commit()
            except Exception as e:
                logger.error(f"STF | Failed to write activation flag to DB: {e}")

        if not _stf_activated():
            logger.warning(
                "Pipeline | STF v1.0 ACTIVATION — closing all legacy Oracle positions at market..."
            )
            _CRYPTO_SKIP = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD"})
            for _liq_pos in _open_pos:
                _liq_sym = _liq_pos["symbol"]
                if _liq_sym in _CRYPTO_SKIP:
                    continue
                try:
                    from execution.broker import close_position as _liq_close
                    _liq_close(_liq_sym)
                    logger.info(f"  STF liquidation: closed {_liq_sym}")
                    # Mark trade closed in journal
                    try:
                        from db.postgres import get_conn as _liq_gc, is_pg_available as _liq_pg
                        if _liq_pg():
                            _raw_pnl = float(_liq_pos.get("unrealized_pl", 0) or 0)
                            _cost    = float(_liq_pos.get("cost_basis", _liq_pos.get("market_value", 0) or 0))
                            _pct     = (_raw_pnl / abs(_cost) * 100) if _cost else 0.0
                            with _liq_gc() as _liq_c:
                                with _liq_c.cursor() as _liq_cur:
                                    _liq_cur.execute(
                                        "UPDATE trades SET status='Closed_Loss', exit_reason='stf_v1_activation_liquidation', "
                                        "realized_pnl=%s, pnl_percentage=%s "
                                        "WHERE ticker=%s AND status='Active'",
                                        (round(_raw_pnl, 2), round(_pct, 4), _liq_sym),
                                    )
                    except Exception as _liq_dbe:
                        logger.debug(f"  STF liquidation DB update failed for {_liq_sym}: {_liq_dbe}")
                    # Remove ratchet stop
                    try:
                        from execution.ratchet_stop import delete_stop as _liq_del
                        _liq_del(_liq_sym)
                    except Exception:
                        pass
                except Exception as _liq_exc:
                    logger.error(f"  STF liquidation failed for {_liq_sym}: {_liq_exc}")
            _mark_stf_activated()
            logger.info("Pipeline | STF v1.0 activation complete — flag written, new strategy live.")
            # Refresh open positions after liquidation
            _open_pos  = _scan_gpos()
            _open_syms = {p["symbol"] for p in _open_pos}

        # ── Fetch momentum universe data before running the scan ──────────────
        # get_cached_momentum_data() starts as None on every cold boot.
        # fetch_momentum_universe() pulls 1-year daily bars for all ~250
        # tickers from Alpaca and populates the in-process cache.
        # Without this call the scan always returns universe_scanned=0.
        from data.yfinance_client import fetch_momentum_universe as _fetch_mom, get_cached_momentum_data as _get_mom_cache
        logger.info("Pipeline | Oracle STF Step 1a: fetching momentum universe (~250 tickers)...")
        await _fetch_mom()

        # ── Oracle Exit Manager (STF v1.0) ─────────────────────────────────
        # Run BEFORE the entry scan so that exiting positions free their slots.
        # Manages trailing stops and checks EMA reversal / ADX / time exits.
        # Non-fatal — if it fails, existing positions continue unchanged.
        _CRYPTO_SKIP = frozenset({"BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD"})
        if _open_pos:
            try:
                from execution.oracle_exit_manager import (
                    run_oracle_exit_checks as _run_exits,
                    execute_exits as _exec_exits,
                )
                _mom_cache = _get_mom_cache()
                _exit_list = _run_exits(_mom_cache, dry_run=dry_run)
                if _exit_list:
                    _exit_result = _exec_exits(_exit_list, dry_run=dry_run)
                    result.setdefault("oracle_exits", []).extend(_exit_result.get("closed", []))
                    logger.info(
                        f"Pipeline | Oracle exits: closed={len(_exit_result.get('closed', []))} "
                        f"errors={len(_exit_result.get('errors', []))}"
                    )
                    # Refresh positions after exits
                    _open_pos  = _scan_gpos()
                    _open_syms = {p["symbol"] for p in _open_pos}
            except Exception as _em_exc:
                logger.warning(f"Pipeline | Oracle exit manager failed (non-fatal): {_em_exc}")

        # Positions still open after exit manager = protected from stale rotation
        _oracle_stf_protected = frozenset(
            sym for sym in _open_syms if sym not in _CRYPTO_SKIP
        )

        # Equity for ATR-based position sizing
        try:
            _stf_acct  = _scan_acct()
            _stf_equity = float(_stf_acct.get("equity", 100_000.0) or 100_000.0)
        except Exception:
            _stf_equity = 100_000.0

        _algo_result = _run_scan(open_symbols=_open_syms, equity=_stf_equity)
        _long_slots  = _algo_result.get("signals", [])
        _oracle_short_signals = _algo_result.get("short_signals", [])

        result["algo_scanner"] = {
            "scan_type":        "stock_trend_follower_v1",
            "active_signals":   len(_long_slots),
            "activated":        bool(_long_slots or _oracle_short_signals),
            "universe_scanned": _algo_result.get("universe_scanned", 0),
            "top5_long":        _algo_result.get("top5_long", []),
            "top5_short":       _algo_result.get("top5_short", []),
            "filter_stages":    _algo_result.get("filter_stages", {}),
        }

        if not _long_slots and not _oracle_stf_protected:
            logger.info(
                "Pipeline | Oracle STF scan: no signals and no open positions "
                "— holding cash this cycle"
            )
            result["status"]       = "ok"
            result["market_regime"] = "STF: no qualifying trend signals — holding cash"
            _update_state(result, started, trading_mode="stf_no_signals")
            return result

        if not _long_slots:
            logger.info(
                f"Pipeline | Oracle STF scan: no new entry signals (holding "
                f"{len(_oracle_stf_protected)} open trend position(s))"
            )

        _effective_long_slots = [] if _suppress_oracle_longs else _long_slots
        _alloc_slots = [_ScanRAS.model_validate({**s, "slot": i + 1}) for i, s in enumerate(_effective_long_slots)]

        # Read actual equity regime for correct trade tagging
        _actual_regime_label = "Sideways"  # default
        try:
            import json as _regime_json
            from pathlib import Path as _regime_path_cls
            _regime_file = _regime_path_cls(__file__).parent.parent / "data" / "market_regime.json"
            if _regime_file.exists():
                _regime_data = _regime_json.loads(_regime_file.read_text())
                _read_regime = str(_regime_data.get("regime", "Sideways")).strip()
                if _read_regime in ("Bull", "Bear", "Sideways"):
                    _actual_regime_label = _read_regime
        except Exception as _re_exc:
            logger.debug(f"Pipeline | Could not read market_regime.json for regime label: {_re_exc}")

        allocation = _ScanRAO(
            regime=_actual_regime_label,
            regime_rationale=(
                f"Oracle STF v1.0: {len(_alloc_slots)} new long(s), "
                f"{len(_oracle_short_signals)} short(s), "
                f"{len(_oracle_stf_protected)} position(s) held — "
                f"EMA20/EMA50 + ADX + ATR sizing"
            ),
            allocations=_alloc_slots,
        )

        logger.info(
            f"Pipeline | Oracle STF: {len(_alloc_slots)} new longs + "
            f"{len(_oracle_short_signals)} shorts + "
            f"{len(_oracle_stf_protected)} held positions — proceeding to execution"
        )

    except Exception as exc:
        logger.error(f"Pipeline | Oracle STF scan FAILED: {exc}")
        result["status"] = "analysis_failed"
        result["errors"].append(f"STF scan failed: {exc}")
        _persist_emergency_regime(spy_override, spy_change, cycle_num)
        _update_state(result, started, trading_mode="stf_error")
        return result

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
        _pipeline_regime = str(allocation.regime) if hasattr(allocation, "regime") else _state.get("last_regime")
        _ah_reserved = float(result.get("afterhours_reserved_cash", 0.0))
        exec_result = execute_allocations(
            allocation,
            dry_run=dry_run,
            regime_label=_pipeline_regime,
            reserved_cash=_ah_reserved,
            additional_protected=_oracle_stf_protected,
        )
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

    # ── Oracle Short Execution ────────────────────────────────────────────────
    # Short signals from the momentum scan are executed separately (short selling
    # uses a different Alpaca order path than long buys).  Non-fatal.
    if _oracle_short_signals and not dry_run:
        try:
            from execution.oracle_short_executor import execute_oracle_shorts
            _short_result = execute_oracle_shorts(_oracle_short_signals)
            result["oracle_shorts"] = _short_result
            logger.info(
                f"Pipeline | Oracle shorts: placed={_short_result.get('placed', 0)} "
                f"skipped={_short_result.get('skipped', 0)} "
                f"errors={len(_short_result.get('errors', []))}"
            )
        except Exception as _se:
            logger.warning(f"Pipeline | Oracle short execution failed (non-fatal): {_se}")
            result.setdefault("errors", []).append(f"Oracle short execution error: {_se}")

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
        options_eq = 0.0  # Options engine retired; Apex Predator now runs as Kraken crypto momentum
        forex_eq = 100_000.0
        try:
            from routes._deps import _get_forex_engine as _gfx_snap
            _fx_snap = _gfx_snap()
            if _fx_snap:
                _fx_val = float(_fx_snap.get_state().get("paper_equity", 0))
                if _fx_val > 0:
                    forex_eq = _fx_val
        except Exception:
            pass
        poseidon_eq = 0.0
        try:
            from db.postgres import get_conn as _gc_ps
            with _gc_ps() as _conn_ps:
                with _conn_ps.cursor() as _cur_ps:
                    _cur_ps.execute("SELECT equity_usd FROM poseidon_portfolio WHERE id = 7")
                    _row_ps = _cur_ps.fetchone()
                    if _row_ps:
                        poseidon_eq = float(_row_ps[0])
        except Exception:
            poseidon_eq = 100_000.0
        kc_eq = 0.0
        try:
            from db.postgres import get_conn as _gc_kc
            with _gc_kc() as _conn_kc:
                with _conn_kc.cursor() as _cur_kc:
                    _cur_kc.execute("SELECT equity_usd FROM kraken_current_portfolio WHERE id = 8")
                    _row_kc = _cur_kc.fetchone()
                    if _row_kc:
                        kc_eq = float(_row_kc[0])
        except Exception:
            kc_eq = 100_000.0
        insert_equity_snapshot(
            alpaca_equity=alpaca_equity,
            kraken_equity=kraken_equity,
            regime=regime,
            source="pipeline",
            options_equity=options_eq,
            forex_equity=forex_eq,
            poseidon_equity=poseidon_eq,
            kraken_current_equity=kc_eq,
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
    if result.get("algo_scanner"):
        _state["last_algo_scanner"] = result["algo_scanner"]
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
