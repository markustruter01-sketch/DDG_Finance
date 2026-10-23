"""Forex execution (Phase 5): carry out the day's AI decision on the OANDA
PRACTICE account, once per New York trading day.

Order of work, every attempt:
1. Read the newest decision-ledger row. Nothing to do if it was already
   executed, is older than MAX_DECISION_AGE_DAYS (logged as stale), or has
   no AI decision (logged: no new trades).
2. Read the account; close ledger rows whose OANDA trade is gone (a stop
   filled). If the market is not tradeable yet (weekend), wait.
3. The risk officer (forex_risk.py) plans closes and opens.
4. Closes first, then opens: each open is a fill-or-kill market order with
   its stop attached; the new trade is then read back and must show its
   stop, or it is closed at once and reported as critical.
5. The whole report is stored (forex_execution_log, one row per day).
Never raises; failures are reported and nothing is retried in a loop.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from forex_risk import plan_forex_actions, price_decimals, stop_price

try:
    from loguru import logger as log
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("forex_execution")

MAX_DECISION_AGE_DAYS = 4          # Friday's decision may wait for Sunday's reopen
NEW_YORK = ZoneInfo("America/New_York")
# Spreads are widest around the 17:00 New York daily rollover; no orders then.
ROLLOVER_QUIET = (time(16, 45), time(18, 0))
EXECUTION_DDL = """
CREATE TABLE IF NOT EXISTS forex_execution_log (
    trading_day  DATE PRIMARY KEY,
    executed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    report       JSONB NOT NULL
)
"""


class PgForexStore:
    """forex_decision_ledger (read), forex_ai_trades and forex_execution_log."""

    def __init__(self, get_conn: Callable[[], Any]):
        self._get_conn = get_conn

    def _run(self, sql: str, params: tuple = (), fetch: str | None = None):
        with self._get_conn() as conn, conn.cursor() as cur:
            cur.execute(EXECUTION_DDL)
            cur.execute(sql, params)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return None

    def latest_decision(self) -> dict[str, Any] | None:
        row = self._run("""SELECT trading_day, status, low_confidence, record
                           FROM forex_decision_ledger ORDER BY trading_day DESC LIMIT 1""", fetch="one")
        if not row:
            return None
        record = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        return {"trading_day": row[0], "status": row[1], "low_confidence": bool(row[2]), "record": record}

    def already_executed(self, day: date) -> bool:
        return self._run("SELECT 1 FROM forex_execution_log WHERE trading_day = %s", (day,), "one") is not None

    def last_nav(self) -> float | None:
        row = self._run("""SELECT report->>'nav' FROM forex_execution_log
                           WHERE report ? 'nav' ORDER BY trading_day DESC LIMIT 1""", fetch="one")
        return float(row[0]) if row and row[0] is not None else None

    def log_execution(self, day: date, report: dict[str, Any]) -> None:
        self._run("""INSERT INTO forex_execution_log (trading_day, report) VALUES (%s, %s::jsonb)
                     ON CONFLICT (trading_day) DO NOTHING""", (day, json.dumps(report, default=str)))

    def open_trade_ids(self) -> set[str]:
        rows = self._run("SELECT trade_id FROM forex_ai_trades WHERE lower(status) = 'open'", fetch="all")
        return {str(r[0]) for r in rows or []}

    def mark_closed(self, trade_ids: list[str], now: datetime) -> None:
        for trade_id in trade_ids:
            self._run("""UPDATE forex_ai_trades SET status = 'closed', closed_at = %s
                         WHERE trade_id = %s AND lower(status) = 'open'""", (now, trade_id))

    def insert_open(self, trade: dict[str, Any], now: datetime) -> None:
        self._run("""INSERT INTO forex_ai_trades
                     (trade_id, instrument, signed_units, entry_price, stop_order_id, status, opened_at)
                     VALUES (%s, %s, %s, %s, %s, 'open', %s) ON CONFLICT (trade_id) DO NOTHING""",
                  (trade["trade_id"], trade["instrument"], trade["signed_units"], trade["entry_price"],
                   trade["stop_order_id"], now))


def run_forex_execution(
    *,
    reader,                                   # core.oanda_client.OandaClient (read-only)
    trader,                                   # core.oanda_trader.OandaTrader (orders)
    store,                                    # PgForexStore or a test double
    snapshot: Callable[[Any], dict[str, Any]],  # core.kill_switch.read_oanda_account_snapshot
    sheet_rows: list[dict[str, Any]],
    max_gross: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    try:
        return _execute(reader, trader, store, snapshot, sheet_rows, max_gross, now)
    except Exception as exc:  # never stop the account monitor
        log.exception("FOREX execution failed")
        return {"status": f"failed: {type(exc).__name__}: {str(exc)[:120]}"}


def _execute(reader, trader, store, snapshot, sheet_rows, max_gross, now) -> dict[str, Any]:
    latest = store.latest_decision()
    if latest is None:
        return {"status": "no decision logged yet"}
    day: date = latest["trading_day"]
    if store.already_executed(day):
        return {"status": f"already executed {day}"}
    if (now.date() - day).days > MAX_DECISION_AGE_DAYS:
        store.log_execution(day, {"status": "stale decision: not executed"})
        return {"status": f"stale decision {day}: not executed"}
    if latest["status"] != "shadow" or not latest["record"].get("decisions"):
        store.log_execution(day, {"status": "no AI decision: no new trades",
                                  "errors": latest["record"].get("errors", [])[:5]})
        return {"status": f"no AI decision for {day}"}

    account = snapshot(reader)
    oanda_ids = {str(t["trade_id"]) for t in account["open_trades"]}
    gone = sorted(store.open_trade_ids() - oanda_ids)
    if gone:
        store.mark_closed(gone, now)
    decisions = latest["record"]["decisions"]
    ny_time = now.astimezone(NEW_YORK).time()
    if ROLLOVER_QUIET[0] <= ny_time < ROLLOVER_QUIET[1]:
        return {"status": f"rollover hour (wide spreads): waiting to execute {day}"}
    first_pair = decisions[0]["pair"]
    if not reader.current_bid_ask(first_pair).get("tradeable"):
        return {"status": f"market not tradeable: waiting to execute {day}"}

    plan = plan_forex_actions(
        decisions=decisions,
        rows_by_pair={r["pair"]: r for r in sheet_rows if "error" not in r},
        nav=float(account["nav"]),
        open_trades=account["open_trades"],
        low_confidence=bool(latest["low_confidence"]),
        nav_at_last_cycle=store.last_nav(),
        max_gross=max_gross,
    )
    report: dict[str, Any] = {"status": "executed", "trading_day": day.isoformat(),
                              "nav": float(account["nav"]), "checks": plan["checks"],
                              "skipped": plan["skipped"], "closed_at_broker": gone,
                              "closes": [], "opens": [], "errors": []}

    for close in plan["closes"]:
        res = trader.close_trade(close["trade_id"])
        report["closes"].append({**close, **res})
        if res["closed"] or res["already_closed"]:
            store.mark_closed([close["trade_id"]], now)
        else:
            report["errors"].append(f"{close['pair']}: close failed ({res['reason']})")

    for want in plan["opens"]:
        pair = want["pair"]
        quote = reader.current_bid_ask(pair)
        mid = (float(quote["bid"]) + float(quote["ask"])) / 2
        level = stop_price(pair, want["direction"], mid, want["stop_distance"])
        res = trader.market_order(pair, int(want["units"]), f"{level:.{price_decimals(pair)}f}")
        entry = {**want, "stop_price": level, **res}
        if not res["filled"]:
            report["opens"].append(entry)
            report["errors"].append(f"{pair}: not filled ({res['reason']})")
            continue
        live = next((t for t in snapshot(reader)["open_trades"] if str(t["trade_id"]) == res["trade_id"]), None)
        if live is None or not live.get("stop_order_id"):
            # A trade without its stop is never left open.
            closed = trader.close_trade(res["trade_id"])
            entry["closed_unprotected"] = closed
            report["errors"].append(f"CRITICAL {pair}: filled without a confirmed stop; closed={closed['closed']}")
            report["opens"].append(entry)
            continue
        store.insert_open({"trade_id": res["trade_id"], "instrument": pair,
                           "signed_units": live["signed_units"], "entry_price": live["entry_price"],
                           "stop_order_id": live["stop_order_id"]}, now)
        report["opens"].append(entry)

    if report["errors"]:
        report["status"] = "executed with errors"
    store.log_execution(day, report)
    log.info(f"FOREX execution | {json.dumps(report, default=str, separators=(',', ':'))[:1500]}")
    return report
