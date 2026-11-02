"""TREND-V1-B live executor on Atlas's (oracle's) Alpaca account.

Runs inside oracle's hourly cycle ONLY when the oracle profile sets
TREND_SLEEVE_LIVE (default off). When on, it replaces Atlas's legacy entries,
exits, trailing stops and take-profits; nothing else trades the account.

Schedule (registered): signal at the first close of each month, trade at the
next open. Live: the first hourly cycle while the market is open after the
month's first close has completed. If that attempt fails, later cycles retry,
at most MAX_ATTEMPTS times and only while the month's completed sessions are
<= EXECUTION_WINDOW_SESSIONS; after that it waits for next month. Every
attempt re-plans against the account as it stands, so a retry never doubles
an order.

Order flow uses the engine's existing, tested primitives only:
  1. sells: close_position (full exit, incl. any fractional remainder) or
     close_partial (re-arms the stop at the new level for what is left);
  2. ask the fleet risk governor (core/risk_governor.py); if it allows new
     risk: unpark SGOV, re-read the account, re-plan, then buys (whole shares,
     scaled to the cash actually there, market orders while open);
  3. every sleeve holding gets its protective stop at the new level, and
     the result is checked; a missing stop is a critical degradation.
Ledger: one open alpaca_etf_positions row per symbol (record_open,
record_resize, close_partial's qty sync, record_close).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable

from sleeve_runtime.trend_v1b import (
    DUST_QTY,
    NEW_YORK,
    REGISTRATION,
    BarFetcher,
    SleeveCapital,
    compute_plan,
    fetch_completed,
    sleeve_capital,
)

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("trend_executor")

STATE_KEY = "trend_v1b"
MAX_ATTEMPTS = 3
EXECUTION_WINDOW_SESSIONS = 3      # trade on the month's sessions 2..4 at the latest
MAX_BAR_AGE_DAYS = 4               # newest final bar older than this = stale feed: never trade
EXIT_REASON = "trend_v1b_rebalance"
FLAT_EXIT_REASON = "broker_flat_stop_filled"
ENTRY_POLLS = 20                   # x 3 s: a market buy while open fills in seconds
GAP_ALLOWANCE = 0.02               # a buy may fill up to 2% above the last close; never spend past cash


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def signal_day_if_due(completed_days: list[date], today_ny: date, state: dict[str, Any]) -> date | None:
    """The month's first completed session if a rebalance is due now, else None.
    A stale feed (no final bar in the last MAX_BAR_AGE_DAYS days) is never due:
    with missing bars the session count, and so the schedule, can't be trusted."""
    if not completed_days or (today_ny - max(completed_days)).days > MAX_BAR_AGE_DAYS:
        return None
    this_month = [d for d in completed_days if (d.year, d.month) == (today_ny.year, today_ny.month)]
    if not this_month or len(this_month) > EXECUTION_WINDOW_SESSIONS:
        return None
    st = state if state.get("month") == month_key(today_ny) else {}
    if st.get("done") or int(st.get("attempts", 0)) >= MAX_ATTEMPTS:
        return None
    return min(this_month)


def ledger_frozen(rows: list[dict[str, Any]], held: dict[str, float]) -> dict[str, str]:
    """Symbols the executor must not touch because the ledger cannot be
    trusted for them: more than one open row, or held with no row."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["symbol"]] = counts.get(r["symbol"], 0) + 1
    frozen = {s: f"{n} open ledger rows" for s, n in counts.items() if n > 1}
    frozen.update({s: "held at broker with no open ledger row" for s in held if s not in counts})
    return frozen


def close_flat_rows(engine, bot_id: str, live: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    """Close ledger rows whose broker position is gone (a protective stop
    filled). Skipped entirely when the broker returned no positions at all
    while rows exist (the known transient empty response)."""
    if not live and rows:
        log.warning("TREND-V1-B | broker returned no positions but ledger has rows; flat check skipped")
        return []
    held = {p["symbol"] for p in live if abs(float(p.get("qty") or 0)) >= DUST_QTY}
    closed = []
    for r in rows:
        sym = r["symbol"]
        if sym in held or engine._has_pending_owned_exit(bot_id, sym):
            continue
        engine.record_close(bot_id, sym, FLAT_EXIT_REASON, None)
        closed.append(sym)
    if closed:
        log.warning(f"TREND-V1-B | ledger rows closed, broker flat: {closed}")
    return closed


def _fresh(engine, bot_id: str, vault: set[str], cash_park: set[str]):
    account = engine.get_account()
    live = engine.get_positions()
    rows = engine.get_db_positions(bot_id)
    cap = sleeve_capital(account, live, vault=vault, cash_park=cash_park)
    return live, rows, cap


def _buy(engine, bot_id: str, sym: str, qty: int, stop: float | None, ref_price: float,
         row: dict | None) -> str | None:
    """One market buy; records the fill. Returns an error string or None.
    Never sends a buy the cash in the account cannot pay for, even if the
    price opened above the last close (no borrowing, ever).

    Top-up of a held symbol: Alpaca always rejects a market buy while a sell
    stop for the same symbol is open (wash-trade protection, see
    docs.alpaca.markets/us/docs/user-protection). So the stop is lifted
    (cancel confirmed) first, and put back for the whole position right after,
    whatever happened to the buy. If the stop can't be lifted, no buy.
    ``stop=None``: a stop-free symbol (FLEET-V1 sleeve 2); none is placed."""
    lifted = False
    if row is not None:
        if not engine._cancel_owned_stop(bot_id, sym, row.get("stop_order_id")):
            return f"{sym}: top-up skipped, its stop could not be lifted"
        lifted = True
    try:
        return _market_buy(engine, bot_id, sym, qty, stop, ref_price, row)
    finally:
        # Protect at once (the lifted stop is gone, so never pass its id); step 3 re-checks every holding.
        if stop is not None:
            engine.ensure_protective_stop(bot_id, sym, stop, None if lifted else (row or {}).get("stop_order_id"))


def _market_buy(engine, bot_id: str, sym: str, qty: int, stop: float, ref_price: float,
                row: dict | None) -> str | None:
    affordable = int(float(engine.get_account()["cash"]) // (ref_price * (1 + GAP_ALLOWANCE)))
    if affordable < qty:
        if affordable < 1:
            return f"{sym}: no cash for even one share"
        qty_note = f"{sym}: cut {qty}->{affordable} to fit cash"
        qty = affordable
    else:
        qty_note = None
    order = engine.buy_market(sym, qty)
    if not order:
        return f"{sym}: buy not accepted"
    res = engine.poll_entry_order(order["order_id"], max_polls=ENTRY_POLLS, interval_seconds=3.0)
    if res["status"] != "filled":
        engine.cancel_order(order["order_id"])
        res = engine.poll_entry_order(order["order_id"], max_polls=3, interval_seconds=2.0)
    filled = float(res.get("filled_qty") or 0)
    if filled <= 0:
        return f"{sym}: buy ended {res['status']} with no fill"
    price = float(res.get("filled_avg_price") or 0)
    live = next((p for p in engine.get_positions() if p["symbol"] == sym), None)
    broker_qty = float(live["qty"]) if live else filled
    if row is None:
        ok = engine.record_open(bot_id, sym, "long", filled, price, None, filled * price,
                                stop, None, None, 0)
    else:
        avg = float(live["entry_price"]) if live else price
        ok = engine.record_resize(bot_id, sym, filled, broker_qty, avg)
    notes = [n for n in (qty_note,
                         None if ok else f"{sym}: filled {filled} but ledger write failed",
                         f"{sym}: partial fill {filled}/{qty}" if filled < qty else None) if n]
    return "; ".join(notes) or None


def execute_rebalance(
    engine,
    *,
    bot_id: str,
    bars: dict[str, list[dict[str, Any]]],
    signal_day: date,
    vault: set[str],
    cash_park: set[str],
    unpark: Callable[[Any, list[dict[str, Any]]], Any],
    risk_check: Callable[[], dict[str, Any]],
    plan_fn: Callable[..., Any] = compute_plan,
    registration: str = REGISTRATION,
    exit_reason: str = EXIT_REASON,
) -> dict[str, Any]:
    """Carry out one rebalance. Returns a report; never leaves a holding
    without a stop attempt. Raises only on a failure before any order.
    plan_fn/registration/exit_reason let another sleeve (GEAR-V1-G4) reuse
    the same order machinery with its own targets."""
    errors: list[str] = []

    # 1. Sells
    live, rows, cap = _fresh(engine, bot_id, vault, cash_park)
    by_row = {r["symbol"]: r for r in rows}
    tp = plan_fn(bars=bars, positions=cap.held, equity=cap.equity, cash=cap.cash,
                 signal_day=signal_day, frozen=ledger_frozen(rows, cap.held))
    first = tp.summary(cap)
    for o in tp.plan.sells:
        row = by_row.get(o.symbol) or {}
        if tp.plan.final_qty.get(o.symbol, 0) == 0:
            pnl = next((p.get("unrealised_pnl_usd") for p in live if p["symbol"] == o.symbol), None)
            if engine.close_position(o.symbol, bot_id=bot_id, stop_order_id=row.get("stop_order_id"),
                                     stop_price=row.get("stop_price")):
                engine.record_close(bot_id, o.symbol, exit_reason, pnl)
            else:
                errors.append(f"{o.symbol}: full exit not confirmed")
        elif not engine.close_partial(o.symbol, o.qty, bot_id=bot_id,
                                      stop_order_id=row.get("stop_order_id"),
                                      stop_price=tp.stop_for(o.symbol)):
            errors.append(f"{o.symbol}: partial sell of {o.qty} not confirmed")

    # 2. Buys, re-planned on the account as it now stands, with only the cash
    #    actually in the account (parked cash counts once it has been sold).
    #    Step-1 failures are already in errors; any new 1-share drift sells
    #    tp2 shows are left for next month rather than churned.
    #    The fleet risk governor may refuse new risk (sells above still ran).
    risk = risk_check() if tp.plan.buys else {"allowed": True, "reasons": []}
    if not risk["allowed"]:
        errors.append(f"buys refused by the risk governor: {risk['reasons']}")
    elif tp.plan.buys:
        unpark(engine, live)
    live, rows, cap = _fresh(engine, bot_id, vault, cash_park)
    by_row = {r["symbol"]: r for r in rows}
    tp2 = plan_fn(bars=bars, positions=cap.held, equity=cap.equity, cash=cap.broker_cash,
                  signal_day=signal_day, frozen=ledger_frozen(rows, cap.held))
    for o in (tp2.plan.buys if risk["allowed"] else []):
        err = _buy(engine, bot_id, o.symbol, o.qty, tp2.stop_for(o.symbol),
                   tp2.prices[o.symbol], by_row.get(o.symbol))
        if err:
            errors.append(err)

    # 3. Protect every sleeve holding at the new level, then check
    live, rows, cap = _fresh(engine, bot_id, vault, cash_park)
    by_row = {r["symbol"]: r for r in rows}
    unprotected = []
    for sym, qty in sorted(cap.held.items()):
        stop = tp2.stop_for(sym)
        if stop is None or sym in tp2.plan.skipped:
            continue   # frozen or unpriced: its existing stop is left as it was
        recorded = (by_row.get(sym) or {}).get("stop_order_id")
        sid = engine.ensure_protective_stop(bot_id, sym, stop, recorded)
        # Check by order id: a stop Alpaca has replaced gets a new client_order_id, so the
        # owner-prefix search alone misses it (the false "SPY unprotected" alerts of 23 Oct).
        if qty >= 1 and engine._find_owned_stop(bot_id, sym, sid or recorded) is None:
            unprotected.append(sym)
    if unprotected:
        errors.append(f"NO PROTECTIVE STOP: {unprotected}")

    return {"registration": registration, "plan": first, "errors": errors,
            "unprotected": unprotected, "done": not errors}


def run_trend_cycle(
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
    """oracle's whole hourly cycle while the sleeve is live."""
    now = now or datetime.now(timezone.utc)
    live = engine.get_positions()
    rows = engine.get_db_positions(bot_id)
    close_flat_rows(engine, bot_id, live, rows)

    if kill_tripped():
        return {"status": "kill switch tripped: no trading"}
    if not engine.is_market_open():
        return {"status": "market closed"}

    status = "no rebalance due"
    today_ny = now.astimezone(NEW_YORK).date()
    month = month_key(today_ny)
    state = read_state() or {}
    if state.get("month") == month and (state.get("done") or int(state.get("attempts", 0)) >= MAX_ATTEMPTS):
        signal_day = None                      # this month is settled; no bar fetch needed
    else:
        cap: SleeveCapital = sleeve_capital(engine.get_account(), live, vault=vault, cash_park=cash_park)
        bars = fetch_completed(fetch_bars, cap.held, now)
        completed_days = sorted({b["day"] for s in bars.values() for b in s})
        signal_day = signal_day_if_due(completed_days, today_ny, state)
    if signal_day is not None:
        attempts = int(state.get("attempts", 0)) + 1 if state.get("month") == month else 1
        # Record the attempt BEFORE any order, so a crash mid-way cannot loop.
        base = {"month": month, "attempts": attempts, "signal_day": signal_day.isoformat(),
                "at": now.isoformat()}
        write_state({**base, "done": False})
        try:
            report = execute_rebalance(engine, bot_id=bot_id, bars=bars, signal_day=signal_day,
                                       vault=vault, cash_park=cash_park, unpark=unpark,
                                       risk_check=risk_check)
        except Exception as exc:
            # Each buy is protected as it fills, and the next cycle's stop
            # reconciliation re-arms from the ledger; still, a human looks now.
            msg = f"TREND-V1-B rebalance attempt {attempts} crashed: {type(exc).__name__}: {exc}"
            write_state({**base, "done": False, "errors": [msg[:300]]})
            alert("critical", msg)
            log.exception(msg)
            return {"status": f"rebalance attempt {attempts} crashed"}
        write_state({**base, "done": report["done"], "errors": report["errors"][:10]})
        log.info(f"TREND-V1-B rebalance | attempt {attempts} | {report}")
        if report["unprotected"]:
            alert("critical", f"TREND-V1-B: positions without a protective stop: {report['unprotected']}")
        elif report["errors"]:
            alert("error", f"TREND-V1-B rebalance attempt {attempts} had errors: {report['errors'][:5]}")
        status = "rebalanced" if report["done"] else f"rebalance attempt {attempts} incomplete"

    acct = engine.get_account()
    park(engine, engine.get_positions(), acct["cash"])
    return {"status": status}
