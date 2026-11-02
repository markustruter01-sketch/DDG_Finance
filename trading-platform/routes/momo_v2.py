"""MOMO-V2 dashboard API (research_harness/explore/MOMO-V2-PLAN.md, "Live build").

Read-only: every figure is the runtime's own state (bots_state.metadata,
written by sleeve_runtime/momo_live.py); the browser only formats it.

- GET /momo-v2/state   the 50 names, the brakes, targets, drawdown, return vs SPY
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

import routes._deps  # noqa: F401  (puts the repo root on sys.path for sleeve_runtime)

momo_v2_router = APIRouter()
BOT_ID = "spy_qqq_trend"


def state_view(st: dict[str, Any]) -> dict[str, Any]:
    """Pure: the dashboard's fields from the runtime's state."""
    from routes.fleet_v1 import since_cutover

    dd = st.get("drawdown") or {}
    targets = st.get("targets") or {}
    return {
        "bot_id": BOT_ID,
        "registration": "MOMO-V2",
        "role": "Forward-only experiment: 50 S&P 500 stocks by 12-1 momentum, brakes on the book",
        "month": st.get("month"),
        "selection_day": st.get("selection_day"),
        "universe_source": st.get("universe_source"),
        "names": st.get("names") or [],
        "targets": targets,
        "held": st.get("held"),
        "why": st.get("why"),
        "trend_on": st.get("trend_on"),
        "invested_fraction": st.get("s"),
        "book_index": st.get("index"),
        "book_sma100": st.get("sma100"),
        "book_vol20": st.get("vol20"),
        "stopped": st.get("stopped") or [],
        "skipped_unaffordable": st.get("skipped_unaffordable") or [],
        "last_rebalance_key": st.get("key"),
        "last_rebalance_at": st.get("at"),
        "last_rebalance_done": st.get("done"),
        "attempts": st.get("attempts"),
        "errors": st.get("errors") or [],
        "since_cutover": since_cutover(st),
        "drawdown": {"mode": dd.get("mode", "normal"), "halted": bool(dd.get("halted")),
                     "drawdown": dd.get("drawdown"), "high_water_mark": dd.get("hwm"),
                     "as_of": dd.get("as_of"), "error": dd.get("error")},
    }


@momo_v2_router.get("/momo-v2/state", tags=["MOMO-V2"])
async def momo_v2_state() -> dict[str, Any]:
    def read() -> dict[str, Any]:
        from core.bot_state import read_metadata
        from sleeve_runtime.momo_live import STATE_KEY

        return state_view((read_metadata(BOT_ID) or {}).get(STATE_KEY, {}) or {})

    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.error(f"MOMO-V2 | state read failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail=f"MOMO-V2 state unreadable: {type(exc).__name__}")
