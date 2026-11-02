"""MOMO-V2 live on Momentum's account (plan: research_harness/explore/MOMO-V2-PLAN.md).

A FORWARD-ONLY paper experiment: no backtest stands behind it.

- Universe: the S&P 500's current members (sleeve_runtime/sp500_universe.py),
  read on each month's signal day; no list -> no trade, critical alert.
- Ranking: 12-1 momentum (research_harness.sleeves.momo_v1.momentum_12_1)
  from Alpaca daily adjusted bars; top 50, 2% each of the invested amount.
- Book index: each session, the equal-weight average of the current 50
  names' closes relative to their close on the selection day (x 100),
  computed back through each name's own history; the brakes read it.
- Brakes: trend (index close above its 100-session average, else the whole
  book goes to cash; re-entry only at a monthly signal day, plan rule 4 —
  see MIDMONTH_REENTRY); volatility (invested fraction s = min(1, 0.15 /
  vol20 of the index), applied at the monthly rebalance); 20% stops on every
  name, a stopped name's slot stays in cash until the next selection; the
  account's 15%/22% governor (fleet_live's) on top.
- Rebalance: the month's first completed session (names, s); the first cycle
  of a month after a cutover or an outage counts as it. Otherwise only the
  trend brake (and the drawdown mode) trades.

Orders go through the executor every live sleeve uses (trend_executor).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from functools import partial
from typing import Any, Callable

from research_harness.sleeves.momo_v1 import MIN_CLOSES, momentum_12_1
from sleeve_runtime import fleet_live
from sleeve_runtime.trend_executor import (
    MAX_ATTEMPTS,
    MAX_BAR_AGE_DAYS,
    close_flat_rows,
    execute_rebalance,
)
from sleeve_runtime.trend_v1b import NEW_YORK, BarFetcher, completed_bars, plan_from_weights, sleeve_capital

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("momo_live")

REGISTRATION = "MOMO-V2"
STATE_KEY = "momo_v2"
EXIT_REASON = "momo_v2_rebalance"
SIGNAL = "SPY"                       # the session calendar only; the brakes read the book
TOP_N = 50
SLOT = 1.0 / TOP_N
TREND_SESSIONS = 100
VOL_SESSIONS = 20
VOL_TARGET = 0.15
STOP_PCT = 0.20
TRADING_DAYS = 252
MIDMONTH_REENTRY = False             # plan rule 4 ("until the next monthly signal day"); rule 5 reads otherwise: Fable
HISTORY_CALENDAR_DAYS = 420          # >= 253 sessions for 12-1, which also covers the 121 the brakes need

Bars = dict[str, list[dict[str, Any]]]


# ── selection and book index (pure) ──────────────────────────────────────────
def closes_upto(bars: Bars, sym: str, day: date) -> list[float]:
    return [b["close"] for b in bars.get(sym, []) if b["day"] <= day]


def rank_top(bars: Bars, universe: list[str], day: date, n: int = TOP_N) -> list[str]:
    """Top ``n`` of ``universe`` by 12-1 momentum as of ``day``; a name needs a bar on ``day``."""
    scored = []
    for sym in universe:
        series = [b for b in bars.get(sym, []) if b["day"] <= day]
        if not series or series[-1]["day"] != day or len(series) < MIN_CLOSES:
            continue
        m = momentum_12_1([b["close"] for b in series[-MIN_CLOSES:]])
        if m is not None:
            scored.append((-m, sym))
    scored.sort()
    return [s for _, s in scored[:n]]


def book_index(bars: Bars, names: list[str], selection_day: date, upto: date) -> list[tuple[date, float]]:
    """Equal-weight average of each name's close / its selection-day close (x 100),
    on every session up to ``upto`` where all names that have a selection-day close
    also have a close (sessions missing a name are skipped, never filled)."""
    base, series = {}, {}
    for s in names:
        by_day = {b["day"]: b["close"] for b in bars.get(s, []) if b["day"] <= upto}
        if selection_day in by_day and by_day[selection_day] > 0:
            base[s], series[s] = by_day[selection_day], by_day
    if not base:
        return []
    days = sorted(set.intersection(*(set(d) for d in series.values())))
    return [(d, 100.0 * sum(series[s][d] / base[s] for s in base) / len(base)) for d in days]


def brakes(index: list[tuple[date, float]]) -> dict[str, Any]:
    """Trend on/off from the 100-session average; s from 20-session volatility."""
    levels = [v for _, v in index]
    out: dict[str, Any] = {"trend_on": None, "sma100": None, "vol20": None, "s": None,
                           "index": levels[-1] if levels else None}
    if len(levels) >= TREND_SESSIONS:
        sma = sum(levels[-TREND_SESSIONS:]) / TREND_SESSIONS
        out.update(sma100=sma, trend_on=levels[-1] > sma)
    if len(levels) >= VOL_SESSIONS + 1:
        r = [levels[i] / levels[i - 1] - 1 for i in range(len(levels) - VOL_SESSIONS, len(levels))]
        m = sum(r) / len(r)
        vol = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(TRADING_DAYS)
        out.update(vol20=vol, s=1.0 if vol <= 0 else min(1.0, VOL_TARGET / vol))
    return out


def book_weights(names: list[str], s: float, *, stopped: set[str], mode: str) -> dict[str, float]:
    """2% x s per name not stopped this month, scaled by the drawdown mode."""
    w = SLOT * s * fleet_live.MODE_SCALE[mode]
    return {n: w for n in names if n not in stopped} if w > 0 else {}


def unaffordable(names: list[str], weight: float, equity: float, prices: dict[str, float | None]) -> list[str]:
    """Names whose one share costs more than their slot (skipped that month, plan rule 7)."""
    slot_value = weight * equity
    return sorted(n for n in names if prices.get(n) and prices[n] > slot_value)


# ── schedule ──────────────────────────────────────────────────────────────────
def decide(state: dict[str, Any], month: str, trend_on: bool | None, mode: str) -> tuple[str, str, str] | None:
    """(key, held, why) when a rebalance is due, else None.
    - monthly: the first cycle of a new month (new names, s); re-entry allowed;
    - brake: the trend goes off mid-month (to cash); back on mid-month only
      if MIDMONTH_REENTRY;
    - mode: the drawdown mode changed (or a retry of an incomplete attempt)."""
    if state.get("month") != month:
        held, why = ("out" if trend_on is False else "in"), "monthly"
    else:
        prev = state.get("held", "in")
        held = prev
        if prev == "in" and trend_on is False:
            held = "out"
        elif prev == "out" and trend_on is True and MIDMONTH_REENTRY:
            held = "in"
        why = "brake" if held != prev else "mode"
    key = f"{month}|{held}|{mode}"
    if state.get("key") == key and (state.get("done") or int(state.get("attempts", 0)) >= MAX_ATTEMPTS):
        return None
    return key, held, why


# ── the hourly cycle ──────────────────────────────────────────────────────────
def run_momo_cycle(
    engine,
    *,
    bot_id: str,
    fetch_bars: BarFetcher,
    fetch_universe: Callable[[], tuple[list[str], str]],
    vault: set[str],
    cash_park: set[str],
    read_state: Callable[[], dict[str, Any]],
    write_state: Callable[[dict[str, Any]], None],
    kill_tripped: Callable[[], bool],
    unpark: Callable[[Any, list[dict[str, Any]]], Any],
    park: Callable[[Any, list[dict[str, Any]], float], Any],
    alert: Callable[[str, str], None],
    risk_check: Callable[[], dict[str, Any]],
    soft: float,
    hard: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    live = engine.get_positions()
    rows = engine.get_db_positions(bot_id)
    stopped_now = close_flat_rows(engine, bot_id, live, rows)   # broker stops that filled

    if kill_tripped():
        return {"status": "kill switch tripped: no trading"}

    state = read_state() or {}
    if stopped_now:
        state = {**state, "stopped": sorted(set(state.get("stopped", [])) | set(stopped_now))}
        write_state(state)
    today_ny = now.astimezone(NEW_YORK).date()
    account = engine.get_account()
    dd_before = state.get("drawdown") or {}
    dd = fleet_live.update_drawdown(dd_before, account.get("last_equity"), today_ny, soft=soft, hard=hard)
    if dd != dd_before:
        state = {**state, "drawdown": dd}
        write_state(state)
        if dd.get("mode") != dd_before.get("mode") and dd_before:
            alert("critical" if dd["mode"] == "halt" else "error",
                  f"{REGISTRATION}: drawdown mode {dd_before.get('mode')} -> {dd['mode']}")
    mode = dd.get("mode", "normal")
    if not engine.is_market_open():
        return {"status": "market closed", "mode": mode}

    cap = sleeve_capital(account, live, vault=vault, cash_park=cash_park)
    spy = completed_bars(fetch_bars([SIGNAL], now.date() - timedelta(days=40)), now).get(SIGNAL) or []
    if not spy or (today_ny - spy[-1]["day"]).days > MAX_BAR_AGE_DAYS:
        return {"status": "stale feed: no trading", "mode": mode}
    signal_day = spy[-1]["day"]
    month = f"{signal_day.year:04d}-{signal_day.month:02d}"

    # Names: re-ranked on the month's first cycle (its first session, or the first
    # cycle after a cutover or an outage); otherwise this month's list.
    names, universe_source = state.get("names") or [], state.get("universe_source")
    new_month = state.get("month") != month
    if new_month:
        try:
            universe, universe_source = fetch_universe()
        except Exception as exc:
            alert("critical", f"{REGISTRATION}: S&P 500 member list unavailable, nothing traded: {exc}"[:500])
            return {"status": "universe unavailable: no trading", "mode": mode}
        ubars = completed_bars(fetch_bars(sorted(set(universe) | set(cap.held) | {SIGNAL}),
                                          now.date() - timedelta(days=HISTORY_CALENDAR_DAYS)), now)
        names = rank_top(ubars, universe, signal_day)
        bars = ubars
    else:
        bars = completed_bars(fetch_bars(sorted(set(names) | set(cap.held) | {SIGNAL}),
                                         now.date() - timedelta(days=HISTORY_CALENDAR_DAYS)), now)
    selection_day = signal_day if new_month else date.fromisoformat(
        state.get("selection_day") or signal_day.isoformat())
    b = brakes(book_index(bars, names, selection_day, signal_day))

    marked = fleet_live.daily_mark(state, bars, cap.equity, float(account["equity"]))
    if marked is not None:
        state = marked
        write_state(state)

    due = decide(state, month, b["trend_on"], mode)
    status = "no rebalance due"
    if due is not None:
        key, held, why = due
        stopped = set() if why == "monthly" else set(state.get("stopped", []))
        s = b["s"] if b["s"] is not None else 0.0
        weights = {} if held == "out" else book_weights(names, s, stopped=stopped, mode=mode)
        prices = {n: (bars.get(n) or [{}])[-1].get("close") for n in names}
        skipped = unaffordable(list(weights), SLOT * s, cap.equity, prices)
        attempts = int(state.get("attempts", 0)) + 1 if state.get("key") == key else 1
        base = {"key": key, "month": month, "held": held, "why": why, "names": names,
                "selection_day": selection_day.isoformat(), "universe_source": universe_source,
                "stopped": sorted(stopped), "trend_on": b["trend_on"], "s": b["s"], "index": b["index"],
                "sma100": b["sma100"], "vol20": b["vol20"], "skipped_unaffordable": skipped,
                "attempts": attempts, "signal_day": signal_day.isoformat(), "at": now.isoformat()}
        write_state({**state, **base, "done": False})

        def plan_fn(*, bars, positions, equity, cash, signal_day, frozen):
            return plan_from_weights(weights=weights, bars=bars, positions=positions, equity=equity,
                                     cash=cash, signal_day=signal_day, price_day=spy[-1]["day"],
                                     frozen=frozen, stop_pct=STOP_PCT, registration=REGISTRATION)

        try:
            report = execute_rebalance(engine, bot_id=bot_id, bars=bars, signal_day=signal_day,
                                       vault=vault, cash_park=cash_park, unpark=unpark,
                                       risk_check=risk_check, plan_fn=plan_fn,
                                       registration=REGISTRATION, exit_reason=EXIT_REASON)
        except Exception as exc:
            msg = f"{REGISTRATION} rebalance attempt {attempts} crashed: {type(exc).__name__}: {exc}"
            write_state({**state, **base, "done": False, "errors": [msg[:300]]})
            alert("critical", msg)
            log.exception(msg)
            return {"status": f"rebalance attempt {attempts} crashed", "mode": mode}
        write_state({**state, **base, "done": report["done"], "errors": report["errors"][:10],
                     "targets": report["plan"].get("weights", {})})
        if report["unprotected"]:
            alert("critical", f"{REGISTRATION}: positions without a protective stop: {report['unprotected']}")
        elif report["errors"]:
            alert("error", f"{REGISTRATION} rebalance attempt {attempts} had errors: {report['errors'][:5]}")
        if skipped:
            alert("warning", f"{REGISTRATION}: names priced above their 2% slot, skipped: {skipped}")
        status = f"rebalanced ({key}, {why})" if report["done"] else f"rebalance attempt {attempts} incomplete"
    elif state.get("month") == month:
        # Keep the brake readings fresh for the dashboard even when nothing trades.
        fresh = {"trend_on": b["trend_on"], "s": b["s"], "index": b["index"], "sma100": b["sma100"],
                 "vol20": b["vol20"]}
        if any(state.get(k) != v for k, v in fresh.items()):
            write_state({**state, **fresh})

    acct = engine.get_account()
    park(engine, engine.get_positions(), acct["cash"])
    return {"status": status, "mode": mode}
