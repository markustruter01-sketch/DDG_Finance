"""Control routes: run, postmortem, rebalance, kill switch, emergency, auto-trading, system restart."""

from __future__ import annotations

import asyncio
import json as _json
import os
from datetime import datetime, timezone
from pathlib import Path as _Path

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

from core.pipeline import get_last_run, run_pipeline, run_postmortem, reset_error_state
from core.scheduler import get_job_status, is_auto_trading_enabled, set_auto_trading
from core.market_clock import is_market_open
from execution.broker import get_account, get_positions, close_position, cancel_all_orders
from execution.kill_switch import (
    get_state as ks_get_state,
    is_tripped,
    reset as ks_reset,
    manual_trip as ks_manual_trip,
)
from execution.ratchet_stop import delete_stop

from routes._deps import (
    VAULT_TICKER,
    KNOWN_CRYPTO_SYMBOLS,
    VAULT_TICKER_PROTECTED,
    _commentary_cache,
)

control_router = APIRouter()

def _liquidate_forex_positions() -> dict:
    closed = []
    errors = []
    try:
        import importlib.util as _ilu
        import sys as _sys
        _fx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "forex-engine")
        if _fx_path not in _sys.path:
            _sys.path.insert(0, _fx_path)

        spec_pe = _ilu.spec_from_file_location("paper_engine_fx", os.path.join(_fx_path, "paper_engine.py"))
        pe = _ilu.module_from_spec(spec_pe)
        spec_pe.loader.exec_module(pe)

        raw_positions = pe.get_paper_positions()
        if not raw_positions:
            return {"closed": [], "errors": []}

        from routes._deps import _get_forex_engine
        fx = _get_forex_engine()
        latest_prices = {}
        if fx:
            labeled_positions = fx.get_positions()
            spec_cfg = _ilu.spec_from_file_location("forex_config_liq", os.path.join(_fx_path, "forex_config.py"))
            cfg = _ilu.module_from_spec(spec_cfg)
            spec_cfg.loader.exec_module(cfg)
            label_to_raw = {v: k for k, v in cfg.PAIR_LABELS.items()}
            for lp in labeled_positions:
                label = lp["pair"]
                raw_key = label_to_raw.get(label, label)
                latest_prices[raw_key] = lp["current_price"]

        for pair, pos in list(raw_positions.items()):
            current_price = latest_prices.get(pair, pos.get("entry_price", 0))
            direction = pos.get("direction", "long")
            try:
                result = pe.paper_close_position(pair, current_price, "rebalance_liquidation",
                                                  latest_prices=latest_prices)
                if result:
                    closed.append({
                        "pair": pair,
                        "direction": direction,
                        "pnl_usd": round(result.get("pnl_usd", 0), 2),
                    })
                    logger.info(
                        f"Rebalance | Forex closed {direction.upper()} {pair} "
                        f"@ {current_price:.5f} | P&L: ${result.get('pnl_usd', 0):+,.2f}"
                    )
                else:
                    errors.append({"pair": pair, "error": "close returned None"})
            except Exception as exc:
                logger.error(f"Rebalance | Forex failed to close {pair}: {exc}")
                errors.append({"pair": pair, "error": str(exc)})

    except Exception as exc:
        logger.error(f"Rebalance | Forex liquidation error: {exc}")
        errors.append({"pair": "all", "error": str(exc)})

    logger.info(f"Rebalance | Forex: closed {len(closed)} positions, {len(errors)} errors")
    return {"closed": closed, "errors": errors}


def _liquidate_options_positions() -> dict:
    """Options engine retired — Apex Predator (Bot #5) now runs as Kraken crypto momentum.
    No options positions to liquidate; returns empty result immediately."""
    logger.info("Rebalance | Options engine retired — skipping options liquidation")
    return {"closed": [], "errors": []}


class RunRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    crypto_only: bool = False


class KillResetRequest(BaseModel):
    opening_equity: float | None = None
    confirmation_token: str


class KillAcknowledgementRequest(BaseModel):
    condition_key: str
    acknowledged_until: str
    acknowledged_by: str = "manual"
    reason: str | None = None


class AutoTradingRequest(BaseModel):
    enabled: bool


@control_router.post("/run", tags=["Control"])
async def manual_run(request: RunRequest, background_tasks: BackgroundTasks) -> dict:
    if is_tripped() and not request.force:
        raise HTTPException(
            status_code=409,
            detail="Kill switch is tripped. Pass force=true to override, or POST /kill/reset first.",
        )

    logger.info(f"Manual run requested: dry_run={request.dry_run} force={request.force}")
    result = await run_pipeline(force=request.force, dry_run=request.dry_run, crypto_only=request.crypto_only)
    return result


@control_router.post("/run/postmortem", tags=["Control"])
async def manual_postmortem() -> dict:
    logger.info("Manual post-mortem requested")
    postmortem_result = await run_postmortem()

    return postmortem_result


@control_router.post("/rebalance", tags=["Control"])
async def force_rebalance() -> dict:
    logger.warning("════════════════════════════════════════════════════════════")
    logger.warning("  FORCE REBALANCE — operator-initiated full liquidation")
    logger.warning("════════════════════════════════════════════════════════════")

    market_open = is_market_open()
    positions = get_positions()
    cancel_all_orders()

    closed = []
    held = []
    errors = []

    for pos in positions:
        sym = pos["symbol"]
        if sym == VAULT_TICKER:
            held.append({"symbol": sym, "reason": "vault_protected"})
            continue
        is_crypto = sym in KNOWN_CRYPTO_SYMBOLS
        if not is_crypto and not market_open:
            held.append({"symbol": sym, "reason": "market_closed"})
            continue
        try:
            order = close_position(sym)
            closed.append({"symbol": sym, "order": order})
            try:
                delete_stop(sym)
            except Exception:
                pass
            try:
                from analysis.trade_journal import close_trade
                pnl_pct = float(pos.get("unrealized_plpc", 0) or 0) * 100
                pnl_usd = float(pos.get("unrealized_pl", 0) or 0)
                close_trade(
                    ticker=sym,
                    pnl_percentage=pnl_pct,
                    exit_reason="rebalance_liquidation",
                    realized_pnl=pnl_usd,
                )
            except Exception as jexc:
                logger.debug(f"Rebalance | Journal close_trade for {sym} failed (non-fatal): {jexc}")
        except Exception as exc:
            logger.error(f"Rebalance | Failed to close {sym}: {exc}")
            errors.append({"symbol": sym, "error": str(exc)})

    forex_result = _liquidate_forex_positions()
    forex_closed = forex_result.get("closed", [])
    forex_errors = forex_result.get("errors", [])

    options_result = _liquidate_options_positions()
    options_closed = options_result.get("closed", [])
    options_errors = options_result.get("errors", [])

    logger.info(
        f"Rebalance | Alpaca: closed {len(closed)}, held {len(held)}, errors {len(errors)} | "
        f"Forex: closed {len(forex_closed)}, errors {len(forex_errors)} | "
        f"Options: closed {len(options_closed)}, errors {len(options_errors)}"
    )

    crypto_only = not market_open
    pipeline_result = await run_pipeline(force=True, dry_run=False, crypto_only=crypto_only)

    return {
        "status": "ok",
        "closed": closed,
        "held": held,
        "errors": errors,
        "forex_closed": forex_closed,
        "forex_errors": forex_errors,
        "options_closed": options_closed,
        "options_errors": options_errors,
        "market_open": market_open,
        "pipeline": pipeline_result,
    }


@control_router.post("/rebalance/{symbol}", tags=["Control"])
async def force_close_single(symbol: str) -> dict:
    sym = symbol.upper()

    if sym == VAULT_TICKER:
        raise HTTPException(status_code=400, detail="JEPQ vault position is protected and cannot be force-closed.")

    market_open = is_market_open()
    is_crypto = sym in KNOWN_CRYPTO_SYMBOLS

    if not is_crypto and not market_open:
        raise HTTPException(
            status_code=409,
            detail=f"{sym} is a stock/ETF position. Market is currently closed — cannot close until next session.",
        )

    try:
        order = close_position(sym)
    except Exception as exc:
        logger.error(f"Force-close {sym} | Failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to close {sym}: {str(exc)}")

    try:
        delete_stop(sym)
    except Exception:
        pass

    logger.info(f"Force-close {sym} | Closed. Running fresh pipeline to reallocate capital.")

    crypto_only = not market_open
    pipeline_result = await run_pipeline(force=True, dry_run=False, crypto_only=crypto_only)

    return {
        "status": "ok",
        "closed": sym,
        "order": order,
        "pipeline": pipeline_result,
    }


@control_router.post("/kill", tags=["Risk"])
async def trip_kill_switch() -> dict:
    logger.warning("Kill switch MANUALLY tripped via API")
    ks_manual_trip(reason="manual_api_trip")
    return {"status": "tripped", "kill_switch": ks_get_state()}


@control_router.post("/kill/reset", tags=["Risk"])
async def reset_kill_switch(request: KillResetRequest) -> dict:
    logger.info(f"Kill switch reset via API | opening_equity={request.opening_equity}")
    try:
        ks_reset(
            opening_equity=request.opening_equity,
            confirmation_token=request.confirmation_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {
        "status": "reset",
        "kill_switch": ks_get_state(),
        "procedure": "POST /trading-api/kill/reset with the server-configured confirmation token.",
    }


@control_router.get("/kill/report", tags=["Risk"])
async def kill_switch_report() -> dict:
    from execution.reconciliation import run_kill_switch_check
    return await asyncio.to_thread(run_kill_switch_check, report_only=True)


@control_router.get("/reconciliation/report", tags=["Risk"])
async def reconciliation_report() -> dict:
    from execution.reconciliation import reconcile
    return await asyncio.to_thread(reconcile, report_only=True)


@control_router.post("/kill/acknowledge", tags=["Risk"])
async def acknowledge_kill_condition(request: KillAcknowledgementRequest) -> dict:
    from core.kill_switch import acknowledge
    try:
        saved = await asyncio.to_thread(
            acknowledge,
            request.condition_key,
            request.acknowledged_until,
            request.acknowledged_by,
            request.reason,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "status": "acknowledged",
        "acknowledgement": saved,
        "expiry_behavior": "Condition is suppressed only until acknowledged_until, then alerts/trips again.",
    }


@control_router.post("/emergency/liquidate", tags=["Emergency"])
async def emergency_liquidate() -> dict:
    logger.critical("EMERGENCY LIQUIDATE triggered via API — closing all positions")

    try:
        cancel_all_orders()
        logger.info("Emergency | All open orders cancelled")
    except Exception as exc:
        logger.error(f"Emergency | cancel_all_orders failed: {exc}")

    positions = []
    try:
        positions = get_positions()
    except Exception as exc:
        logger.error(f"Emergency | Could not fetch positions: {exc}")

    closed: list[dict] = []
    held: list[dict] = []
    errors: list[dict] = []

    for pos in positions:
        sym = pos["symbol"]
        if sym in VAULT_TICKER_PROTECTED:
            held.append({"symbol": sym, "reason": "vault_protected"})
            continue
        try:
            order = close_position(sym)
            closed.append({"symbol": sym, "order_id": order.get("id")})
            try:
                delete_stop(sym)
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"Emergency | Failed to close {sym}: {exc}")
            errors.append({"symbol": sym, "error": str(exc)})

    ks_manual_trip(reason="emergency_liquidate")
    logger.warning(
        f"Emergency | Complete — closed {len(closed)}, "
        f"held {len(held)} (vault), errors {len(errors)}"
    )

    market_open = is_market_open()
    ks_state = ks_get_state()
    pending = ks_state.get("pending_liquidation", False)

    if market_open and not pending:
        fill_note = f"{len(closed)} position(s) closing — market is open, orders will fill shortly. Kill switch is active."
    else:
        fill_note = "Market is closed. Positions will be force-closed automatically when the market opens. Kill switch is active."

    return {
        "status": "emergency_liquidated",
        "positions_closed": closed,
        "positions_held": held,
        "errors": errors,
        "kill_switch": ks_state,
        "market_open": market_open,
        "pending_liquidation": pending,
        "fill_note": fill_note,
        "message": (
            f"Emergency liquidation complete — {len(closed)} closed, "
            f"{len(held)} vault-protected, {len(errors)} error(s)."
        ),
    }


@control_router.post("/system/restart", tags=["Emergency"])
async def system_restart() -> dict:
    logger.info("SYSTEM RESTART triggered via API — clearing error state and cache")

    new_state = reset_error_state()

    try:
        import data.yfinance_client as _yf
        _yf._cached_market_data = None
        logger.info("System restart | Market-data cache cleared")
    except Exception as exc:
        logger.warning(f"System restart | Could not clear market-data cache: {exc}")

    _commentary_cache.update({"text": None, "generated_at": None, "ts": 0})

    jobs = get_job_status()
    logger.info(f"System restart | Complete — scheduler has {len(jobs)} job(s)")

    return {
        "status": "restarted",
        "pipeline_state": new_state,
        "scheduler_jobs": len(jobs),
        "kill_switch": ks_get_state(),
        "message": (
            "Error state cleared and cache invalidated. "
            "System will resume on next scheduled cycle. "
            "NOTE: Kill switch state is unchanged — use POST /kill/reset if it was tripped."
        ),
    }


@control_router.get("/auto-trading", tags=["Control"])
async def auto_trading_status() -> dict:
    return {
        "auto_trading_enabled": is_auto_trading_enabled(),
        "jobs": get_job_status(),
    }


@control_router.post("/auto-trading", tags=["Control"])
async def toggle_auto_trading(request: AutoTradingRequest) -> dict:
    logger.info(f"Auto-trading toggle requested: enabled={request.enabled}")
    result = set_auto_trading(request.enabled)
    return result


@control_router.post("/fleet/halt")
async def fleet_halt_endpoint(reason: str = "operator_manual"):
    """Activate fleet-wide emergency halt — stops all new entries across all bots."""
    from core.fleet_halt import set_halt, get_status
    success = set_halt(True, reason=reason, halted_by="dashboard")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to write halt flag to DB")
    logger.warning(f"FLEET HALT ACTIVATED via API — reason: {reason}")
    return {"halted": True, "reason": reason, "status": get_status()}


@control_router.post("/fleet/resume")
async def fleet_resume_endpoint():
    """Clear fleet-wide emergency halt — resumes normal trading."""
    from core.fleet_halt import set_halt, get_status
    success = set_halt(False, reason="operator_resume", halted_by="dashboard")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to clear halt flag in DB")
    logger.info("Fleet halt cleared via API — trading resumed")
    return {"halted": False, "status": get_status()}


@control_router.get("/fleet/halt/status")
async def fleet_halt_status():
    """Return current fleet halt status."""
    from core.fleet_halt import get_status
    return get_status()


@control_router.post("/bots/{bot_id}/pause")
async def pause_bot_unified(bot_id: str, reason: str = ""):
    """Pause any bot by bot_id — writes bots_state.paused = true."""
    from core.bot_state import set_paused
    try:
        set_paused(bot_id, paused=True, reason=reason)
        return {"bot_id": bot_id, "paused": True, "reason": reason}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pause failed: {exc}")


@control_router.post("/bots/{bot_id}/resume")
async def resume_bot_unified(bot_id: str):
    """Resume any bot by bot_id — writes bots_state.paused = false."""
    from core.bot_state import set_paused
    try:
        set_paused(bot_id, paused=False, reason="")
        return {"bot_id": bot_id, "paused": False}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"resume failed: {exc}")
