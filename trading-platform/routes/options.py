"""
Options routes — DECOMMISSIONED.

Apex Predator (Bot #5) has been converted from an options volatility engine
to a 24/7 crypto momentum scalper running on Kraken (BOT_ID=apex-predator).
These endpoints now return a 410 Gone response so any stale callers fail
explicitly rather than silently.
"""

from fastapi import APIRouter, HTTPException

options_router = APIRouter()

_GONE_MSG = (
    "Apex Predator options engine has been decommissioned. "
    "Bot #5 now runs as a crypto momentum scalper (BOT_ID=apex-predator) "
    "via the Kraken pool. Use /kraken/* endpoints instead."
)


@options_router.get("/options/state")
async def options_state():
    raise HTTPException(status_code=410, detail=_GONE_MSG)


@options_router.get("/options/positions")
async def options_positions():
    raise HTTPException(status_code=410, detail=_GONE_MSG)


@options_router.get("/options/pending")
async def options_pending():
    raise HTTPException(status_code=410, detail=_GONE_MSG)


@options_router.post("/options/approve")
async def options_approve():
    raise HTTPException(status_code=410, detail=_GONE_MSG)


@options_router.post("/options/reject")
async def options_reject():
    raise HTTPException(status_code=410, detail=_GONE_MSG)


@options_router.post("/options/toggle")
async def options_toggle():
    raise HTTPException(status_code=410, detail=_GONE_MSG)


@options_router.post("/options/scan")
async def options_scan():
    raise HTTPException(status_code=410, detail=_GONE_MSG)
