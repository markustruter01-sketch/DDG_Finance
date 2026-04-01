"""Control routes: run, postmortem, rebalance, kill switch, emergency, auto-trading, system restart."""

from __future__ import annotations

import asyncio
import os

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
    _sync_kraken_trades_to_journal,
)

control_router = APIRouter()


class RunRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    crypto_only: bool = False


class KillResetRequest(BaseModel):
    opening_equity: float | None = None


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

    try:
        kraken_sync = _sync_kraken_trades_to_journal()
        postmortem_result["kraken_journal_sync"] = kraken_sync
    except Exception as _ksync_exc:
        logger.error(f"Kraken journal sync failed: {_ksync_exc}")
        postmortem_result["kraken_journal_sync"] = {"error": str(_ksync_exc), "imported": 0}

    try:
        from db.postgres import insert_equity_snapshot as _ins_snap, is_pg_available as _pg_ok
        if _pg_ok():
            _k_equity = 0.0
            try:
                import psycopg2 as _pg2pm
                _dburlpm = os.environ.get("DATABASE_URL")
                if _dburlpm:
                    _pmconn = _pg2pm.connect(_dburlpm)
                    try:
                        with _pmconn.cursor() as _pmc:
                            _pmc.execute("SELECT COALESCE(SUM(equity_usd), 0) FROM kraken_heartbeat")
                            _pmrow = _pmc.fetchone()
                            if _pmrow:
                                _k_equity = float(_pmrow[0] or 0)
                    finally:
                        _pmconn.close()
            except Exception:
                pass
            try:
                from execution.broker import get_account as _ga2
                _a_equity = float(_ga2().get("equity", 0) or 0)
            except Exception:
                _a_equity = 0.0
            _o_equity = 0.0
            try:
                import importlib as _il_pm
                _opts_pm = _il_pm.import_module("options_engine")
                _o_equity = float(_opts_pm.get_state().get("paper_equity", 0))
            except Exception:
                pass
            _f_equity = 0.0
            try:
                from routes._deps import _get_forex_engine as _gfx_pm
                _fx_pm = _gfx_pm()
                if _fx_pm:
                    _f_equity = float(_fx_pm.get_state().get("paper_equity", 0))
            except Exception:
                pass
            _ins_snap(
                alpaca_equity=_a_equity, kraken_equity=_k_equity, source="postmortem",
                options_equity=_o_equity, forex_equity=_f_equity,
            )
            logger.info(f"Postmortem equity snapshot: alpaca={_a_equity:.2f} kraken={_k_equity:.2f} options={_o_equity:.2f} forex={_f_equity:.2f}")
    except Exception as _snap2_exc:
        logger.warning(f"Postmortem equity snapshot failed (non-fatal): {_snap2_exc}")

    return postmortem_result


@control_router.post("/rebalance", tags=["Control"])
async def force_rebalance() -> dict:
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
        except Exception as exc:
            logger.error(f"Rebalance | Failed to close {sym}: {exc}")
            errors.append({"symbol": sym, "error": str(exc)})

    logger.info(
        f"Rebalance | Closed {len(closed)} positions, "
        f"held {len(held)}, errors {len(errors)}"
    )

    crypto_only = not market_open
    pipeline_result = await run_pipeline(force=True, dry_run=False, crypto_only=crypto_only)

    return {
        "status": "ok",
        "closed": closed,
        "held": held,
        "errors": errors,
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
    ks_reset(opening_equity=request.opening_equity)
    return {"status": "reset", "kill_switch": ks_get_state()}


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

    return {
        "status": "emergency_liquidated",
        "closed": closed,
        "held": held,
        "errors": errors,
        "kill_switch": ks_get_state(),
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
