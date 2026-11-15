"""Twin maths, pure: no database, no network.

- The real account read as target weights (shares: at the session close,
  without owner-kept lines; forex: OANDA positions over NAV).
- Replay: a twin's decision log through the research simulator
  (research_harness/harness/portfolio.simulate), the engine every backtest
  uses: fills at the next open, the same costs, the same stops.
- Daily points and the mirror check.

Steps: a daily twin steps on US sessions (keys are dates); the forex twins
step on hourly bars (keys are the bar's opening time, UTC). A decision is
stored against the close it follows (step_close) and fills at the next step's
opening price.

Forex in a share simulator: an XXX_USD pair is held as XXX units priced in
US dollars; a USD_XXX pair is held as the inverse instrument XXX_USD (price
1/P), so a long USD/JPY is a short of JPY_USD. Profit and loss then come out
in US dollars exactly as OANDA books them.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from research_harness.harness.costs import CostModel, SymbolCosts
from research_harness.harness.portfolio import simulate

from core.symbols import canonical_symbol
from twins.config import DAILY, HOURLY, REGISTRATION

NEW_YORK = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
FOREX_DAY_CLOSE = time(17, 0)        # New York; the forex trading day ends here
HOUR = timedelta(hours=1)
STEPS_PER_YEAR = {DAILY: 252, HOURLY: 24 * 5 * 52}   # accrual of financing per step


class SnapshotError(ValueError):
    """The real account could not be read cleanly; nothing is taken from it."""


# ── steps ─────────────────────────────────────────────────────────────────────
def step_close(step: Any, bars: str) -> datetime:
    """The moment a step's bar closes: what a decision on that step follows."""
    if bars == DAILY:
        return datetime.combine(step, SESSION_CLOSE, NEW_YORK)
    return step + HOUR


def step_of(close_at: datetime, bars: str) -> Any:
    """Inverse of step_close."""
    if bars == DAILY:
        return close_at.astimezone(NEW_YORK).date()
    return close_at.astimezone(timezone.utc) - HOUR


def fill_time(step: Any, bars: str) -> datetime:
    """When a fill on this step happens (at the step's opening price)."""
    if bars == DAILY:
        return datetime.combine(step, SESSION_OPEN, NEW_YORK)
    return step


def bar_hour(ts: datetime) -> datetime:
    """The hourly bar (opening time, UTC) that contains ts."""
    return ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


# ── the real account ──────────────────────────────────────────────────────────
def _num(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise SnapshotError(f"{what} is not a number") from None
    if not math.isfinite(out):
        raise SnapshotError(f"{what} is not finite")
    return out


def share_snapshot(positions: list[dict[str, Any]], cash: Any, closes: dict[str, float],
                   owner_kept: frozenset[str] = frozenset()) -> dict[str, Any]:
    """An Alpaca account at a session close, without the owner-kept lines:
    weights of equity, equity (cash + holdings at the close) and share counts."""
    if not isinstance(positions, list):
        raise SnapshotError("positions are not a list")
    money = _num(cash, "cash")
    qty: dict[str, float] = {}
    for p in positions:
        sym = canonical_symbol(p.get("symbol"))
        if not sym:
            raise SnapshotError("a position has no symbol")
        if sym in owner_kept:
            continue
        q = _num(p.get("qty"), f"{sym} qty")
        if str(p.get("side") or "").lower() == "short":
            q = -abs(q)
        if abs(q) > 1e-9:
            qty[sym] = qty.get(sym, 0.0) + q
    missing = sorted(s for s in qty if not closes.get(s) or closes[s] <= 0)
    if missing:
        raise SnapshotError(f"no close for {missing}")
    values = {s: q * closes[s] for s, q in qty.items()}
    equity = money + sum(values.values())
    if equity <= 0:
        raise SnapshotError("equity without the owner-kept lines is not positive")
    return {"weights": {s: v / equity for s, v in sorted(values.items())},
            "equity": equity, "qty": {s: round(q, 6) for s, q in sorted(qty.items())}}


def synthetic(pair: str) -> str:
    """The US-dollar-priced instrument the simulator holds for an OANDA pair."""
    base, quote = pair.split("_")
    if "USD" not in (base, quote):
        raise SnapshotError(f"{pair}: only US dollar pairs are registered")
    return pair if quote == "USD" else f"{quote}_{base}"


def forex_snapshot(positions: list[dict[str, Any]], nav: Any,
                   mids: dict[str, float]) -> dict[str, Any]:
    """OANDA open positions as weights of NAV (signed US dollar exposure)."""
    if not isinstance(positions, list):
        raise SnapshotError("positions are not a list")
    equity = _num(nav, "NAV")
    if equity <= 0:
        raise SnapshotError("NAV is not positive")
    units: dict[str, float] = {}
    for p in positions:
        pair = str(p.get("instrument") or "")
        if pair.count("_") != 1:
            raise SnapshotError(f"{pair!r} is not an OANDA pair")
        u = sum(_num((p.get(side) or {}).get("units") or 0, f"{pair} {side} units")
                for side in ("long", "short"))
        if abs(u) > 1e-9:
            units[pair] = units.get(pair, 0.0) + u
    weights: dict[str, float] = {}
    for pair, u in units.items():
        sym = synthetic(pair)
        if sym == pair:                       # XXX_USD: u units of XXX at P dollars
            px = mids.get(pair)
            if not px or px <= 0:
                raise SnapshotError(f"no price for {pair}")
            weights[sym] = u * px / equity
        else:                                 # USD_XXX: u is dollars; long USD = short XXX_USD
            weights[sym] = -u / equity
    return {"weights": dict(sorted(weights.items())), "equity": equity,
            "units": {p: round(u, 6) for p, u in sorted(units.items())}}


# ── prices ────────────────────────────────────────────────────────────────────
def _candle_time(value: str) -> datetime:
    return datetime.fromisoformat(value[:19]).replace(tzinfo=timezone.utc)


def _ohlc(part: dict[str, Any], what: str) -> tuple[float, float, float, float]:
    o, h, lo, c = (_num((part or {}).get(k), f"{what} {k}") for k in ("o", "h", "l", "c"))
    if min(o, h, lo, c) <= 0 or h < max(o, c, lo) or lo > min(o, c):
        raise SnapshotError(f"{what}: inconsistent prices")
    return o, h, lo, c


def forex_bars(candles: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """OANDA hourly mid candles as simulator bars, USD_XXX pairs inverted."""
    out: dict[str, list[dict[str, Any]]] = {}
    for pair, rows in candles.items():
        sym = synthetic(pair)
        by_hour: dict[datetime, dict[str, Any]] = {}
        for c in rows:
            t = _candle_time(c["time"])
            o, h, lo, cl = _ohlc(c.get("mid"), f"{pair} {t:%Y-%m-%d %H:%M}")
            if sym != pair:
                o, h, lo, cl = 1 / o, 1 / lo, 1 / h, 1 / cl
            by_hour[t] = {"day": t, "open": o, "high": h, "low": lo, "close": cl}
        out[sym] = [by_hour[t] for t in sorted(by_hour)]
    return out


def half_spread_bps(candles: list[dict[str, Any]]) -> float:
    """Median half spread at the bar opens, in basis points of the mid price."""
    vals = []
    for c in candles:
        bid, ask, mid = (_num((c.get(k) or {}).get("o"), f"{k} open") for k in ("bid", "ask", "mid"))
        if ask >= bid > 0 and mid > 0:
            vals.append((ask - bid) / 2 / mid * 1e4)
    if not vals:
        raise SnapshotError("no bid/ask candles to measure the spread")
    return round(median(vals), 3)


def forex_costs(spread_bps: dict[str, float]) -> SymbolCosts:
    """Measured half spread per instrument; OANDA charges no commission.
    Financing (overnight interest) and slippage beyond the spread are left out."""
    return SymbolCosts(per_trade_bps={synthetic(p): v for p, v in spread_bps.items()},
                       sell_fee_bps=0.0, short_borrow_bps_yr=0.0, financing_spread_bps_yr=0.0,
                       omitted=("slippage", "financing"))


def closes_on(bars: dict[str, list[dict[str, Any]]], step: Any) -> dict[str, float]:
    """Each symbol's close on the step, or its last close before it."""
    out = {}
    for sym, rows in bars.items():
        days = [b["day"] for b in rows]
        i = bisect.bisect_right(days, step)
        if i:
            out[sym] = rows[i - 1]["close"]
    return out


# ── replay ────────────────────────────────────────────────────────────────────
@dataclass
class Replay:
    curve: list[tuple[Any, float, float]] = field(default_factory=list)   # (step, equity, gross)
    fills: list[dict[str, Any]] = field(default_factory=list)
    cost_label: str = ""


def replay(*, bars_kind: str, mirror: bool, start: Any, start_equity: float,
           decisions: list[dict[str, Any]], bars: dict[str, list[dict[str, Any]]],
           costs: CostModel | SymbolCosts, max_gross: float, allow_short: bool,
           stop_pct: float | None = None) -> Replay:
    """Replay a twin from its start through the last bar.

    decisions: dicts with id, step (a step key) and weights (None = missed:
    hold). On each step the twin's target is its latest decision at or before
    that step; a mirror's is the one at or before the NEXT step, because the
    real account's holdings at a close were bought at that session's open
    (the bots decide after a close and trade at the next open, as the
    simulator does). A target is sent to the simulator once, when it changes."""
    steps = sorted({b["day"] for rows in bars.values() for b in rows if b["day"] >= start})
    if not steps:
        return Replay()
    live = sorted((d for d in decisions if d.get("weights") is not None),
                  key=lambda d: (d["step"], d["id"]))
    keys = [d["step"] for d in live]
    state: dict[str, Any] = {"sent": None}
    fills: list[dict[str, Any]] = []
    seen: dict[tuple[Any, str], int] = {}

    def strategy(day: Any, view: Any) -> dict[str, float] | None:
        i = bisect.bisect_left(steps, day)
        at = day if not mirror else (steps[i + 1] if i + 1 < len(steps) else None)
        if at is None:
            return None
        j = bisect.bisect_right(keys, at)
        if not j or live[j - 1]["id"] == state["sent"]:
            return None
        state["sent"] = live[j - 1]["id"]
        return dict(live[j - 1]["weights"])

    def on_fill(day: Any, sym: str, qty: float, price: float, cost: float, reason: str) -> None:
        n = seen.get((day, sym), 0)
        seen[(day, sym)] = n + 1
        fills.append({"filled_at": fill_time(day, bars_kind), "symbol": sym, "n": n, "qty": qty,
                      "price": price, "cost": cost, "reason": reason,
                      "decision_id": state["sent"] if reason == "rebalance" else None})

    res = simulate(bars, strategy, costs=costs, rf_annual=None, start=start, end=steps[-1],
                   start_equity=start_equity, max_gross=max_gross, allow_short=allow_short,
                   registration_id=REGISTRATION, whole_shares=False, stop_pct=stop_pct,
                   periods_per_year=STEPS_PER_YEAR[bars_kind], on_fill=on_fill)
    return Replay(curve=list(res.curve), fills=fills, cost_label=res.cost_label)


def daily_points(curve: list[tuple[Any, float, float]], bars_kind: str) -> list[tuple[date, float, float]]:
    """One point per day: a session close, or the forex day's close (17:00 New York)."""
    if bars_kind == DAILY:
        return [(step, eq, g) for step, eq, g in curve]
    out = []
    for step, eq, g in curve:
        close = step_close(step, bars_kind).astimezone(NEW_YORK)
        if close.time() == FOREX_DAY_CLOSE:
            out.append((close.date(), eq, g))
    return out


def equity_at(curve: list[tuple[Any, float, float]], at: datetime, bars_kind: str,
              before: float | None = None) -> float | None:
    """Equity at the last step that closed at or before ``at``; ``before`` (the
    start balance) if no step had closed yet."""
    best = before
    for step, eq, _ in curve:
        if step_close(step, bars_kind) <= at:
            best = eq
        else:
            break
    return best


def mirror_gaps(points: list[tuple[date, float | None, float | None]]) -> dict[date, float]:
    """Cumulative return gap, mirror minus real account, in percentage points.

    Measured from the first close after the start: the mirror starts in cash
    and buys at the next open, so the real account's first night is not in it."""
    pts = sorted(p for p in points if p[1] and p[2])
    if len(pts) < 2:
        return {}
    _, m0, r0 = pts[1]
    return {d: round((m / m0 - r / r0) * 100, 4) for d, m, r in pts[1:]}
