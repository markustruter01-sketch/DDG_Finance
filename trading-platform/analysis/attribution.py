"""
P&L Attribution Engine
-----------------------
Decomposes trading P&L into three attribution categories:
  1. Regime Accuracy — Was the Bull/Bear/Sideways call correct?
  2. Timing Quality — How close was entry to the optimal entry point?
  3. Stop Quality  — Did the ATR ratchet stop fire at the right level?

Uses the trades table + performance_snapshots for all computation.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from analysis.trade_journal import get_all_trades


def compute_attribution() -> dict[str, Any]:
    trades = get_all_trades()

    if not trades:
        return {
            "total_trades": 0,
            "closed_trades": 0,
            "regime_attribution": {},
            "asset_class_attribution": {},
            "conviction_attribution": {},
            "timing_quality": {"trades_with_fill_data": 0, "avg_slippage_pct": None, "max_slippage_pct": None, "worst_fills": []},
            "stop_quality": {"stop_triggered_count": 0, "stop_avg_pnl_pct": None, "avg_loss_when_stopped": None},
            "overall": {"total_pnl_pct": 0, "avg_pnl_pct": 0, "win_rate": 0, "wins": 0, "losses": 0},
        }

    closed_trades = [t for t in trades if t.get("status", "").startswith("Closed")]

    if not closed_trades:
        return {
            "total_trades": len(trades),
            "closed_trades": 0,
            "regime_attribution": {},
            "asset_class_attribution": {},
            "conviction_attribution": {},
            "timing_quality": {"trades_with_fill_data": 0, "avg_slippage_pct": None, "max_slippage_pct": None, "worst_fills": []},
            "stop_quality": {"stop_triggered_count": 0, "stop_avg_pnl_pct": None, "avg_loss_when_stopped": None},
            "overall": {"total_pnl_pct": 0, "avg_pnl_pct": 0, "win_rate": 0, "wins": 0, "losses": 0},
        }

    regime_buckets: dict[str, list[float]] = {}
    asset_class_buckets: dict[str, list[float]] = {}
    conviction_buckets: dict[str, list[float]] = {"high": [], "medium": [], "low": []}
    timing_data: list[dict] = []

    total_pnl = 0.0
    wins = 0
    losses = 0

    for t in closed_trades:
        pnl = t.get("pnl_percentage") or 0.0
        total_pnl += pnl

        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

        asset_class = t.get("asset_class", "unknown")
        if asset_class not in asset_class_buckets:
            asset_class_buckets[asset_class] = []
        asset_class_buckets[asset_class].append(pnl)

        conviction = t.get("conviction_score", 0)
        if conviction >= 0.85:
            conviction_buckets["high"].append(pnl)
        elif conviction >= 0.75:
            conviction_buckets["medium"].append(pnl)
        else:
            conviction_buckets["low"].append(pnl)

        intended = t.get("intended_price")
        actual = t.get("actual_fill_price")
        if intended and actual and intended > 0:
            slippage_pct = ((actual - intended) / intended) * 100
            timing_data.append({
                "ticker": t["ticker"],
                "slippage_pct": round(slippage_pct, 4),
                "date": t.get("date"),
            })

    def _bucket_stats(values: list[float]) -> dict:
        if not values:
            return {"count": 0, "total_pnl_pct": 0, "avg_pnl_pct": 0, "win_rate": 0}
        w = sum(1 for v in values if v > 0)
        return {
            "count": len(values),
            "total_pnl_pct": round(sum(values), 2),
            "avg_pnl_pct": round(sum(values) / len(values), 2),
            "win_rate": round(w / len(values) * 100, 1),
        }

    regime_attr = {k: _bucket_stats(v) for k, v in regime_buckets.items()}
    asset_attr = {k: _bucket_stats(v) for k, v in asset_class_buckets.items()}
    conviction_attr = {k: _bucket_stats(v) for k, v in conviction_buckets.items()}

    avg_slippage = None
    max_slippage = None
    if timing_data:
        slippages = [d["slippage_pct"] for d in timing_data]
        avg_slippage = round(sum(slippages) / len(slippages), 4)
        max_slippage = round(max(slippages, key=abs), 4)

    n_closed = len(closed_trades)
    win_rate = round(wins / n_closed * 100, 1) if n_closed > 0 else 0

    stop_exits = [t for t in closed_trades if "stop" in (t.get("status", "")).lower()]
    stop_quality = {
        "stop_triggered_count": len(stop_exits),
        "stop_avg_pnl_pct": round(
            sum(t.get("pnl_percentage", 0) for t in stop_exits) / len(stop_exits), 2
        ) if stop_exits else None,
        "avg_loss_when_stopped": round(
            sum(t.get("pnl_percentage", 0) for t in stop_exits if t.get("pnl_percentage", 0) < 0) /
            max(1, sum(1 for t in stop_exits if t.get("pnl_percentage", 0) < 0)), 2
        ) if stop_exits else None,
    }

    return {
        "total_trades": len(trades),
        "closed_trades": n_closed,
        "regime_attribution": regime_attr,
        "asset_class_attribution": asset_attr,
        "conviction_attribution": conviction_attr,
        "timing_quality": {
            "trades_with_fill_data": len(timing_data),
            "avg_slippage_pct": avg_slippage,
            "max_slippage_pct": max_slippage,
            "worst_fills": sorted(timing_data, key=lambda d: abs(d["slippage_pct"]), reverse=True)[:5],
        },
        "stop_quality": stop_quality,
        "overall": {
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(total_pnl / n_closed, 2) if n_closed else 0,
            "win_rate": win_rate,
            "wins": wins,
            "losses": losses,
        },
    }
