"""GEAR-V1: the S&P 500 "gearbox" core (plan: research_harness/explore/GEAR-V1-PLAN.md).

Read once a day at the close on SPY; trades go out at the next open:
- Aggressive: SPY close > its 200-session average AND SPY's 20-session
  realised volatility (annualised) <= 20%  -> the candidate's aggressive mix.
- Normal: above the average but volatility > 20%  -> the normal mix (1.0x).
- Safe: close <= the average  -> T-bills (empty weights; cash earns DTB3).
Trades only when the gear changes and at the first session close of each
month (back to target weights). Every value here is fixed by the plan.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Callable

from research_harness.harness.portfolio import HistoryView

SIGNAL = "SPY"
SMA_SESSIONS = 200          # Gayed & Bilello's published rule
VOL_SESSIONS = 20
VOL_LINE = 0.20             # annualised; fixed design value, see the plan
TRADING_DAYS = 252
LEVERAGE = {"SPY": 1.0, "QQQ": 1.0, "SSO": 2.0, "QLD": 2.0}   # 2x ETFs reset daily

CANDIDATES: dict[str, dict[str, dict[str, float]]] = {
    "G1": {"aggressive": {"SPY": 1.0}, "normal": {"SPY": 1.0}},
    "G2": {"aggressive": {"SPY": 0.5, "SSO": 0.5}, "normal": {"SPY": 1.0}},
    "G3": {"aggressive": {"SPY": 0.75, "SSO": 0.25}, "normal": {"SPY": 1.0}},
    "G4": {"aggressive": {"SPY": 0.25, "SSO": 0.25, "QQQ": 0.25, "QLD": 0.25},
           "normal": {"SPY": 0.5, "QQQ": 0.5}},
}
SIMPLICITY_ORDER = ["G1", "G3", "G2", "G4"]          # ties go to the simpler candidate


def exposure(weights: dict[str, float]) -> float:
    """Market exposure of a mix (2x ETFs count double)."""
    return sum(w * LEVERAGE[s] for s, w in weights.items())


def gear_for(closes: list[float]) -> str | None:
    """Gear from SPY closes up to today; None until there is enough history."""
    if len(closes) < max(SMA_SESSIONS, VOL_SESSIONS + 1):
        return None
    sma = sum(closes[-SMA_SESSIONS:]) / SMA_SESSIONS
    if closes[-1] <= sma:
        return "safe"
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - VOL_SESSIONS, len(closes))]
    mean = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(TRADING_DAYS)
    return "aggressive" if vol <= VOL_LINE else "normal"


def make_strategy(cid: str, log: list[tuple[date, str]] | None = None,
                  safe: Callable[[HistoryView], dict[str, float]] | None = None):
    """Strategy for the portfolio simulator. ``log`` (if given) receives
    (day, gear) for every session once the signal exists. ``safe`` (GEAR-V2)
    gives the safe gear's weights; None = T-bills, as registered for G4."""
    mixes = CANDIDATES[cid]
    state: dict[str, Any] = {"gear": None, "month": None}

    def strategy(day: date, view: HistoryView) -> dict[str, float] | None:
        bars = view.window(SIGNAL, SMA_SESSIONS + 1)
        if not bars or bars[-1]["day"] != view.today:
            return None                                   # no SPY bar today: hold
        gear = gear_for([b["close"] for b in bars])
        if gear is None:
            return None
        if gear == "aggressive" and mixes["aggressive"] == mixes["normal"]:
            gear = "normal"                               # G1 has only two gears
        if log is not None:
            log.append((day, gear))
        month = (day.year, day.month)
        changed, new_month = gear != state["gear"], month != state["month"]
        state["gear"], state["month"] = gear, month
        if not (changed or new_month):
            return None
        if gear == "safe":
            return safe(view) if safe is not None else {}
        return dict(mixes[gear])

    return strategy


def gear_stats(log: list[tuple[date, str]], cid: str, start: date, end: date) -> dict[str, Any]:
    """Time in each gear, gear changes, and target exposure over a window."""
    rows = [(d, g) for d, g in log if start <= d <= end]
    if not rows:
        return {"note": "no gear history in window"}
    mixes = CANDIDATES[cid]
    exp = [0.0 if g == "safe" else exposure(mixes[g]) for _, g in rows]
    changes = sum(1 for i in range(1, len(rows)) if rows[i][1] != rows[i - 1][1])
    n = len(rows)
    return {
        "sessions": n,
        "time_in_gear_pct": {g: round(100 * sum(1 for _, x in rows if x == g) / n, 1)
                             for g in ("aggressive", "normal", "safe")},
        "gear_changes": changes,
        "target_exposure_avg": round(sum(exp) / n, 3),
        "target_exposure_max": round(max(exp), 3),
    }
