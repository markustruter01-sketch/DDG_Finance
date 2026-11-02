"""FLEET-V1 sleeve 2: cross-asset trend (plan: research_harness/explore/FLEET-V1-PLAN.md).

At the first session close of each month (trade at the next open), for each
line - 10-year Treasuries (IEF), gold (GLD), commodities (DBC), the dollar
(UUP):
- votes = how many of "close above its close 63 / 126 / 252 sessions ago" hold;
  long when votes >= 2, otherwise flat (T-bills). Long only.
- weight = (0.10 / vol63) / 4, vol63 = annualised sample sd of the last 63
  simple returns; capped at 0.40; if the sum exceeds 1, all are scaled down
  pro rata. The divisor is always 4.
- A line without 253 closes (or without a bar today) is flat.
No stops (the monthly call is the exit). Every value is fixed by the plan.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView
from research_harness.sleeves.core_v1 import NEED, votes

LINES = ("IEF", "GLD", "DBC", "UUP")
VOL_SESSIONS = 63
VOL_TARGET = 0.10
DIVISOR = 4
MAX_WEIGHT = 0.40
MIN_VOTES = 2
TRADING_DAYS = 252


def vol63(closes: list[float]) -> float | None:
    if len(closes) < VOL_SESSIONS + 1:
        return None
    c = closes[-(VOL_SESSIONS + 1):]
    r = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    m = sum(r) / len(r)
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(TRADING_DAYS)
    return sd if sd > 0 else None


def line_weight(closes: list[float]) -> float:
    """The line's weight before the gross cap (0 when off or not yet eligible)."""
    v, vol = votes(closes), vol63(closes)
    if v is None or vol is None or v < MIN_VOTES:
        return 0.0
    return min(MAX_WEIGHT, VOL_TARGET / vol / DIVISOR)


def target_weights(view: HistoryView, lines: tuple[str, ...] = LINES) -> dict[str, float]:
    w: dict[str, float] = {}
    for sym in lines:
        if sym not in view.symbols():
            continue
        bars = view.window(sym, NEED)
        if len(bars) < NEED or bars[-1]["day"] != view.today:
            continue
        x = line_weight([b["close"] for b in bars])
        if x > 0:
            w[sym] = x
    gross = sum(w.values())
    if gross > 1:
        w = {s: x / gross for s, x in w.items()}
    return w


def make_strategy(log: list[tuple[date, dict[str, float]]] | None = None,
                  lines: tuple[str, ...] = LINES):
    """Strategy for portfolio.simulate: rebalances on the first close of each month."""
    state: dict[str, Any] = {"month": None}

    def strategy(day: date, view: HistoryView) -> dict[str, float] | None:
        month = (day.year, day.month)
        if month == state["month"]:
            return None
        state["month"] = month
        w = target_weights(view, lines)
        if log is not None:
            log.append((day, dict(w)))
        return w

    return strategy


def xasset_stats(log: list[tuple[date, dict[str, float]]], start: date, end: date) -> dict[str, Any]:
    rows = [r for r in log if start <= r[0] <= end]
    if not rows:
        return {"note": "no rebalances in window"}
    n = len(rows)
    return {
        "rebalances": n,
        "time_on_pct": {s: round(100 * sum(1 for _, w in rows if s in w) / n, 1) for s in LINES},
        "gross_avg": round(sum(sum(w.values()) for _, w in rows) / n, 3),
        "gross_max": round(max(sum(w.values()) for _, w in rows), 3),
    }
