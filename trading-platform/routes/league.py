"""Shadow League leaderboard (roadmap Phase 1). Read-only: GET /league/leaderboard.

All figures come from twins/leaderboard.py; the browser only formats them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

league_router = APIRouter()


@league_router.get("/league/leaderboard", tags=["League"])
async def league_leaderboard() -> dict[str, Any]:
    def read() -> dict[str, Any]:
        from db.postgres import get_conn
        from twins import leaderboard
        return leaderboard.read(get_conn)

    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.error(f"league | leaderboard read failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="leaderboard unavailable")
