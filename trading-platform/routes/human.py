"""Markus's own pretend account (twins/human.py): GET /human/catalog,
GET /human/account, POST /human/trade. Writes only pretend decisions: no orders."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

human_router = APIRouter()
_members: dict[str, Any] = {"day": None, "list": []}


def _sp500() -> list[str]:
    """Today's S&P 500 members, read once a day (SSGA, iShares fallback)."""
    if _members["day"] != date.today() or not _members["list"]:
        from twins import league
        tickers, _, _ = league.load_universe()
        _members.update(day=date.today(), list=sorted(tickers))
    return _members["list"]


class Trade(BaseModel):
    asset: str = Field(max_length=16)
    side: str = Field(pattern="^(buy|sell)$")
    percent: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=500)


@human_router.get("/human/catalog", tags=["Human"])
async def human_catalog() -> dict[str, Any]:
    def read() -> dict[str, Any]:
        from twins import human
        try:
            members = _sp500()
        except Exception as exc:
            logger.warning(f"human | S&P 500 list unavailable: {type(exc).__name__}: {exc}")
            members = []
        return {"classes": human.catalog(members), "shares_available": bool(members)}
    return await asyncio.to_thread(read)


@human_router.get("/human/account", tags=["Human"])
async def human_account() -> dict[str, Any]:
    def read() -> dict[str, Any]:
        from db.postgres import get_conn
        from twins import human
        return human.account(get_conn)
    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.error(f"human | account read failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="account unavailable")


@human_router.post("/human/trade", tags=["Human"])
async def human_trade(body: Trade) -> dict[str, Any]:
    def write() -> dict[str, Any]:
        from db.postgres import get_conn
        from twins import human
        members = _sp500() if body.asset not in {a for c in human.catalog([]) for a in
                                                  (x["symbol"] for x in c["assets"])} else []
        return human.trade(get_conn, datetime.now(timezone.utc), asset=body.asset, side=body.side,
                           percent=body.percent, reason=body.reason, members=members)
    try:
        return await asyncio.to_thread(write)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"human | trade failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="trade not recorded")
