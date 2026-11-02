"""FLEET-V1 sleeve 1: the geared equity core (plan: research_harness/explore/FLEET-V1-PLAN.md).

Read once a day at the close on the S&P 500 total-return series (the spliced
SPY instrument); trades go out at the next open (the simulator's timing).

1. Votes v = how many of "close above its close 63 / 126 / 252 sessions ago" hold.
2. s = min(1, 0.15 / vol20), vol20 = annualised sample sd of the last 20
   simple returns.
3. E = min(1.5, 1.5 x v/3 x s); E < 0.10 -> 0 (T-bills).
4. For each index i with mix share m_i: E <= 1 -> 1x at m_i x E;
   E > 1 -> 1x at m_i x (2 - E) and 2x at m_i x (E - 1), all x 0.99 (the 1%
   cash buffer the plan declares for the fully invested case).
5. Rebalance when v changes and at the first session close of each month.
6. 20% stops are the simulator's (stop_pct), re-set at every rebalance.
Every value is fixed by the plan.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView

SIGNAL = "SPY"                     # spliced S&P 500 TR (rebuilt before 1993, real SPY after)
LOOKBACKS = (63, 126, 252)
VOL_SESSIONS = 20
VOL_TARGET = 0.15
MAX_EXPOSURE = 1.5
MIN_EXPOSURE = 0.10
CASH_BUFFER = 0.01
STOP_PCT = 0.20
TRADING_DAYS = 252
INSTRUMENTS = {"SP": ("SPY", "SSO"), "NDX": ("QQQ", "QLD")}   # index -> (1x, 2x)
LEVERAGE = {"SPY": 1.0, "QQQ": 1.0, "SSO": 2.0, "QLD": 2.0}
MIXES = {"C1": {"SP": 0.6, "NDX": 0.4}, "C2": {"SP": 1.0}}
NEED = max(LOOKBACKS) + 1          # closes needed for every vote (vol needs 21)


def votes(closes: list[float]) -> int | None:
    if len(closes) < NEED:
        return None
    return sum(1 for n in LOOKBACKS if closes[-1] > closes[-1 - n])


def vol20(closes: list[float]) -> float | None:
    if len(closes) < VOL_SESSIONS + 1:
        return None
    c = closes[-(VOL_SESSIONS + 1):]
    r = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(TRADING_DAYS)


def target_exposure(v: int, vol: float | None) -> float:
    s = 1.0 if not vol else min(1.0, VOL_TARGET / vol)
    e = min(MAX_EXPOSURE, MAX_EXPOSURE * (v / 3) * s)
    return 0.0 if e < MIN_EXPOSURE else e


def weights_for(e: float, mix: dict[str, float]) -> dict[str, float]:
    """Instrument weights giving exposure m_i x E per index (x 0.99 when geared)."""
    out: dict[str, float] = {}
    if e <= 0:
        return out
    for idx, m in mix.items():
        one, two = INSTRUMENTS[idx]
        if e <= 1:
            out[one] = m * e
        else:
            out[one] = m * (2 - e) * (1 - CASH_BUFFER)
            out[two] = m * (e - 1) * (1 - CASH_BUFFER)
    return {s: w for s, w in out.items() if w > 1e-12}


def exposure(weights: dict[str, float]) -> float:
    return sum(w * LEVERAGE[s] for s, w in weights.items())


def make_strategy(cid: str, log: list[tuple[date, int, float]] | None = None):
    """Strategy for portfolio.simulate. ``log`` receives (day, votes, E) every
    session once the signal exists."""
    mix = MIXES[cid]
    state: dict[str, Any] = {"votes": None, "month": None}

    def strategy(day: date, view: HistoryView) -> dict[str, float] | None:
        bars = view.window(SIGNAL, NEED)
        if len(bars) < NEED or bars[-1]["day"] != view.today:
            return None
        closes = [b["close"] for b in bars]
        v = votes(closes)
        e = target_exposure(v, vol20(closes))
        if log is not None:
            log.append((day, v, e))
        month = (day.year, day.month)
        changed, new_month = v != state["votes"], month != state["month"]
        state["votes"], state["month"] = v, month
        if not (changed or new_month):
            return None
        return weights_for(e, mix)

    return strategy


def core_stats(log: list[tuple[date, int, float]], start: date, end: date) -> dict[str, Any]:
    """Time at each vote count and exposure band, vote changes, average and max exposure."""
    rows = [r for r in log if start <= r[0] <= end]
    if not rows:
        return {"note": "no signal history in window"}
    n = len(rows)
    bands = {"0 (cash)": lambda e: e == 0, "0-0.5": lambda e: 0 < e <= 0.5,
             "0.5-1.0": lambda e: 0.5 < e <= 1.0, "1.0-1.5": lambda e: e > 1.0}
    return {
        "sessions": n,
        "time_at_votes_pct": {v: round(100 * sum(1 for r in rows if r[1] == v) / n, 1) for v in range(4)},
        "time_at_exposure_pct": {k: round(100 * sum(1 for r in rows if f(r[2])) / n, 1)
                                 for k, f in bands.items()},
        "vote_changes": sum(1 for i in range(1, n) if rows[i][1] != rows[i - 1][1]),
        "target_exposure_avg": round(sum(r[2] for r in rows) / n, 3),
        "target_exposure_max": round(max(r[2] for r in rows), 3),
    }
