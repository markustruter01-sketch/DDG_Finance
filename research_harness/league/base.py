"""The strategy interface and the one rebalance rule every shadow shares.

A strategy is a ``Strategy`` record. Its ``target`` function is pure:
``target(view, ctx) -> Call | None``. ``view`` is a HistoryView set to the day
(bars up to and including that day's close, nothing later); ``ctx`` carries the
session calendar and, for stock-picking strategies, the S&P 500 member list.
``None`` means "not enough history yet" (the shadow stays in cash).

A ``Call`` is the strategy's wanted holdings plus a small ``state`` value (for
example the trend votes, or "in"/"out"). The league sends a new decision on a
session when:
  1. the shadow has no decision yet, or
  2. the session is a scheduled rebalance day (first session of the month or
     of the week, by ``cadence``), or
  3. ``state`` differs from the previous session's ``state``.
Otherwise the shadow holds. Because the rule only reads history, a missed night
is caught up later with exactly the decisions a nightly run would have made.

Unused money is parked in T-bills (BIL), as the real accounts park cash; the
pretend-account engine pays no interest on plain cash.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from research_harness.harness.portfolio import HistoryView

CASH = "BIL"                    # T-bill fund; every shadow's idle money sits here
TRADING_DAYS = 252
CADENCES = ("monthly", "weekly", "daily", "once")
FAMILIES = ("yardstick", "trend", "stocks", "diversifier", "short_term", "forex")


@dataclass(frozen=True)
class Call:
    weights: dict[str, float]
    state: Any = None
    note: dict[str, Any] = field(default_factory=dict)   # stored with the decision (inputs)


@dataclass(frozen=True)
class Context:
    calendar: tuple[date, ...]                 # US sessions (SPY's days), ascending
    universe: tuple[str, ...] = ()             # S&P 500 members (stock strategies only)
    sectors: dict[str, str] = field(default_factory=dict)
    start: date | None = None                  # the shadow's first day (path-dependent rules walk from it)


@dataclass(frozen=True)
class Strategy:
    id: str
    family: str
    name: str                                  # plain words for the leaderboard
    cadence: str
    symbols: tuple[str, ...]                   # fixed instruments it may hold (CASH added)
    target: Callable[[HistoryView, Context], Call | None]
    stop_pct: float | None = None
    uses_universe: bool = False
    uses_sectors: bool = False                 # needs a real sector for most members (else a missed night)
    history_sessions: int = 260                # sessions of history it needs before day 1
    max_gross: float = 1.0                     # longs plus shorts, as a share of equity
    allow_short: bool = False
    forex: bool = False                        # OANDA daily bars; no T-bill parking (a forex account holds cash)

    def __post_init__(self) -> None:
        if self.cadence not in CADENCES:
            raise ValueError(f"{self.id}: unknown cadence {self.cadence}")
        if self.family not in FAMILIES:
            raise ValueError(f"{self.id}: unknown family {self.family}")


# ── small pure helpers shared by the families ────────────────────────────────
def checked(weights: dict[str, float], max_gross: float) -> dict[str, float]:
    """Long/short weights (forex): gross at most ``max_gross``; nothing parked."""
    w = {s: round(float(x), 10) for s, x in weights.items() if abs(x) > 1e-9}
    gross = sum(abs(x) for x in w.values())
    if gross > max_gross + 1e-9:
        raise ValueError(f"gross {gross:.6f} is above {max_gross}")
    return dict(sorted(w.items()))


def with_cash(weights: dict[str, float]) -> dict[str, float]:
    """Weights plus BIL for whatever is not invested. Rejects more than 100%."""
    if any(float(x) < -1e-9 for x in weights.values()):
        raise ValueError("shadows are long only")
    w = {s: float(x) for s, x in weights.items() if x > 1e-9}
    total = sum(w.values())
    if total > 1 + 1e-9:
        raise ValueError(f"weights add to {total:.6f} (> 1): shadows do not borrow")
    rest = 1.0 - total
    if rest > 1e-6:
        w[CASH] = w.get(CASH, 0.0) + rest
    return {s: round(x, 10) for s, x in sorted(w.items())}


def has_today(view: HistoryView, symbol: str) -> bool:
    try:
        bars = view.window(symbol, 1)
    except KeyError:                   # no bars at all for this symbol
        return False
    return bool(bars) and bars[-1]["day"] == view.today


def closes(view: HistoryView, symbol: str, n: int) -> list[float]:
    """The last n closes up to today, or [] if the symbol has no bar today."""
    if not has_today(view, symbol):
        return []
    return [b["close"] for b in view.window(symbol, n)]


def ann_vol(c: list[float], n: int) -> float | None:
    """Annualised sample sd of the last n simple returns (needs n+1 closes)."""
    if len(c) < n + 1:
        return None
    c = c[-(n + 1):]
    r = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
    m = sum(r) / len(r)
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(TRADING_DAYS)
    return sd if sd > 0 else None


def sma(c: list[float], n: int) -> float | None:
    return sum(c[-n:]) / n if len(c) >= n else None


def previous_session(calendar: tuple[date, ...], day: date) -> date | None:
    import bisect
    i = bisect.bisect_left(calendar, day)
    return calendar[i - 1] if i > 0 else None


def is_month_start(calendar: tuple[date, ...], day: date) -> bool:
    p = previous_session(calendar, day)
    return p is None or (p.year, p.month) != (day.year, day.month)


def is_week_start(calendar: tuple[date, ...], day: date) -> bool:
    p = previous_session(calendar, day)
    return p is None or p.isocalendar()[:2] != day.isocalendar()[:2]


def month_sessions(calendar: tuple[date, ...], day: date) -> list[date]:
    """This month's sessions up to and including ``day``."""
    return [d for d in calendar if (d.year, d.month) == (day.year, day.month) and d <= day]


# ── the one rebalance rule ────────────────────────────────────────────────────
def at(view: HistoryView, day: date) -> HistoryView:
    view.today = day
    return view


def decide(strategy: Strategy, view: HistoryView, ctx: Context, day: date,
           has_decision: bool) -> Call | None:
    """The Call to send on ``day``, or None to hold (see the module rules)."""
    call = strategy.target(at(view, day), ctx)
    if call is None:
        return None
    send = not has_decision or strategy.cadence == "daily"
    if not send and strategy.cadence == "monthly":
        send = is_month_start(ctx.calendar, day)
    if not send and strategy.cadence == "weekly":
        send = is_week_start(ctx.calendar, day)
    if not send:
        prev = previous_session(ctx.calendar, day)
        if prev is not None:
            before = strategy.target(at(view, prev), ctx)
            send = before is None or before.state != call.state
        view.today = day
    if not send:
        return None
    weights = checked(call.weights, strategy.max_gross) if strategy.allow_short else with_cash(call.weights)
    return Call(weights=weights, state=call.state, note=call.note)
