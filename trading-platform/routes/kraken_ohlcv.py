"""Historical Kraken OHLCV ingestion endpoints.

Kept separate from the retired Kraken bot analytics/control routes so the
public historical-price data utility can be maintained independently.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from loguru import logger

router = APIRouter()


@router.get("/kraken/ohlcv/status", tags=["Historical Data"])
async def kraken_ohlcv_status() -> dict:
    try:
        from analysis.ingest_kraken_ohlcv import get_coverage_status
        coverage = get_coverage_status()
        return {
            "status": "ok",
            "total_candles": sum(r["total_candles"] for r in coverage),
            "coverage": coverage,
            "note": (
                "1d timeframe: ~720 daily candles ≈ 2 years. "
                "1h timeframe: ~720 hourly candles ≈ 30 days."
            ),
        }
    except Exception as exc:
        logger.error(f"OHLCV Status | Error: {exc}")
        return {"status": "error", "error": str(exc)}


@router.post("/kraken/ohlcv/ingest", tags=["Historical Data"])
async def kraken_ohlcv_ingest(
    pairs: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> dict:
    try:
        from analysis.ingest_kraken_ohlcv import (
            run_ingest, PAIRS as all_pairs, TIMEFRAMES as all_timeframes,
        )
        pairs_cfg = [p for p in all_pairs if not pairs or p["display"] in pairs]
        tfs_cfg = [t for t in all_timeframes if not timeframes or t["label"] in timeframes]
        logger.info(
            "OHLCV | Manual ingest triggered via API — "
            f"pairs={[p['display'] for p in pairs_cfg]}"
        )
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: run_ingest(pairs_cfg, tfs_cfg)
        )
        summary = []
        for key, result in results.items():
            if "error" in result:
                summary.append({"key": key, "status": "error", "error": result["error"]})
                continue
            rng = result.get("range")
            summary.append({
                "key": key,
                "status": "ok",
                "pair": result.get("pair"),
                "timeframe": result.get("timeframe"),
                "fetched": result.get("fetched", 0),
                "inserted": result.get("inserted", 0),
                "total": result.get("total", 0),
                "from": rng[0] if rng else None,
                "to": rng[1] if rng else None,
            })
        return {
            "status": "ok",
            "total_inserted": sum(
                r.get("inserted", 0) for r in results.values() if "error" not in r
            ),
            "results": summary,
        }
    except Exception as exc:
        logger.error(f"OHLCV Ingest | Error: {exc}")
        return {"status": "error", "error": str(exc)}