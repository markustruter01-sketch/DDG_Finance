"""2027 predictions (twins/predictions.py): GET /predictions, POST /predictions
(Markus files his), POST /predictions/ask-council (the three AI members file theirs).
Locked at the start of 2027. No orders."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

predictions_router = APIRouter()


class Entry(BaseModel):
    thesis: str = Field(max_length=4000)
    forecasts: dict[str, Any]


def _levels() -> dict[str, Any]:
    """Latest close and change over the last year for every market (read-only fetches)."""
    from twins import league, predictions
    from twins.prices import alpaca_daily
    now = datetime.now(timezone.utc)
    etfs = [k for k in predictions.MARKETS if "_" not in k]
    bars = alpaca_daily(etfs, date.today() - timedelta(days=400), now)
    from research_harness.league.forex import bars_from_daily_candles
    fx = bars_from_daily_candles(league.oanda_daily([k for k in predictions.MARKETS if "_" in k]))
    out = {}
    for key in predictions.MARKETS:
        rows = bars.get(key) or fx.get(key, [])
        closes = [r["close"] for r in rows if r.get("close")]
        if closes:
            year_ago = closes[-253] if len(closes) > 252 else closes[0]
            out[key] = {"close": round(closes[-1], 5), "change_1y_pct": round(100 * (closes[-1] / year_ago - 1), 2)}
    return out


@predictions_router.get("/predictions", tags=["Predictions"])
async def predictions_read() -> dict[str, Any]:
    def read():
        from db.postgres import get_conn
        from twins import predictions
        return predictions.read(get_conn)
    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.error(f"predictions | read failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="predictions unavailable")


@predictions_router.post("/predictions", tags=["Predictions"])
async def predictions_file(body: Entry) -> dict[str, Any]:
    def write():
        from db.postgres import get_conn
        from twins import predictions
        return predictions.file(get_conn, datetime.now(timezone.utc), author="Markus", thesis=body.thesis,
                                forecasts=body.forecasts)
    try:
        return await asyncio.to_thread(write)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@predictions_router.post("/predictions/ask-council", tags=["Predictions"])
async def predictions_ask_council() -> dict[str, Any]:
    from data.fred_client import fetch_macro_data
    try:
        macro = await fetch_macro_data(lookback_days=120)
        macro_now = {v["name"]: {"value": v["value"], "date": v["date"]} for v in macro.values() if v.get("value") is not None}
    except Exception as exc:
        logger.warning(f"predictions | FRED unavailable: {type(exc).__name__}: {exc}")
        macro_now = {}

    def run():
        from db.postgres import get_conn
        from twins import predictions
        return predictions.ask_council(get_conn, datetime.now(timezone.utc), _levels(), macro_now)
    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        logger.error(f"predictions | council failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="council unavailable")
