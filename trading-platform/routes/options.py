"""Options engine routes (Apex Predator, Bot #5)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

import options_engine as _opts

options_router = APIRouter()


@options_router.get("/options/state")
async def options_state():
    return _opts.get_full_state()


@options_router.get("/options/positions")
async def options_positions():
    positions = _opts._get_positions()
    for pos in positions:
        pos["max_loss_pct"] = _opts.MAX_LOSS_PCT
        pos["profit_target_pct"] = _opts.PROFIT_TARGET_PCT
        expiry = (pos.get("call") or {}).get("expiry") or (pos.get("put") or {}).get("expiry")
        pos["dte_remaining"] = _opts._compute_dte(expiry) if expiry else None
        tc = pos.get("total_cost", 0)
        cv = pos.get("current_value", tc)
        pos["unrealized_pnl_pct"] = ((cv - tc) / tc * 100) if tc > 0 else 0.0
    return {"positions": positions, "count": len(positions)}


@options_router.get("/options/pending")
async def options_pending():
    pending = _opts._get_pending()
    return {"pending": pending, "count": len(pending)}


class _OptionsApproveReq(BaseModel):
    trade_id: str


@options_router.post("/options/approve")
async def options_approve(req: _OptionsApproveReq):
    result = _opts.approve_trade(req.trade_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@options_router.post("/options/reject")
async def options_reject(req: _OptionsApproveReq):
    result = _opts.reject_trade(req.trade_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@options_router.post("/options/toggle")
async def options_toggle():
    return _opts.toggle_pause()


@options_router.post("/options/scan")
async def options_manual_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(_opts.scan_for_setups)
    return {"status": "scan_queued"}


@options_router.post("/options/close")
async def options_close_position(req: _OptionsApproveReq):
    result = _opts.close_position_by_id(req.trade_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
