"""Forex engine routes (The Navigator, Bot #6)."""

from __future__ import annotations

import os
import sys

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from routes._deps import _get_forex_engine, _get_forex_db

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

forex_router = APIRouter()


@forex_router.get("/forex/state")
async def forex_state():
    fx = _get_forex_engine()
    if fx is None:
        return {
            "status": "not_started",
            "paused": False,
            "cycle_count": 0,
            "usd_bias": "NEUTRAL",
            "news_blackout": False,
            "paper_mode": True,
            "paper_equity": 100000.0,
            "total_equity": 100000.0,
            "position_count": 0,
            "total_trades": 0,
            "total_wins": 0,
            "total_pnl": 0.0,
            "hwm_usd": 100000.0,
            "vault_total_usd": 0.0,
            "error": None,
        }
    return fx.get_state()


@forex_router.get("/forex/positions")
async def forex_positions():
    fx = _get_forex_engine()
    if fx is None:
        return {"positions": [], "count": 0}
    positions = fx.get_positions()
    return {"positions": positions, "count": len(positions)}


@forex_router.get("/forex/trades")
async def forex_trades():
    fxdb = _get_forex_db()
    if fxdb is None:
        return {"trades": [], "count": 0}
    trades = fxdb.load_recent_trades(limit=50)
    return {"trades": trades, "count": len(trades)}


@forex_router.get("/forex/journal")
async def forex_journal():
    try:
        import importlib.util as _ilu_j
        _fx_path = os.path.join(_REPO_ROOT, "forex-engine")
        spec = _ilu_j.spec_from_file_location("forex_journal", os.path.join(_fx_path, "journal.py"))
        mod = _ilu_j.module_from_spec(spec)
        spec.loader.exec_module(mod)
        entries = mod.get_journal_entries(limit=50)
        stats = mod.get_journal_stats()
        return {"entries": entries, "stats": stats, "count": len(entries)}
    except Exception:
        return {"entries": [], "stats": {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0, "avg_pips": 0}, "count": 0}


@forex_router.get("/forex/vault")
async def forex_vault():
    fxdb = _get_forex_db()
    if fxdb is None:
        return {"vault_total_usd": 0, "sweeps": []}
    try:
        sweeps = fxdb.load_vault_history()
    except Exception:
        sweeps = []
    fx = _get_forex_engine()
    vault_total = 0
    if fx:
        state = fx.get_state()
        vault_total = state.get("vault_total_usd", 0)
    return {"vault_total_usd": vault_total, "sweeps": sweeps}


@forex_router.post("/forex/toggle")
async def forex_toggle():
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    state = fx.get_state()
    if state.get("paused"):
        fx.resume_bot()
        return {"paused": False, "message": "Navigator resumed"}
    else:
        fx.pause_bot()
        return {"paused": True, "message": "Navigator paused"}


@forex_router.post("/forex/pause")
async def forex_pause():
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    fx.pause_bot()
    return {"paused": True, "message": "Navigator paused"}


@forex_router.post("/forex/resume")
async def forex_resume():
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    fx.resume_bot()
    return {"paused": False, "message": "Navigator resumed"}


@forex_router.post("/forex/scan")
async def forex_manual_scan(background_tasks: BackgroundTasks):
    fx = _get_forex_engine()
    if fx is None:
        raise HTTPException(status_code=503, detail="Forex engine not loaded")
    background_tasks.add_task(fx.run_cycle)
    return {"status": "forex_scan_queued"}
