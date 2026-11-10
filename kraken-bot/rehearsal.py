"""Rehearsal: run the live order machinery on Bot 3's idle account with 1-share orders.

Why (finance-2027-plan.md, Step 2 item 9a): two of the last three incidents
happened the first time new code traded. Until the record starts (23 Nov 2026)
Bot 3 (spy_qqq_trend) holds only cash, so new trading paths are rehearsed there
first, through the same engine and executor the bots use. After the start: no
live-account rehearsals (fake-broker and replay tests, then one bot first).

Scenario (each step checked against the broker and the ledger):
  1 buy 1 SPY                    4 stop removed, then repaired (the paused-bot check)
  2 top up to 2 (stop lifted)    5 full close
  3 partial sell to 1 (9 Nov)    6 2x gold / silver funds: tradable? buy 1, protect, close

Rows use the ledger tag bot_id='rehearsal' (own client-order-id prefixes, never
mixed with the strategy's rows); reconciliation counts them as Bot 3's account.

Dry run (default): checks the preconditions and prints the plan; sends nothing.
Live, from the Replit workspace shell, Bot 3 paused, US market open:
    PGOPTIONS= python3 kraken-bot/rehearsal.py --live
(PGOPTIONS= lifts the workspace's read-only database guard for this one command.)
Exit code 0 = every step passed and the account is back to cash.
"""
from __future__ import annotations

import argparse
import math
import os
import pathlib
import sys
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "trading-platform"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sleeve_runtime.trend_executor import execute_rebalance, fixed_targets_plan  # noqa: E402

ACCOUNT = "spy_qqq_trend"          # Bot 3's Alpaca paper account
TAG = "rehearsal"                  # ledger bot_id and client-order-id owner
VAULT, CASH_PARK = {"BIL", "VOO"}, {"SGOV"}
STOP_BELOW = 0.20                  # stops far away: a rehearsal stop must never fill
TWO_X_FUNDS = ("UGL", "AGQ")       # 2x gold, 2x silver (Bot 3's planned sleeve)


class StepFailed(Exception):
    pass


def preconditions(engine, *, bot_paused: bool) -> list[str]:
    """Reasons the rehearsal must not run; empty = clear to go."""
    problems = []
    if not bot_paused:
        problems.append(f"{ACCOUNT} is not paused (pause Bot 3 first)")
    if not engine.is_market_open():
        problems.append("US market is closed (market orders would not fill)")
    held = [p["symbol"] for p in engine.get_positions()
            if p["symbol"] not in VAULT | CASH_PARK and abs(float(p["qty"])) > 1e-9]
    if held:
        problems.append(f"account holds stock positions: {held} (rehearsal needs an all-cash account)")
    open_orders = engine.api.list_orders(status="open", limit=100, nested=True)
    if open_orders:
        problems.append(f"account has {len(open_orders)} open order(s)")
    if engine.get_db_positions(TAG):
        problems.append("open 'rehearsal' ledger rows left from an earlier run")
    return problems


def _price(engine, symbol: str) -> float:
    return float(engine.api.get_latest_trade(symbol).price)


def _rebalance(engine, targets: dict[str, int], stops: dict[str, float], prices: dict[str, float]):
    return execute_rebalance(
        engine, bot_id=TAG, bars={}, signal_day=None, vault=VAULT, cash_park=CASH_PARK,
        unpark=lambda e, live: None, risk_check=lambda: {"allowed": True, "reasons": []},
        plan_fn=fixed_targets_plan(targets, prices, stops))


def _check(engine, symbol: str, qty: int, report: dict[str, Any] | None = None) -> None:
    """Broker, stop and ledger all agree on ``qty`` shares, each share under one live stop."""
    if report is not None and report["errors"]:
        raise StepFailed(f"executor errors: {report['errors']}")
    live = next((p for p in engine.get_positions() if p["symbol"] == symbol), None)
    held = 0 if live is None else float(live["qty"])
    if held != qty:
        raise StepFailed(f"{symbol}: broker holds {held}, expected {qty}")
    stops = [o for o in engine.api.list_orders(status="open", limit=100, nested=True)
             if o.symbol == symbol and o.side == "sell" and o.type in {"stop", "stop_limit"}
             and engine._still_open(o)]
    rows = [r for r in engine.get_db_positions(TAG) if r["symbol"] == symbol]
    if qty == 0:
        if stops or rows:
            raise StepFailed(f"{symbol}: flat but {len(stops)} stop(s) / {len(rows)} ledger row(s) left")
        return
    if len(stops) != 1 or math.floor(float(stops[0].qty)) != qty:
        raise StepFailed(f"{symbol}: expected one stop for {qty}, found {[(s.id, s.qty) for s in stops]}")
    if len(rows) != 1 or rows[0].get("stop_order_id") != stops[0].id:
        raise StepFailed(f"{symbol}: ledger stop id does not match the live stop")


def scenario(engine) -> list[tuple[str, Any]]:
    """The steps, in order: (name, callable). Each callable raises StepFailed."""
    px = {"SPY": _price(engine, "SPY")}
    stop = {"SPY": round(px["SPY"] * (1 - STOP_BELOW), 2)}

    def step(target):
        return lambda: _check(engine, "SPY", target, _rebalance(engine, {"SPY": target}, stop, px))

    def stop_lost_and_repaired():
        row = next(r for r in engine.get_db_positions(TAG) if r["symbol"] == "SPY")
        if not engine._cancel_owned_stop(TAG, "SPY", row.get("stop_order_id")):
            raise StepFailed("could not remove the stop to rehearse its repair")
        engine.reconcile_protective_stops(TAG, engine.get_db_positions(TAG))
        _check(engine, "SPY", 1)

    def two_x_funds():
        notes = []
        for sym in TWO_X_FUNDS:
            asset = engine.api.get_asset(sym)
            if not (getattr(asset, "tradable", False) and getattr(asset, "status", "") == "active"):
                notes.append(f"{sym}: NOT tradable on Alpaca paper")
                continue
            p = {sym: _price(engine, sym)}
            s = {sym: round(p[sym] * (1 - STOP_BELOW), 2)}
            _check(engine, sym, 1, _rebalance(engine, {sym: 1}, s, p))
            _check(engine, sym, 0, _rebalance(engine, {sym: 0}, s, p))
            notes.append(f"{sym}: tradable; buy, stop and close OK")
        return notes

    return [
        ("1 buy 1 SPY", step(1)),
        ("2 top up to 2 SPY (stop lifted, then the whole position protected)", step(2)),
        ("3 partial sell to 1 SPY (the 9 Nov path)", step(1)),
        ("4 stop removed, then repaired by the stop check", stop_lost_and_repaired),
        ("5 full close", step(0)),
        ("6 2x gold / silver funds", two_x_funds),
    ]


def flatten(engine) -> None:
    """Best effort after a failed step: close every rehearsal holding and its stop."""
    for row in engine.get_db_positions(TAG):
        sym = row["symbol"]
        if engine.close_position(sym, bot_id=TAG, stop_order_id=row.get("stop_order_id")):
            engine.record_close(TAG, sym, "rehearsal_cleanup", None)


def run(engine, *, bot_paused: bool, live: bool, out=print) -> int:
    problems = preconditions(engine, bot_paused=bot_paused)
    for p in problems:
        out(f"BLOCKED: {p}")
    steps = scenario(engine) if not problems else []
    if problems:
        return 2
    if not live:
        out("DRY RUN: preconditions met. Steps that --live would run:")
        for name, _ in steps:
            out(f"  {name}")
        return 0
    failed = False
    for name, fn in steps:
        try:
            result = fn()
            out(f"PASS  {name}" + (f": {'; '.join(result)}" if result else ""))
        except Exception as exc:              # report, clean up, stop
            out(f"FAIL  {name}: {exc}")
            failed = True
            break
    if failed:
        flatten(engine)
    leftovers = engine.get_db_positions(TAG)
    out("CLEAN: account back to cash" if not leftovers
        else f"NOT CLEAN: rehearsal rows still open: {[r['symbol'] for r in leftovers]}")
    return 1 if failed or leftovers else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="send real paper orders (default: dry run)")
    args = ap.parse_args()
    import importlib.util
    # kraken-bot/config.py by path (trading-platform has its own config package), as runner.py does.
    spec = importlib.util.spec_from_file_location("_kraken_local_config",
                                                  pathlib.Path(__file__).with_name("config.py"))
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    from core.bot_state import get_bot_state
    from alpaca_etf_engine import AlpacaEtfEngine
    profile = cfg.BOT_PROFILES["bot2_spy_qqq"]      # Bot 3's account keys (legacy profile name)
    engine = AlpacaEtfEngine(profile["ALPACA_API_KEY"], profile["ALPACA_SECRET_KEY"],
                             profile.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"))
    os.environ.setdefault("RUNNER_ENVIRONMENT", "dev")
    return run(engine, bot_paused=bool(get_bot_state(ACCOUNT).get("paused")), live=args.live)


if __name__ == "__main__":
    sys.exit(main())
