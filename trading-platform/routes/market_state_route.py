"""
routes/market_state_route.py — Market State Engine API
--------------------------------------------------------
GET /trading-api/market-state

Returns the current MSE regime + the last 10 historical snapshots.

Regime values:
  BULL   — Normal trading conditions
  BEAR   — SPY below 200SMA (display only; no trading gate)
  CRISIS — SPY 20-day return <= -12% (validated trading gate, Pass C OOS)

HIGH_VOL flag: SPY 10-day realized vol > 30% annualised.

CRISIS trading rules (per-bot):
  Oracle      : block all new entries; TLT/GLD/IEF longs only (max 2, 0.5× size)
  SPY/QQQ     : block all new entries
  Jerome/Buck : block all new entries
  All bots    : exits never gated
"""
from __future__ import annotations

from fastapi import APIRouter
from loguru import logger
from core.bot_registry import display_label

router = APIRouter()


@router.get("/market-state", tags=["Market State"])
async def get_market_state_endpoint() -> dict:
    """
    Current MSE regime + 10 most recent historical snapshots.

    Fast (~1 ms): reads from the same yfinance momentum cache that Oracle
    already uses every cycle, so there is no additional data fetch.
    """
    import asyncio
    from core.market_state import (
        MSE_CRISIS_THRESHOLD,
        MSE_HIGH_VOL_ANN,
        MSE_SAFE_HAVENS,
        MSE_SAFE_HAVEN_MAX,
        MSE_HIGH_VOL_SCALE,
        get_market_state_with_history,
    )

    try:
        state = await asyncio.to_thread(get_market_state_with_history, 10)
    except Exception as exc:
        logger.warning(f"market_state endpoint: {exc}")
        state = {
            "regime": "UNKNOWN", "high_vol": False,
            "spy_close": None, "spy_20d_ret": None,
            "spy_200sma": None, "spy_10d_vol": None,
            "computed_at": None, "data_bars": 0,
            "error": str(exc), "history": [],
        }

    regime = state.get("regime", "UNKNOWN")

    return {
        **state,
        "meta": {
            "crisis_threshold":    MSE_CRISIS_THRESHOLD,
            "high_vol_ann_threshold": MSE_HIGH_VOL_ANN,
            "safe_havens":         sorted(MSE_SAFE_HAVENS),
            "safe_haven_max":      MSE_SAFE_HAVEN_MAX,
            "high_vol_scale":      MSE_HIGH_VOL_SCALE,
            "trading_rules": {
                "CRISIS": (
                    "Block ALL new entries (both sides). "
                    f"Exception: {sorted(MSE_SAFE_HAVENS)} eligible as longs, "
                    f"max {MSE_SAFE_HAVEN_MAX}, sized at {MSE_HIGH_VOL_SCALE}×."
                ),
                "BEAR":   "Display only — no trading gate.",
                "BULL":   "Normal trading — no gate active.",
            },
            "dual_gate_note": (
                "Live fast gate (algo_scanner + executor): "
                f"SPY close > 200SMA AND 5d return > -3% → {display_label('oracle')} long-only brake. "
                "CRISIS gate (this module): SPY 20d return <= -12% → "
                "both-sides block + safe-haven rotation. "
                "Complementary; CRISIS is more restrictive when both active."
            ),
        },
        "regime_label": regime,
        "is_crisis":    regime == "CRISIS",
        "is_bear":      regime == "BEAR",
        "is_bull":      regime == "BULL",
    }
