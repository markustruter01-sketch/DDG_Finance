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
    _sync_kraken_trades_to_journal,
)

control_router = APIRouter()

KRAKEN_FEE_PCT = 0.0026

_KRAKEN_BOTS = {
    "davy-jones": 1,
    "blackbeard": 2,
    "calypso":    3,
}


def _liquidate_kraken_positions() -> dict:
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return {"closed": [], "errors": [{"bot": "all", "error": "database_unavailable"}]}

    live_prices: dict[str, float] = {}
    for bid in _KRAKEN_BOTS:
        lsf = _Path(f"../kraken-bot/{bid}_live_state.json")
        if not lsf.exists() and bid == "davy-jones":
            lsf = _Path("../kraken-bot/live_state.json")
        try:
            if lsf.exists():
                ls = _json.loads(lsf.read_text())
                for op in ls.get("open_positions", []):
                    sym = op.get("symbol")
                    price = op.get("current_price") or op.get("mark_price")
                    if sym and price:
                        live_prices[sym] = float(price)
        except Exception:
            pass

    closed = []
    errors = []

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_text_id, db_id in _KRAKEN_BOTS.items():
                    cur.execute(
                        "SELECT cash_usd, positions FROM kraken_portfolio WHERE id = %s",
                        (db_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        continue

                    cash_usd, pos_raw = row
                    if isinstance(pos_raw, str):
                        pos_raw = _json.loads(pos_raw)
                    if not isinstance(pos_raw, dict) or not pos_raw:
                        continue

                    symbols_to_close = list(pos_raw.keys())
                    for symbol in symbols_to_close:
                        pos = pos_raw[symbol]
                        try:
                            entry_price = float(pos.get("entry_price", 0))
                            size_units = float(pos.get("size_units", 0))
                            size_usd = float(pos.get("size_usd", 0))
                            side = pos.get("side", "long")
                            entry_fee = float(pos.get("entry_fee", 0))

                            current_price = live_prices.get(symbol, entry_price)

                            exit_value = size_units * current_price
                            exit_fee = exit_value * KRAKEN_FEE_PCT
                            net_value = exit_value - exit_fee

                            if side == "long":
                                pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0
                            else:
                                pnl_pct = ((entry_price - current_price) / entry_price) * 100 if entry_price else 0

                            gross_pnl_usd = size_usd * (pnl_pct / 100)
                            total_fees = entry_fee + exit_fee
                            net_pnl_usd = gross_pnl_usd - total_fees

                            cash_usd += net_value

                            now_iso = datetime.now(tz=timezone.utc).isoformat()
                            cur.execute(
                                """
                                INSERT INTO kraken_trades
                                    (bot_id, symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                                     fees_usd, reason, closed_at, paper, order_id)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                                """,
                                (
                                    bot_text_id,
                                    symbol,
                                    side,
                                    entry_price,
                                    current_price,
                                    round(pnl_pct, 2),
                                    round(net_pnl_usd, 2),
                                    round(total_fees, 4),
                                    "rebalance_liquidation",
                                    now_iso,
                                    pos.get("order_id"),
                                ),
                            )

                            del pos_raw[symbol]

                            closed.append({
                                "bot": bot_text_id,
                                "symbol": symbol,
                                "side": side,
                                "pnl_pct": round(pnl_pct, 2),
                                "pnl_usd": round(net_pnl_usd, 2),
                            })

                            logger.info(
                                f"Rebalance | Kraken {bot_text_id} closed {side.upper()} {symbol} "
                                f"@ ${current_price:,.4f} | P&L: {pnl_pct:+.2f}% (${net_pnl_usd:+,.2f})"
                            )

                        except Exception as exc:
                            logger.error(f"Rebalance | Failed to close Kraken {bot_text_id} {symbol}: {exc}")
                            errors.append({"bot": bot_text_id, "symbol": symbol, "error": str(exc)})

                    cur.execute(
                        "UPDATE kraken_portfolio SET cash_usd = %s, positions = %s, pending_tranches = '{}' WHERE id = %s",
                        (cash_usd, _json.dumps(pos_raw, default=str), db_id),
                    )

    except Exception as exc:
        logger.error(f"Rebalance | Kraken liquidation DB error: {exc}")
        errors.append({"bot": "all", "error": str(exc)})

    for bid in _KRAKEN_BOTS:
        ctrl_path = _Path(f"../kraken-bot/{bid}_control.json")
        try:
            ctrl_data = {}
            if ctrl_path.exists():
                ctrl_data = _json.loads(ctrl_path.read_text())
            ctrl_data["force_reload"] = True
            ctrl_path.write_text(_json.dumps(ctrl_data, indent=2))
            logger.info(f"Rebalance | Set force_reload flag for {bid}")
        except Exception as exc:
            logger.warning(f"Rebalance | Could not set force_reload for {bid}: {exc}")

    logger.info(f"Rebalance | Kraken: closed {len(closed)} positions, {len(errors)} errors")
    return {"closed": closed, "errors": errors}


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
    closed = []
    errors = []
    try:
        import importlib as _il
        opts = _il.import_module("options_engine")
        positions = opts._get_positions()
        if not positions:
            return {"closed": [], "errors": []}

        for pos in positions:
            pos_id = pos.get("id")
            symbol = pos.get("symbol", "?")
            try:
                result = opts.close_position_by_id(pos_id, exit_reason="rebalance_liquidation")
                if result and not result.get("error"):
                    closed.append({
                        "symbol": symbol,
                        "pnl": round(result.get("pnl", 0), 2),
                    })
                    logger.info(
                        f"Rebalance | Options closed {symbol} straddle | P&L: ${result.get('pnl', 0):+,.2f}"
                    )
                else:
                    err_msg = result.get("error", "unknown") if result else "no result"
                    errors.append({"symbol": symbol, "error": err_msg})
            except Exception as exc:
                logger.error(f"Rebalance | Options failed to close {symbol}: {exc}")
                errors.append({"symbol": symbol, "error": str(exc)})

    except Exception as exc:
        logger.error(f"Rebalance | Options liquidation error: {exc}")
        errors.append({"symbol": "all", "error": str(exc)})

    logger.info(f"Rebalance | Options: closed {len(closed)} positions, {len(errors)} errors")
    return {"closed": closed, "errors": errors}


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

    kraken_result = _liquidate_kraken_positions()
    kraken_closed = kraken_result.get("closed", [])
    kraken_errors = kraken_result.get("errors", [])

    forex_result = _liquidate_forex_positions()
    forex_closed = forex_result.get("closed", [])
    forex_errors = forex_result.get("errors", [])

    options_result = _liquidate_options_positions()
    options_closed = options_result.get("closed", [])
    options_errors = options_result.get("errors", [])

    logger.info(
        f"Rebalance | Alpaca: closed {len(closed)}, held {len(held)}, errors {len(errors)} | "
        f"Kraken: closed {len(kraken_closed)}, errors {len(kraken_errors)} | "
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
        "kraken_closed": kraken_closed,
        "kraken_errors": kraken_errors,
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
