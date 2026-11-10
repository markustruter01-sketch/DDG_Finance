"""Run the real AlpacaEtfEngine and trend executor against FakeAlpaca and the
local test database. Shared by the broker-quirk and replay tests."""
from __future__ import annotations

import math
import os
import pathlib
import sys
from datetime import date

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
# Same order as the other kraken-bot engine tests: trading-platform first, so
# kraken-bot/db.py never shadows the trading-platform db package.
sys.path.insert(0, str(_ROOT / "trading-platform"))
sys.path.insert(1, str(_ROOT / "kraken-bot"))
sys.path.insert(2, str(_ROOT))


def _database_is_local() -> bool:
    import ipaddress
    import socket
    from urllib.parse import urlparse
    host = urlparse(os.environ.get("DATABASE_URL", "")).hostname
    try:
        return bool(host) and ipaddress.ip_address(socket.gethostbyname(host)).is_loopback
    except (OSError, ValueError):
        return False


# 🔴 These tests DELETE ledger rows for the bots they simulate. They run only
# against a database on this machine; anywhere else (in Replit, DATABASE_URL is
# production) the whole module is skipped before any connection is opened.
if not _database_is_local():
    pytest.skip("broker tests need a local test database (DATABASE_URL is not on this machine)",
                allow_module_level=True)

# Bind "db" to the trading-platform package now, while the order above holds:
# pytest may put kraken-bot first again when it imports the next test file.
import db.postgres  # noqa: E402,F401

import alpaca_etf_engine as etf_engine_module  # noqa: E402
from alpaca_etf_engine import AlpacaEtfEngine  # noqa: E402
from core.cash_park import is_cash_park  # noqa: E402
from core.stop_policy import stop_exempt  # noqa: E402
from sleeve_runtime.planner import Order, RebalancePlan, StopAction  # noqa: E402
from sleeve_runtime.trend_v1b import TrendPlan  # noqa: E402

from fake_alpaca import FakeAlpaca  # noqa: E402

VAULT = {"BIL", "VOO"}   # vault holdings: never stopped
needs_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs the local test database")


def db_exec(sql: str, params=()):
    from db.postgres import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else None


def make_engine(monkeypatch, broker: FakeAlpaca, bot_ids=("oracle",)) -> AlpacaEtfEngine:
    """Real engine, fake broker, virtual time, clean ledger rows for these bots."""
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "published")
    monkeypatch.setattr(etf_engine_module, "time", broker.clock)
    monkeypatch.setattr("notifications.discord.notify_capital_risk", lambda *a, **k: None, raising=False)
    # Test database: only the alarm table the engine writes to (full columns as in db/postgres.py).
    db_exec("""CREATE TABLE IF NOT EXISTS system_degradations (
        id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(), component TEXT NOT NULL,
        severity TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT NOT NULL, detail TEXT,
        bot_id TEXT, cycle_id TEXT, resolved_at TIMESTAMPTZ, resolved_reason TEXT)""")
    engine = object.__new__(AlpacaEtfEngine)
    engine.api = broker
    engine._ensure_schema()
    for bot in bot_ids:
        db_exec("DELETE FROM alpaca_etf_positions WHERE bot_id = %s", (bot,))
        db_exec("DELETE FROM system_degradations WHERE component = %s", (bot,))
    return engine


def seed_holding(engine, broker: FakeAlpaca, bot_id: str, symbol: str, qty: float,
                 stop: float | None = None) -> str | None:
    """A position the bot already holds: broker shares, ledger row and (optionally) its live stop."""
    price = broker.prices[symbol]
    broker.positions[symbol] = float(qty)
    broker._entry[symbol] = price
    engine.record_open(bot_id, symbol, "long", qty, price, None, qty * price, stop, None, None, 0)
    if stop is None:
        return None
    from core.order_ids import make_client_order_id
    sid = broker.seed_stop(symbol, math.floor(qty), stop, make_client_order_id(f"etf-stop-{bot_id}-{symbol}"))
    engine._store_stop_order_id(bot_id, symbol, sid, stop_price=stop)
    return sid


def ledger(bot_id: str) -> dict[str, dict]:
    rows = db_exec("""SELECT symbol, qty, current_qty, stop_price, stop_order_id
                        FROM alpaca_etf_positions WHERE bot_id = %s AND status = 'open'""", (bot_id,))
    return {r[0]: {"qty": float(r[1]), "current_qty": None if r[2] is None else float(r[2]),
                   "stop_price": None if r[3] is None else float(r[3]), "stop_order_id": r[4]}
            for r in rows}


def critical_alarms(bot_id: str) -> list[str]:
    rows = db_exec("""SELECT detail FROM system_degradations
                       WHERE component = %s AND severity = 'critical'""", (bot_id,))
    return [r[0] or "" for r in rows]


def fixed_plan(targets: dict[str, int], prices: dict[str, float], stops: dict[str, float],
               day: date = date(2026, 11, 9)):
    """plan_fn for execute_rebalance: move each symbol to a fixed share count.
    Symbols without an entry in ``stops`` are stop-free (FLEET-V1 sleeve 2)."""
    def plan_fn(*, bars, positions, equity, cash, signal_day, frozen):
        plan = RebalancePlan()
        for sym in sorted(set(targets) | set(positions)):
            cur, tgt = int(positions.get(sym, 0)), int(targets.get(sym, int(positions.get(sym, 0))))
            if frozen and sym in frozen:
                plan.skipped[sym] = "frozen"
                tgt = cur
            elif tgt < cur:
                plan.cancel_stops.append(sym)
                plan.sells.append(Order(sym, "sell", cur - tgt))
            elif tgt > cur:
                plan.buys.append(Order(sym, "buy", tgt - cur))
            if tgt > 0:
                plan.final_qty[sym] = tgt
                if sym in stops and sym not in plan.skipped:
                    plan.stops.append(StopAction(sym, "replace" if tgt == cur else "place", tgt, stops[sym]))
        return TrendPlan(plan=plan, weights={}, signal_day=day, price_day=day, prices=dict(prices))
    return plan_fn


def protection_report(broker: FakeAlpaca, bot_id: str, report_unprotected=()) -> dict[str, str]:
    """For every holding that needs a stop: 'protected', 'alarmed' or 'NAKED'.
    'alarmed' = no stop, but the executor reported it or a critical alarm names it."""
    alarms = " ".join(critical_alarms(bot_id))
    out = {}
    for sym, qty in sorted(broker.positions.items()):
        if qty < 1 or is_cash_park(sym) or stop_exempt(bot_id, sym) or sym in VAULT:
            continue
        covered = sum(o.qty for o in broker.open_stops(sym))
        if covered >= math.floor(qty):
            out[sym] = "protected"
        elif sym in report_unprotected or f"symbol={sym}" in alarms:
            out[sym] = "alarmed"
        else:
            out[sym] = "NAKED"
    return out
