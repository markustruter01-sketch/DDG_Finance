"""Single source of truth: GET /fleet/equity aggregates equity & P&L for all 9 bots."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from fastapi import APIRouter
from loguru import logger

fleet_equity_router = APIRouter()

_STARTING = 100_000.0
_CACHE_TTL = 30  # seconds

_cache: dict = {"data": None, "ts": 0.0}




def _fetch_fleet_equity() -> dict:
    """
    Primary path: read all bot portfolios from bot_portfolio in a single query.
    Raises on failure — route handler converts to HTTP 503.
    """
    try:
        from core.bot_state import get_all_portfolios
        portfolios = get_all_portfolios()  # 9 rows in one query

        if not portfolios:
            raise RuntimeError("bot_portfolio returned empty — falling back")

        result: dict = {}
        for p in portfolios:
            bot_id = p["bot_id"]
            eq      = float(p["equity_usd"] or _STARTING)
            start   = float(p["starting_usd"] or _STARTING)
            cash    = float(p["cash_usd"] or 0.0)
            pos_raw = p.get("positions") or []
            pos_count = len(pos_raw) if isinstance(pos_raw, list) else 0
            pnl     = eq - start
            pnl_pct = round((pnl / start) * 100, 4) if start else 0.0
            upd     = p.get("last_updated")

            result[bot_id] = {
                "equity":    round(eq, 2),
                "starting":  round(start, 2),
                "cash":      round(cash, 2),
                "pnl":       round(pnl, 2),
                "pnl_pct":   pnl_pct,
                "positions": pos_count,
                "source":    "bot_portfolio",
                "last_updated": upd if isinstance(upd, str) else (upd.isoformat() if upd else None),
            }

        # Merge paused state from bots_state
        try:
            from core.bot_state import get_all_states
            states = {s["bot_id"]: s for s in get_all_states()}
            for bid, data in result.items():
                data["paused"] = bool(states.get(bid, {}).get("paused", False))
        except Exception as _exc:
            logger.debug(f"fleet_equity | paused merge failed: {_exc}")
            for data in result.values():
                data.setdefault("paused", False)

        # Fleet totals
        _meta_keys = {"fleet_total", "generated_at", "errors"}
        _bot_vals  = [v for k, v in result.items() if k not in _meta_keys]

        fleet_eq      = sum(b["equity"]    for b in _bot_vals)
        fleet_start   = sum(b["starting"]  for b in _bot_vals)
        fleet_pnl     = sum(b["pnl"]       for b in _bot_vals)
        fleet_pos     = sum(b["positions"] for b in _bot_vals)
        fleet_pnl_pct = round((fleet_pnl / fleet_start) * 100, 4) if fleet_start else 0.0

        result["fleet_total"] = {
            "equity":    round(fleet_eq, 2),
            "starting":  round(fleet_start, 2),
            "cash":      round(sum(b.get("cash", 0) for b in _bot_vals), 2),
            "pnl":       round(fleet_pnl, 2),
            "pnl_pct":   fleet_pnl_pct,
            "positions": fleet_pos,
            "source":    "computed",
        }
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        result["errors"] = []
        return result

    except Exception as exc:
        logger.error(f"fleet_equity unified path failed: {exc}", exc_info=True)
        raise




@fleet_equity_router.get("/fleet/equity")
async def fleet_equity():
    """Return consistent equity & P&L for all 9 bots. 30-second server-side cache."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    try:
        data = _fetch_fleet_equity()
    except Exception as exc:
        logger.error(f"[fleet/equity] Primary path failed: {exc}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="fleet_equity unavailable — bot_portfolio read failed")

    _cache["data"] = data
    _cache["ts"] = now
    return data
