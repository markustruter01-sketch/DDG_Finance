"""Control routes: postmortem, kill switch, emergency, auto-trading, system restart.
POST /run (the retired LLM pipeline) was removed 2 Nov 2026 (FLEET-V1-LIVE-SPEC.md section 5)."""

from __future__ import annotations

import asyncio
import json as _json
from datetime import datetime, timezone
from pathlib import Path as _Path

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

from core.pipeline import get_last_run, run_postmortem, reset_error_state
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
    VAULT_TICKER_PROTECTED,
    _commentary_cache,
)

control_router = APIRouter()

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


@control_router.post("/run/postmortem", tags=["Control"])
async def manual_postmortem() -> dict:
    logger.info("Manual post-mortem requested")
    postmortem_result = await run_postmortem()

    return postmortem_result


@control_router.post("/kill", tags=["Risk"])
async def trip_kill_switch() -> dict:
    logger.warning("Kill switch MANUALLY tripped via API")
    # manual_trip pauses every bot, then reads the brokers to cancel pending
    # orders; run it off the event loop so the API keeps answering meanwhile.
    result = await asyncio.to_thread(ks_manual_trip, reason="manual_api_trip")
    return {
        "status": "tripped",
        "cancelled_orders": result.get("cancelled", 0),
        "action": result.get("action"),
        "kill_switch": ks_get_state(),
    }


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


@control_router.get("/forex-ai/kill", tags=["Risk"])
async def forex_ai_kill_status() -> dict:
    from core.forex_ai_kill import ai_kill_state
    return await asyncio.to_thread(ai_kill_state)


@control_router.post("/forex-ai/kill", tags=["Risk"])
async def forex_ai_kill_on(reason: str = "operator_manual") -> dict:
    """Turn off every Forex AI call. No orders are touched."""
    from core.forex_ai_kill import ai_kill_state, set_ai_kill
    try:
        await asyncio.to_thread(set_ai_kill, True, reason)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"kill switch not written: {exc}")
    return await asyncio.to_thread(ai_kill_state)


@control_router.post("/forex-ai/kill/clear", tags=["Risk"])
async def forex_ai_kill_off(reason: str = "operator_manual") -> dict:
    from core.forex_ai_kill import ai_kill_state, set_ai_kill
    try:
        await asyncio.to_thread(set_ai_kill, False, reason)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"kill switch not written: {exc}")
    return await asyncio.to_thread(ai_kill_state)


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


@control_router.get("/bots/pause-state")
async def bots_pause_state() -> dict:
    """Uncached pause switch per active bot, read straight from bots_state.

    A missing row is reported as paused=None (the runner treats it as
    paused); an unreadable database is a 503, never a guess.
    """
    from core.bot_registry import active_bot_ids

    def read() -> dict:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT bot_id, paused, pause_reason, paused_at FROM bots_state "
                    "WHERE bot_id = ANY(%s)",
                    (list(active_bot_ids()),),
                )
                rows = {r[0]: r for r in cur.fetchall()}
        bots = []
        for bot_id in active_bot_ids():
            row = rows.get(bot_id)
            bots.append({
                "bot_id": bot_id,
                "paused": None if row is None else bool(row[1]),
                "pause_reason": row[2] if row else "no bots_state row (runner treats as paused)",
                "paused_at": row[3].isoformat() if row and row[3] else None,
            })
        return {"bots": bots, "kill_switch_tripped": bool(ks_get_state().get("tripped"))}

    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"pause state unreadable: {exc}")


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
    """Resume any bot by bot_id — writes bots_state.paused = false.

    Refused while the kill switch is tripped: a trip pauses every bot, and
    only a confirmed reset may lift that.
    """
    from core.bot_state import set_paused
    if is_tripped():
        raise HTTPException(
            status_code=409,
            detail="Kill switch is tripped. Reset it with the confirmation token before resuming bots.",
        )
    try:
        set_paused(bot_id, paused=False, reason="")
        return {"bot_id": bot_id, "paused": False}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"resume failed: {exc}")
