"""GEAR-V1-G4 live on Atlas's (oracle's) Alpaca account.

Markus's decision (23 Oct 2026, 09:43 Brisbane): run G4 exactly as tested,
in Atlas's account, even though it failed the held-out drawdown bar (its
worst fall equalled SPY's; research_harness/explore/GEAR-V1-PLAN.md). The
TREND-V1-B cutover planned for Atlas is cancelled.

Rules (the registered candidate, unchanged; research_harness/sleeves/gear.py):
- Gear from SPY's completed daily closes: at or below its 200-day average ->
  safe (all cash, parked in SGOV); above it and 20-day volatility <= 20% ->
  aggressive (SPY, QQQ, SSO, QLD 25% each = 1.5x exposure); above it with
  higher volatility -> normal (SPY, QQQ 50% each).
- Rebalance only when the gear changes or a new month starts (signal at a
  close, trade at the next session), every holding with a 20% protective
  stop re-set at each rebalance, whole shares, no borrowing.
Live differences (necessary, small): a 1% cash buffer; orders go in on the
first hourly cycle while the market is open, not exactly at the open.

The order machinery is the tested TREND-V1-B executor
(sleeve_runtime/trend_executor.execute_rebalance) with G4's targets.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from research_harness.explore.gear_v1 import STOP_PCT, SYMBOLS
from research_harness.sleeves.gear import CANDIDATES, SMA_SESSIONS, gear_for
from sleeve_runtime.trend_executor import (
    MAX_ATTEMPTS,
    MAX_BAR_AGE_DAYS,
    close_flat_rows,
    execute_rebalance,
)
from sleeve_runtime.trend_v1b import (
    NEW_YORK,
    BarFetcher,
    TrendPlan,
    completed_bars,
    plan_from_weights,
    sleeve_capital,
)

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("gear_live")

REGISTRATION = "GEAR-V1-G4"
CANDIDATE = "G4"
STATE_KEY = "gear_v1_g4"
EXIT_REASON = "gear_v1_g4_rebalance"
SIGNAL = "SPY"
HISTORY_CALENDAR_DAYS = 420          # > 200 sessions of SPY for the gear


def gear_on(bars: dict[str, list[dict[str, Any]]], day: date) -> str | None:
    """G4's gear from SPY closes up to and including ``day``."""
    closes = [b["close"] for b in bars.get(SIGNAL, []) if b["day"] <= day]
    return gear_for(closes[-(SMA_SESSIONS + 1):]) if closes else None


def target_weights(gear: str | None) -> dict[str, float]:
    return {} if gear in (None, "safe") else dict(CANDIDATES[CANDIDATE][gear])


def compute_gear_plan(
    *,
    bars: dict[str, list[dict[str, Any]]],
    positions: dict[str, float],
    equity: float,
    cash: float,
    signal_day: date | None = None,
    frozen: dict[str, str] | None = None,
) -> TrendPlan:
    """Pure. Same plan shape as TREND-V1-B, with G4's weights."""
    spy = bars.get(SIGNAL) or []
    if not spy:
        raise ValueError("no SPY bars")
    price_day = spy[-1]["day"]
    signal_day = signal_day or price_day
    if signal_day > price_day:
        raise ValueError("signal day is after the latest bar")
    gear = gear_on(bars, signal_day)
    if gear is None:
        raise ValueError("not enough SPY history for the gear")
    return plan_from_weights(weights=target_weights(gear), bars=bars, positions=positions,
                             equity=equity, cash=cash, signal_day=signal_day, price_day=price_day,
                             frozen=frozen, stop_pct=STOP_PCT, registration=REGISTRATION)


def rebalance_key(day: date, gear: str) -> str:
    """A rebalance is due whenever this changes: new month or new gear."""
    return f"{day.year:04d}-{day.month:02d}|{gear}"


def gear_due(bars: dict[str, list[dict[str, Any]]], today_ny: date,
             state: dict[str, Any]) -> tuple[date, str, str] | None:
    """(signal day, gear, key) if a rebalance is due now, else None.
    A stale feed (no final SPY bar in the last MAX_BAR_AGE_DAYS days) is
    never due."""
    spy = bars.get(SIGNAL) or []
    if not spy or (today_ny - spy[-1]["day"]).days > MAX_BAR_AGE_DAYS:
        return None
    signal_day = spy[-1]["day"]
    gear = gear_on(bars, signal_day)
    if gear is None:
        return None
    key = rebalance_key(signal_day, gear)
    if state.get("key") == key and (state.get("done") or int(state.get("attempts", 0)) >= MAX_ATTEMPTS):
        return None
    return signal_day, gear, key


def fetch_gear_bars(fetch_bars: BarFetcher, held: dict[str, float], now: datetime):
    """G4's symbols plus anything held (legacy holdings get a price to sell)."""
    symbols = sorted(set(SYMBOLS) | set(held))
    return completed_bars(fetch_bars(symbols, now.date() - timedelta(days=HISTORY_CALENDAR_DAYS)), now)


def run_gear_cycle(
    engine,
    *,
    bot_id: str,
    fetch_bars: BarFetcher,
    vault: set[str],
    cash_park: set[str],
    read_state: Callable[[], dict[str, Any]],
    write_state: Callable[[dict[str, Any]], None],
    kill_tripped: Callable[[], bool],
    unpark: Callable[[Any, list[dict[str, Any]]], Any],
    park: Callable[[Any, list[dict[str, Any]], float], Any],
    alert: Callable[[str, str], None],
    risk_check: Callable[[], dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """oracle's whole hourly cycle while G4 is live."""
    now = now or datetime.now(timezone.utc)
    live = engine.get_positions()
    rows = engine.get_db_positions(bot_id)
    close_flat_rows(engine, bot_id, live, rows)

    if kill_tripped():
        return {"status": "kill switch tripped: no trading"}
    if not engine.is_market_open():
        return {"status": "market closed"}

    status = "no rebalance due"
    state = read_state() or {}
    cap = sleeve_capital(engine.get_account(), live, vault=vault, cash_park=cash_park)
    bars = fetch_gear_bars(fetch_bars, cap.held, now)
    due = gear_due(bars, now.astimezone(NEW_YORK).date(), state)
    if due is not None:
        signal_day, gear, key = due
        attempts = int(state.get("attempts", 0)) + 1 if state.get("key") == key else 1
        # Record the attempt BEFORE any order, so a crash mid-way cannot loop.
        base = {"key": key, "gear": gear, "attempts": attempts,
                "signal_day": signal_day.isoformat(), "at": now.isoformat()}
        write_state({**base, "done": False})
        try:
            report = execute_rebalance(engine, bot_id=bot_id, bars=bars, signal_day=signal_day,
                                       vault=vault, cash_park=cash_park, unpark=unpark,
                                       risk_check=risk_check, plan_fn=compute_gear_plan,
                                       registration=REGISTRATION, exit_reason=EXIT_REASON)
        except Exception as exc:
            msg = f"GEAR-V1-G4 rebalance attempt {attempts} crashed: {type(exc).__name__}: {exc}"
            write_state({**base, "done": False, "errors": [msg[:300]]})
            alert("critical", msg)
            log.exception(msg)
            return {"status": f"rebalance attempt {attempts} crashed"}
        write_state({**base, "done": report["done"], "errors": report["errors"][:10]})
        log.info(f"GEAR-V1-G4 rebalance | gear={gear} | attempt {attempts} | {report}")
        if report["unprotected"]:
            alert("critical", f"GEAR-V1-G4: positions without a protective stop: {report['unprotected']}")
        elif report["errors"]:
            alert("error", f"GEAR-V1-G4 rebalance attempt {attempts} had errors: {report['errors'][:5]}")
        status = f"rebalanced to {gear}" if report["done"] else f"rebalance attempt {attempts} incomplete"

    acct = engine.get_account()
    park(engine, engine.get_positions(), acct["cash"])
    return {"status": status}
