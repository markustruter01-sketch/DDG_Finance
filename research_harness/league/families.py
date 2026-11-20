"""The Shadow League's strategies (roadmap Phase 1), one function each.

Exact rules are written in research_harness/registrations/league/<ID>.json;
this file implements them. Rules marked PROPOSED there were written by Opus
5.5 on 19 Nov 2026 and need Markus's yes before the lock.

Reused, not copied: the Atlas trend rule (research_harness/sleeves/core_v1),
the cross-asset trend rule (sleeves/xasset_v1) and 12-1 momentum
(sleeves/momo_v1.momentum_12_1). MOMO-V2's book index and brakes are copied
from sleeve_runtime/momo_live.py, which the shadows may not import (it carries
the order path); tests/test_league.py checks both agree.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from research_harness.harness.portfolio import HistoryView
from research_harness.league.base import (
    Call,
    Context,
    Strategy,
    ann_vol,
    closes,
    has_today,
    is_week_start,
    month_sessions,
    sma,
)
from research_harness.league import forex as fx
from research_harness.sleeves import core_v1, xasset_v1
from research_harness.sleeves.momo_v1 import MIN_CLOSES, momentum_12_1


# ── yardsticks ────────────────────────────────────────────────────────────────
def _fixed(weights: dict[str, float]):
    def target(view: HistoryView, ctx: Context) -> Call | None:
        if not all(has_today(view, s) for s in weights):
            return None
        return Call(dict(weights), state="hold")
    return target


# ── trend and gearing ─────────────────────────────────────────────────────────
def atlas_exposure(c: list[float], cap: float) -> tuple[int, float] | None:
    """The Atlas trend rule (core_v1) with its 1.5x ceiling replaced by ``cap``:
    E = min(cap, cap x votes/3 x min(1, 0.15 / vol20)); E < 0.10 -> 0."""
    v = core_v1.votes(c)
    if v is None:
        return None
    vol = core_v1.vol20(c)
    s = 1.0 if not vol else min(1.0, core_v1.VOL_TARGET / vol)
    e = min(cap, cap * (v / 3) * s)
    return v, (0.0 if e < core_v1.MIN_EXPOSURE else e)


def _atlas(cap: float):
    def target(view: HistoryView, ctx: Context) -> Call | None:
        c = closes(view, core_v1.SIGNAL, core_v1.NEED)
        got = atlas_exposure(c, cap) if len(c) >= core_v1.NEED else None
        if got is None:
            return None
        v, e = got
        return Call(core_v1.weights_for(e, core_v1.MIXES["C1"]), state=v,
                    note={"votes": v, "exposure": round(e, 4)})
    return target


F1_SPLIT = (0.65, 0.35)          # FLEET-V1-F1: core, cross-asset (sleeve_runtime.fleet_live.F1)


def _atlas_f1(view: HistoryView, ctx: Context) -> Call | None:
    core = _atlas(core_v1.MAX_EXPOSURE)(view, ctx)
    if core is None:
        return None
    x = xasset_v1.target_weights(view)
    w = {s: F1_SPLIT[0] * q for s, q in core.weights.items()}
    for s, q in x.items():
        w[s] = w.get(s, 0.0) + F1_SPLIT[1] * q
    return Call(w, state=core.state, note={**core.note, "xasset": {s: round(q, 4) for s, q in x.items()}})


# ── diversifiers ──────────────────────────────────────────────────────────────
def _xtrend(view: HistoryView, ctx: Context) -> Call | None:
    """xasset_v1's rule on its own, monthly as in FLEET-V1: each line long on
    >= 2 of 3 trend votes, sized to 10% volatility / 4, capped 40%."""
    if not has_today(view, core_v1.SIGNAL):
        return None
    w = xasset_v1.target_weights(view)
    return Call(w, state="hold", note={"on": sorted(w)})


def _gold(view: HistoryView, ctx: Context) -> Call | None:
    """100% gold (GLD) when >= 2 of the 3 Atlas trend votes (close above its
    close 63 / 126 / 252 sessions ago) hold, else cash. Monthly."""
    c = closes(view, "GLD", core_v1.NEED)
    v = core_v1.votes(c) if len(c) >= core_v1.NEED else None
    if v is None:
        return None
    return Call({"GLD": 1.0} if v >= xasset_v1.MIN_VOTES else {}, state="hold", note={"votes": v})


RP_LINES = ("SPY", "IEF", "GLD")
RP_VOL_SESSIONS = 63


def _risk_parity(view: HistoryView, ctx: Context) -> Call | None:
    """Shares, bonds and gold, each weighted by 1 / its 63-session volatility,
    adding to 100%. Monthly."""
    inv = {}
    for s in RP_LINES:
        vol = ann_vol(closes(view, s, RP_VOL_SESSIONS + 1), RP_VOL_SESSIONS)
        if vol is None:
            return None
        inv[s] = 1.0 / vol
    total = sum(inv.values())
    return Call({s: x / total for s, x in inv.items()}, state="hold")


# ── short-term ────────────────────────────────────────────────────────────────
DIP_TREND = 200           # sessions in the long average
DIP_LOW = 5               # a close at the lowest of this many sessions is a dip
DIP_EXIT_SMA = 5          # leave when the close is back above this average...
DIP_MAX_HOLD = 5          # ...or after this many sessions held


def dip_state(c: list[float]) -> str | None:
    """'in' or 'out' at the last close, by walking the rule through history.
    Entry (decided at a close, filled next open): close above its 200-session
    average AND the lowest close of the last 5 sessions. Exit: close above its
    5-session average, or the 5th session held."""
    if len(c) < DIP_TREND:
        return None
    state, held = "out", 0
    for i in range(DIP_TREND - 1, len(c)):
        window = c[: i + 1]
        if state == "out":
            if window[-1] > sma(window, DIP_TREND) and window[-1] <= min(window[-DIP_LOW:]):
                state, held = "in", 0
        else:
            held += 1
            if window[-1] > sma(window, DIP_EXIT_SMA) or held >= DIP_MAX_HOLD:
                state = "out"
    return state


DIP_HISTORY = 400         # closes walked; a dip trade lasts days, so an older start cannot change today


def _dip(view: HistoryView, ctx: Context) -> Call | None:
    st = dip_state(closes(view, "SPY", DIP_HISTORY))
    if st is None:
        return None
    return Call({"SPY": 1.0} if st == "in" else {}, state=st)


TOM_EXIT_SESSION = 3      # out after the 3rd session of the new month


def weekdays_left(day: date) -> int:
    """Weekdays after ``day`` in its month (holidays not known: counted)."""
    import calendar
    last = calendar.monthrange(day.year, day.month)[1]
    return sum(1 for d in range(day.day + 1, last + 1) if date(day.year, day.month, d).weekday() < 5)


def tom_state(day: date, calendar_: tuple[date, ...]) -> str:
    """'in' when the decision at this close should hold the index:
    - at most 1 weekday left in the month (so the fill is on its last weekday), or
    - this is the 1st or 2nd session of a month (held through the 3rd session's
      close; the decision at the 3rd session's close is 'out')."""
    if weekdays_left(day) <= 1:
        return "in"
    n = len(month_sessions(calendar_, day))
    return "in" if n < TOM_EXIT_SESSION else "out"


def _tom(view: HistoryView, ctx: Context) -> Call | None:
    if not has_today(view, "SPY"):
        return None
    st = tom_state(view.today, ctx.calendar)
    return Call({"SPY": 1.0} if st == "in" else {}, state=st)


# ── stock picking (S&P 500 members) ───────────────────────────────────────────
MOMO_TOP = 50
MOMO_TREND = 100
MOMO_VOL = 20
MOMO_VOL_TARGET = 0.15
SECTOR_CAP = 0.25                     # at most 25% of the 50 names (12) from one sector
DEF_TOP = 50
DEF_VOL_SESSIONS = 252


def rank_momentum(view: HistoryView, universe: tuple[str, ...], n: int,
                  sectors: dict[str, str] | None = None, cap: float | None = None) -> list[str]:
    """Top n by 12-1 momentum at today's close; a name needs a bar today and
    MIN_CLOSES closes. With ``cap``, at most floor(cap x n) names per sector
    (a name with no sector counts as its own sector 'unknown')."""
    scored = []
    for s in universe:
        c = closes(view, s, MIN_CLOSES)
        if len(c) < MIN_CLOSES:
            continue
        m = momentum_12_1(c)
        if m is not None:
            scored.append((-m, s))
    scored.sort()
    if cap is None:
        return [s for _, s in scored[:n]]
    limit, used, out = math.floor(cap * n), {}, []
    for _, s in scored:
        sec = (sectors or {}).get(s) or "unknown"
        if used.get(sec, 0) >= limit:
            continue
        used[sec] = used.get(sec, 0) + 1
        out.append(s)
        if len(out) == n:
            break
    return out


def book_index(view: HistoryView, names: list[str], selection_day: date) -> list[tuple[date, float]]:
    """Copy of momo_live.book_index on a HistoryView (bars up to today)."""
    base, series = {}, {}
    for s in names:
        if not has_today(view, s) and s not in view.symbols():
            continue
        by_day = {b["day"]: b["close"] for b in view.bars(s)}
        if selection_day in by_day and by_day[selection_day] > 0:
            base[s], series[s] = by_day[selection_day], by_day
    if not base:
        return []
    days = sorted(set.intersection(*(set(d) for d in series.values())))
    return [(d, 100.0 * sum(series[s][d] / base[s] for s in base) / len(base)) for d in days]


def brakes(levels: list[float]) -> tuple[bool | None, float | None]:
    """Copy of momo_live.brakes: (trend on, s)."""
    trend = levels[-1] > sum(levels[-MOMO_TREND:]) / MOMO_TREND if len(levels) >= MOMO_TREND else None
    s = None
    if len(levels) >= MOMO_VOL + 1:
        r = [levels[i] / levels[i - 1] - 1 for i in range(len(levels) - MOMO_VOL, len(levels))]
        m = sum(r) / len(r)
        vol = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252)
        s = 1.0 if vol <= 0 else min(1.0, MOMO_VOL_TARGET / vol)
    return trend, s


def _momo(weekly_reentry: bool, cap: float | None):
    """MOMO-V2 on fake money. Names: top 50 at the month's first session.
    Trend brake: the book index vs its 100-session average; below -> cash.
    Re-entry: only at the next month's first session (MOMO-V2), or also at the
    first session of each week (weekly_reentry). s (volatility scale) is set at
    each entry. Each name 2% x s. 20% stops are the engine's (stop_pct)."""
    def target(view: HistoryView, ctx: Context) -> Call | None:
        today = view.today
        sessions = month_sessions(ctx.calendar, today)
        if not sessions or not ctx.universe:
            return None
        sel = sessions[0]
        view.today = sel
        names = rank_momentum(view, ctx.universe, MOMO_TOP, ctx.sectors, cap)
        view.today = today
        if len(names) < MOMO_TOP:
            return None
        idx = dict(book_index(view, names, sel))
        invested, s_at_entry = False, None
        for d in sessions:
            levels = [v for day, v in sorted(idx.items()) if day <= d]
            trend, s = brakes(levels)
            if trend is None:
                return None
            entry_day = d == sel or (weekly_reentry and is_week_start(ctx.calendar, d))
            if invested and not trend:
                invested = False
            elif not invested and trend and entry_day:
                invested, s_at_entry = True, s
        if not invested:
            return Call({}, state=(sel.isoformat(), "out", None), note={"names": names})
        slot = round((1.0 / MOMO_TOP) * (s_at_entry or 0.0), 8)
        return Call({n: slot for n in names}, state=(sel.isoformat(), "in", slot), note={"names": names})
    return target


def _defensive(view: HistoryView, ctx: Context) -> Call | None:
    """The 50 members with the lowest 252-session volatility, 2% each. Monthly."""
    scored = []
    for s in ctx.universe:
        vol = ann_vol(closes(view, s, DEF_VOL_SESSIONS + 1), DEF_VOL_SESSIONS)
        if vol is not None:
            scored.append((vol, s))
    if len(scored) < DEF_TOP:
        return None
    names = [s for _, s in sorted(scored)[:DEF_TOP]]
    return Call({n: 1.0 / DEF_TOP for n in names}, state="hold", note={"names": names})


# ── the catalogue: 3 yardsticks + 15 shadows here; the 16th, FX-COUNCIL, is the Forex
#    account's mirror twin (TWINS-V1), shown in the league by twins/leaderboard.py
ATLAS_SYMBOLS = ("SPY", "QQQ", "SSO", "QLD")
STRATEGIES: tuple[Strategy, ...] = (
    Strategy("Y-SPX", "yardstick", "S&P 500, buy and hold", "once", ("SPY",), _fixed({"SPY": 1.0})),
    Strategy("Y-6040", "yardstick", "60% shares / 40% bonds", "monthly", ("SPY", "AGG"),
             _fixed({"SPY": 0.6, "AGG": 0.4})),
    Strategy("Y-CASH", "yardstick", "Cash (T-bills)", "once", ("BIL",), _fixed({"BIL": 1.0})),
    Strategy("T-1X", "trend", "Atlas trend rule at 1x", "monthly", ATLAS_SYMBOLS, _atlas(1.0),
             stop_pct=core_v1.STOP_PCT),
    Strategy("T-15X", "trend", "Atlas trend rule at 1.5x", "monthly", ATLAS_SYMBOLS, _atlas(1.5),
             stop_pct=core_v1.STOP_PCT),
    Strategy("T-2X", "trend", "Atlas trend rule at 2x", "monthly", ATLAS_SYMBOLS, _atlas(2.0),
             stop_pct=core_v1.STOP_PCT),
    Strategy("T-F1", "trend", "Today's multi-asset Atlas (FLEET-V1-F1)", "monthly",
             ATLAS_SYMBOLS + xasset_v1.LINES, _atlas_f1, stop_pct=core_v1.STOP_PCT),
    Strategy("S-MOMO", "stocks", "Momentum (MOMO-V2)", "monthly", (), _momo(False, None),
             stop_pct=0.20, uses_universe=True, history_sessions=380),
    Strategy("S-MOMO-CAP", "stocks", "Momentum, weekly re-entry, 25% sector cap", "monthly", (),
             _momo(True, SECTOR_CAP), stop_pct=0.20, uses_universe=True, uses_sectors=True,
             history_sessions=380),
    Strategy("S-DEF", "stocks", "Defensive stocks (50 steadiest)", "monthly", (), _defensive,
             stop_pct=0.20, uses_universe=True),
    Strategy("S-EQW", "stocks", "Equal-weight S&P 500 (RSP fund)", "once", ("RSP",), _fixed({"RSP": 1.0})),
    Strategy("D-XTREND", "diversifier", "Trend on bonds, gold, commodities, dollar", "monthly",
             xasset_v1.LINES, _xtrend),
    Strategy("D-GOLD", "diversifier", "Gold trend alone", "monthly", ("GLD",), _gold),
    Strategy("D-RP", "diversifier", "Risk-balanced shares, bonds, gold", "monthly", RP_LINES, _risk_parity),
    Strategy("ST-DIP", "short_term", "Buy index dips, hold a few days", "once", ("SPY",), _dip),
    Strategy("ST-TOM", "short_term", "Index only around the turn of the month", "once", ("SPY",), _tom),
    Strategy("FX-BT1", "forex", "Forex trend baseline (FX-BT1, no AI)", "once", fx.PAIRS, fx._fx_bt1,
             max_gross=fx.GROSS_CAP, allow_short=True, forex=True),
    Strategy("FX-TREND", "forex", "Simple currency trend", "monthly", fx.PAIRS, fx._fx_trend,
             max_gross=fx.GROSS_CAP, allow_short=True, forex=True),
)
BY_ID = {s.id: s for s in STRATEGIES}


def fixed_symbols() -> list[str]:
    """Share and fund symbols the league needs every night (forex pairs come from OANDA)."""
    out = {"SPY", "BIL"}
    for s in STRATEGIES:
        if not s.forex:
            out |= set(s.symbols)
    return sorted(out)


def describe(strategy: Strategy) -> dict[str, Any]:
    return {"id": strategy.id, "family": strategy.family, "name": strategy.name, "cadence": strategy.cadence}
