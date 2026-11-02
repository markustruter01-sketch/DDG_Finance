"""MOMO-V1: regime-gated single-stock momentum (plan: research_harness/explore/MOMO-V1-PLAN.md).

Every value is fixed by the plan:
- Universe (point-in-time, at each month's first session): US common stocks
  from the research panel with >= 253 closes (the 12-1 look-back needs the
  close 252 sessions ago), close >= $5 and a bar on the signal day; the 500
  with the highest average dollar volume (close x volume) over the last 60
  sessions.
- Rank: 12-1 momentum = close 21 sessions ago / close 252 sessions ago - 1.
  Top 20, equal weight.
- Dial (FLEET-V1 sleeve 1's, imported from core_v1, unchanged): votes on
  SPY's adjusted closes over 63/126/252 sessions, s = min(1, 0.15 / vol20).
  M1: E = (v/3) x s, capped at 1.0. M2: E = 1.5 x (v/3) x s, capped at 1.5,
  the part above 1.0 held as SSO (F1's split: stocks (2 - E), SSO (E - 1),
  x 0.99). E < 0.10: the book is sold to cash.
- Rebalance: names re-ranked at the month's first session; the book is
  resized when the vote count changes. 20% stops (the simulator's
  stop_pct) re-set at every rebalance; a stopped name stays in cash until
  the next monthly ranking.

The universe and ranking are pure functions of bars up to the signal day,
computed once per month outside the simulation (``monthly_selection``) so a
backtest only carries the bars of names it can hold.
"""

from __future__ import annotations

import bisect
from datetime import date
from typing import Any, Callable, Sequence

from research_harness.harness.portfolio import HistoryView
from research_harness.harness.sizing import stop_price
from research_harness.sleeves import core_v1

UNIVERSE_SIZE = 500
TOP_N = 20
MIN_PRICE = 5.0
LIQUIDITY_SESSIONS = 60
SKIP_SESSIONS = 21
LOOKBACK_SESSIONS = 252
MIN_CLOSES = LOOKBACK_SESSIONS + 1
SIGNAL = core_v1.SIGNAL                 # "SPY"
GEAR = "SSO"
STOP_PCT = core_v1.STOP_PCT             # 0.20
CASH_BUFFER = core_v1.CASH_BUFFER       # 0.01
CANDIDATES: dict[str, dict[str, Any]] = {
    "M1": {"max_exposure": 1.0, "gear": False},
    "M2": {"max_exposure": 1.5, "gear": True},
}
SIMPLICITY_ORDER = ["M1", "M2"]

Bars = list[dict[str, Any]]


# ── universe and ranking (pure, point-in-time) ────────────────────────────────
class Panel:
    """Daily bars per stock with a day index, read only up to a given day."""

    def __init__(self, bars: dict[str, Bars]) -> None:
        self.bars = {s: b for s, b in bars.items() if b}
        self.days = {s: [x["day"] for x in b] for s, b in self.bars.items()}

    def upto(self, symbol: str, day: date) -> Bars:
        n = bisect.bisect_right(self.days[symbol], day)
        return self.bars[symbol][:n]

    def tail(self, symbol: str, day: date, n: int) -> Bars:
        end = bisect.bisect_right(self.days[symbol], day)
        return self.bars[symbol][max(0, end - n):end]


def dollar_volume(bars: Bars) -> float:
    rows = bars[-LIQUIDITY_SESSIONS:]
    return sum(b["close"] * b.get("volume", 0.0) for b in rows) / len(rows) if rows else 0.0


def momentum_12_1(closes: Sequence[float]) -> float | None:
    if len(closes) < MIN_CLOSES:
        return None
    past = closes[-1 - LOOKBACK_SESSIONS]
    return closes[-1 - SKIP_SESSIONS] / past - 1 if past > 0 else None


def universe_on(panel: Panel, day: date, size: int = UNIVERSE_SIZE) -> list[str]:
    """The ``size`` most traded eligible stocks as of ``day``'s close."""
    scored = []
    for sym in panel.bars:
        tail = panel.tail(sym, day, MIN_CLOSES)
        if len(tail) < MIN_CLOSES or tail[-1]["day"] != day or tail[-1]["close"] < MIN_PRICE:
            continue
        scored.append((-dollar_volume(tail), sym))
    scored.sort()
    return [s for _, s in scored[:size]]


def top_momentum(panel: Panel, day: date, universe: Sequence[str], n: int = TOP_N) -> list[str]:
    ranked = []
    for sym in universe:
        m = momentum_12_1([b["close"] for b in panel.tail(sym, day, MIN_CLOSES)])
        if m is not None:
            ranked.append((-m, sym))
    ranked.sort()
    return [s for _, s in ranked[:n]]


def month_first_sessions(calendar: Sequence[date], start: date, end: date) -> list[date]:
    out, seen = [], set()
    for d in sorted(calendar):
        if start <= d <= end and (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            out.append(d)
    return out


def monthly_selection(panel: Panel, signal_days: Sequence[date],
                      pick: Callable[[Panel, date, list[str]], list[str]] | None = None) -> dict[date, list[str]]:
    """{signal day: names} using only bars up to each signal day.
    ``pick`` defaults to the top-20 by 12-1 momentum (the random null passes its own)."""
    pick = pick or (lambda p, d, u: top_momentum(p, d, u))
    return {d: pick(panel, d, universe_on(panel, d)) for d in signal_days}


# ── dial and weights ──────────────────────────────────────────────────────────
def exposure(spy_closes: Sequence[float], max_exposure: float) -> tuple[int, float] | None:
    """(votes, E) from SPY closes; FLEET-V1's dial scaled to ``max_exposure``."""
    if len(spy_closes) < core_v1.NEED:
        return None
    c = list(spy_closes[-core_v1.NEED:])
    v = core_v1.votes(c)
    vol = core_v1.vol20(c)
    s = 1.0 if not vol else min(1.0, core_v1.VOL_TARGET / vol)
    e = min(max_exposure, max_exposure * (v / 3) * s)
    return v, (0.0 if e < core_v1.MIN_EXPOSURE else e)


def book_weights(names: Sequence[str], e: float, gear: bool) -> dict[str, float]:
    """Equal weight over TOP_N slots (a missing or stopped name's slot is cash)."""
    if e <= 0 or not names:
        return {}
    if e <= 1 or not gear:
        per = min(e, 1.0) / TOP_N
        return {s: per for s in names}
    per = (2 - e) * (1 - CASH_BUFFER) / TOP_N
    out = {s: per for s in names}
    out[GEAR] = (e - 1) * (1 - CASH_BUFFER)
    return out


def stopped_since(view: HistoryView, symbol: str, rebalance_day: date, stop_pct: float = STOP_PCT) -> bool:
    """True if the simulator's stop for ``symbol`` would have fired after the
    rebalance signalled on ``rebalance_day``: the stop is stop_pct below the
    next session's open (the fill), checked against every low from that bar on."""
    later = [b for b in view.bars(symbol) if b["day"] > rebalance_day]
    if not later:
        return False
    level = stop_price(later[0]["open"], long=True, stop_pct=stop_pct)
    return any(b["low"] <= level for b in later)


def make_strategy(cid: str, selection: dict[date, list[str]], log: list | None = None, *,
                  use_dial: bool = True):
    """Strategy for portfolio.simulate. ``selection`` maps each month's first
    session to its names. ``use_dial=False`` is control X18 (always fully
    invested, monthly only). ``log`` receives (day, votes, E) every session."""
    cfg = CANDIDATES[cid]
    state: dict[str, Any] = {"votes": None, "month": None, "names": [], "stopped": set(), "rebalanced": None}

    def strategy(day: date, view: HistoryView) -> dict[str, float] | None:
        spy = view.window(SIGNAL, core_v1.NEED)
        if len(spy) < core_v1.NEED or spy[-1]["day"] != view.today:
            return None
        sig = exposure([b["close"] for b in spy], cfg["max_exposure"])
        if sig is None:
            return None
        v, e = sig if use_dial else (sig[0], 1.0)
        month = (day.year, day.month)
        new_month = month != state["month"]
        changed = use_dial and v != state["votes"]
        state["votes"], state["month"] = v, month
        if new_month:
            state["names"] = list(selection.get(day, []))
            state["stopped"] = set()
        elif changed and state["rebalanced"] is not None:
            # Only at an event does it matter which names were stopped since the
            # last rebalance (each rebalance re-sets every held name's stop).
            for s in state["names"]:
                if s not in state["stopped"] and stopped_since(view, s, state["rebalanced"]):
                    state["stopped"].add(s)
        if log is not None:
            log.append((day, v, e))
        if not (new_month or changed):
            return None
        held = [s for s in state["names"] if s not in state["stopped"]]
        state["rebalanced"] = day
        return book_weights(held, e, cfg["gear"] and use_dial)

    return strategy
