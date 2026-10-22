"""BOOST-V1 crypto booster sleeve (plan: research_harness/explore/BOOST-V1-PLAN.md).

Crypto trades every calendar day; the fleet trades US sessions. ``to_sessions``
puts crypto bars on the session calendar so every harness convention (252
sessions a year, T-bill accrual, day-for-day alignment with other sleeves)
holds unchanged. The signal reuses TREND-V1's code: same rule, same
look-backs, so nothing here is tuned for crypto.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves.trend import TrendParams, make_strategy

BTC, ETH = "BTC-USD", "ETH-USD"
TREND_RULE = "sma_210"          # copied from TREND-V1-B, not explored
CANDIDATES = {
    "A": {"symbols": [BTC], "rule": None},          # always held
    "B": {"symbols": [BTC], "rule": TREND_RULE},
    "C": {"symbols": [BTC, ETH], "rule": TREND_RULE},
}
STOP_PCT = 0.25                 # copied from the live Bullion crypto stop
SLEEVE_FLEET_WEIGHT = 0.04      # 4% of fleet equity (approved range 3-5%)
MAX_DRAWDOWN_LIMIT = -0.50      # selection gate and pass bar 2


def to_sessions(bars: list[dict[str, Any]], sessions: list[date]) -> list[dict[str, Any]]:
    """Resample calendar-day OHLC onto session days. The bar for session d
    covers calendar days after the previous session up to and including d:
    open of the first, high/low over all, close of d. A session without a
    bar dated exactly d is skipped (its days roll into the next session)."""
    bars = sorted(bars, key=lambda b: b["day"])
    out: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = []
    i, n = 0, len(bars)
    for d in sorted(sessions):
        while i < n and bars[i]["day"] <= d:
            bucket.append(bars[i])
            i += 1
        if bucket and bucket[-1]["day"] == d:
            out.append({"day": d, "open": bucket[0]["open"],
                        "high": max(b["high"] for b in bucket),
                        "low": min(b["low"] for b in bucket),
                        "close": bucket[-1]["close"]})
            bucket = []
    return out


def _hold(symbol: str):
    """Candidate A: fully in ``symbol`` from the first monthly rebalance on."""
    state: dict[str, tuple[int, int] | None] = {"month": None}

    def strategy(day: date, view: HistoryView) -> dict[str, float] | None:
        month = (day.year, day.month)
        if month == state["month"]:
            return None
        state["month"] = month
        bars = view.window(symbol, 1)
        return {symbol: 1.0} if bars and bars[-1]["day"] == view.today else {}

    return strategy


def make_candidate(cid: str):
    spec = CANDIDATES[cid]
    if spec["rule"] is None:
        return _hold(spec["symbols"][0])
    return make_strategy(spec["symbols"], TrendParams(rule=spec["rule"], vol_lookback=63, max_weight=1.0))
