"""Forex execution against fake OANDA reader/trader and a fake store; plus the
SQL store against a throwaway local Postgres (skipped anywhere else)."""
from __future__ import annotations

import ipaddress
import os
import socket
import sys
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trading-platform"))

import forex_execution as fx

NOW = datetime(2026, 10, 26, 23, 30, tzinfo=timezone.utc)        # Mon 19:30 New York
DAY = date(2026, 10, 26)
ROWS = [{"pair": "EUR_USD", "close": 1.08, "atr": 0.006},
        {"pair": "USD_JPY", "close": 150.0, "atr": 1.0}]


def _record(decisions, status="shadow", low=False):
    return {"trading_day": DAY, "status": status, "low_confidence": low,
            "record": {"decisions": decisions, "errors": []}}


class FakeStore:
    def __init__(self, latest, open_ids=(), executed=False, last_nav=None):
        self.latest, self.ids, self.executed, self.nav = latest, set(open_ids), executed, last_nav
        self.logged, self.closed, self.inserted = [], [], []

    def latest_decision(self): return self.latest
    def already_executed(self, day): return self.executed
    def last_nav(self): return self.nav
    def log_execution(self, day, report): self.logged.append((day, report))
    def open_trade_ids(self): return set(self.ids)
    def mark_closed(self, ids, now): self.closed.extend(ids); self.ids -= set(ids)
    def insert_open(self, trade, now): self.inserted.append(trade); self.ids.add(trade["trade_id"])


class FakeOanda:
    """Reader + trader + snapshot in one: OANDA's state as a dict of trades."""

    def __init__(self, trades=None, tradeable=True, attach_stops=True, fill=True, unclear=False):
        self.trades = dict(trades or {})
        self.tradeable, self.attach_stops, self.fill, self.unclear = tradeable, attach_stops, fill, unclear
        self.orders, self._id = [], 100

    def current_bid_ask(self, pair):
        mid = {"EUR_USD": 1.0812, "USD_JPY": 150.40}.get(pair, 1.0)
        return {"bid": mid - 0.0001, "ask": mid + 0.0001, "tradeable": self.tradeable}

    def market_order(self, pair, units, stop_price):
        self.orders.append(("open", pair, units, stop_price))
        if self.unclear:
            return {"filled": False, "trade_id": None, "price": None, "units": None, "unclear": True,
                    "client_id": "pub-fx-eur_usd-0123456789abcdef",
                    "reason": "unclear answer (HTTP 504) and read-back failed: may have filled"}
        if not self.fill:
            return {"filled": False, "trade_id": None, "price": None, "units": None, "reason": "MARKET_HALTED"}
        self._id += 1
        tid = str(self._id)
        self.trades[tid] = {"trade_id": tid, "instrument": pair, "signed_units": float(units),
                            "entry_price": 1.0, "market_value": abs(units),
                            "stop_order_id": f"s{tid}" if self.attach_stops else None}
        return {"filled": True, "trade_id": tid, "price": "1.0", "units": str(units), "reason": None}

    def close_trade(self, trade_id):
        self.orders.append(("close", trade_id))
        gone = self.trades.pop(trade_id, None) is None
        return {"closed": not gone, "already_closed": gone, "price": "1.0", "pl": "0", "reason": None}

    def snapshot(self, _reader):
        return {"nav": 100_000.0, "open_trades": list(self.trades.values())}


def _run(store, oanda, now=NOW):
    return fx.run_forex_execution(reader=oanda, trader=oanda, store=store, snapshot=oanda.snapshot,
                                  sheet_rows=ROWS, max_gross=2.0, now=now)


def _d(pair, direction):
    return {"pair": pair, "direction": direction, "conviction": 3, "stop_atr_multiple": 2.0}


def test_opens_with_stops_records_the_trade_and_logs_the_day():
    store, oanda = FakeStore(_record([_d("EUR_USD", "long"), _d("USD_JPY", "short")])), FakeOanda()
    report = _run(store, oanda)
    assert report["status"] == "executed"
    assert [o[:3] for o in oanda.orders] == [("open", "EUR_USD", 41_666), ("open", "USD_JPY", -37_500)]
    assert oanda.orders[0][3] == "1.06920" and oanda.orders[1][3] == "152.400"   # mid -/+ 2 ATR
    assert [t["instrument"] for t in store.inserted] == ["EUR_USD", "USD_JPY"]
    assert store.logged[0][0] == DAY and store.logged[0][1]["nav"] == 100_000.0


def test_runs_once_per_day_and_waits_for_a_tradeable_market_and_quiet_rollover():
    store = FakeStore(_record([_d("EUR_USD", "long")]), executed=True)
    assert _run(store, FakeOanda())["status"] == f"already executed {DAY}"
    store = FakeStore(_record([_d("EUR_USD", "long")]))
    assert "not tradeable" in _run(store, FakeOanda(tradeable=False))["status"] and store.logged == []
    rollover = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)              # 17:10 New York
    assert "rollover" in _run(store, FakeOanda(), now=rollover)["status"] and store.logged == []


def test_no_ai_decision_or_stale_decision_means_no_orders():
    store, oanda = FakeStore(_record([], status="no_trade")), FakeOanda()
    assert _run(store, oanda)["status"] == f"no AI decision for {DAY}" and oanda.orders == []
    store = FakeStore(_record([_d("EUR_USD", "long")]))
    late = datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc)
    assert "stale" in _run(store, oanda, now=late)["status"] and oanda.orders == []


def test_flat_call_closes_and_stopped_out_rows_are_closed_in_the_ledger():
    held = {"7": {"trade_id": "7", "instrument": "EUR_USD", "signed_units": 5000.0, "entry_price": 1.07,
                  "market_value": 5400.0, "stop_order_id": "s7"}}
    store = FakeStore(_record([_d("EUR_USD", "flat")]), open_ids={"7", "3"})   # "3": its stop filled
    oanda = FakeOanda(trades=held)
    report = _run(store, oanda)
    assert report["closed_at_broker"] == ["3"] and ("close", "7") in oanda.orders
    assert set(store.closed) == {"3", "7"} and store.inserted == []


def test_a_fill_without_a_stop_is_closed_at_once_and_reported_critical():
    store, oanda = FakeStore(_record([_d("EUR_USD", "long")])), FakeOanda(attach_stops=False)
    report = _run(store, oanda)
    assert ("close", "101") in oanda.orders and oanda.trades == {}
    assert report["status"] == "executed with errors" and "CRITICAL" in report["errors"][0]
    assert store.inserted == []


def test_rejected_order_is_reported_not_retried():
    store, oanda = FakeStore(_record([_d("EUR_USD", "long")])), FakeOanda(fill=False)
    report = _run(store, oanda)
    assert len(oanda.orders) == 1 and "MARKET_HALTED" in report["errors"][0]
    assert store.logged and store.inserted == []


def test_never_raises():
    class Broken(FakeStore):
        def latest_decision(self): raise RuntimeError("db down")
    assert _run(Broken(None), FakeOanda())["status"].startswith("failed: RuntimeError")


# ── SQL store, local throwaway Postgres only ──────────────────────────────────

def _loopback_dsn():
    dsn = os.environ.get("DATABASE_URL", "")
    host = urllib.parse.urlparse(dsn).hostname
    try:
        return dsn if host and ipaddress.ip_address(socket.gethostbyname(host)).is_loopback else None
    except (OSError, ValueError):
        return None


@pytest.mark.skipif(_loopback_dsn() is None, reason="needs a throwaway Postgres on this machine")
def test_pg_store_round_trip():
    import json
    from contextlib import contextmanager

    import psycopg2

    dsn = _loopback_dsn()

    @contextmanager
    def get_conn():
        conn = psycopg2.connect(dsn)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    import re

    from forex_ledger import FOREX_LEDGER_DDL, record_sha256

    # The real table definition, read as text (importing db.postgres opens its pool).
    schema = (Path(__file__).resolve().parents[1] / "trading-platform" / "db" / "postgres.py").read_text()
    trades_ddl = re.search(r"CREATE TABLE IF NOT EXISTS forex_ai_trades \(.*?\);", schema, re.S).group(0)
    record = {"decisions": [_d("EUR_USD", "long")]}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS forex_execution_log, forex_ai_trades, forex_decision_ledger")
        cur.execute(trades_ddl)
        cur.execute(FOREX_LEDGER_DDL)
        cur.execute("""INSERT INTO forex_decision_ledger (trading_day, status, low_confidence, record, record_sha256)
                       VALUES (%s, 'shadow', false, %s::jsonb, %s)""", (DAY, json.dumps(record), record_sha256(record)))
    store = fx.PgForexStore(get_conn)
    latest = store.latest_decision()
    assert latest["trading_day"] == DAY and latest["record"]["decisions"][0]["pair"] == "EUR_USD"
    store.insert_open({"trade_id": "101", "instrument": "EUR_USD", "signed_units": 41666,
                       "entry_price": 1.0812, "stop_order_id": "s101"}, NOW)
    assert store.open_trade_ids() == {"101"}
    store.mark_closed(["101"], NOW)
    assert store.open_trade_ids() == set()
    assert not store.already_executed(DAY) and store.last_nav() is None
    store.log_execution(DAY, {"status": "executed", "nav": 100000.0})
    store.log_execution(DAY, {"status": "duplicate ignored"})
    assert store.already_executed(DAY) and store.last_nav() == 100000.0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE forex_execution_log, forex_ai_trades, forex_decision_ledger")


def test_sync_marks_only_trades_oanda_reports_closed_with_oandas_close_time():
    import forex_execution as fe

    class Reader:
        def open_trades(self): return [{"id": "21"}]
        def trade(self, trade_id):
            return {"45": {"state": "CLOSED", "closeTime": "2026-11-06T13:30:11.345570370Z",
                           "realizedPL": "-511.8981", "averageClosePrice": "1.40990"},
                    "8": {"state": "OPEN"}}[trade_id]

    class Store:
        def __init__(self): self.ids, self.closed = {"21", "45", "8"}, []
        def open_trade_ids(self): return set(self.ids)
        def mark_closed(self, ids, when): self.closed.append((ids, when)); self.ids -= set(ids)

    store = Store()
    out = fe.sync_closed_trades(Reader(), store, NOW)
    assert [c["trade_id"] for c in out] == ["45"] and out[0]["realized_pl"] == "-511.8981"
    assert store.closed[0][1].isoformat() == "2026-11-06T13:30:11.345570+00:00"
    assert store.ids == {"21", "8"}  # still open at OANDA / not reported closed: untouched
    assert fe._oanda_time("bad") is None


def test_unclear_order_answer_is_critical_and_never_resent():
    store, oanda = FakeStore(_record([_d("EUR_USD", "long")])), FakeOanda(unclear=True)
    report = _run(store, oanda)
    assert len(oanda.orders) == 1 and store.inserted == []
    assert report["status"] == "executed with errors"
    assert report["errors"][0].startswith("CRITICAL EUR_USD: order answer unclear, may have filled")


class _Ledger:
    def __init__(self, ids=()): self.ids, self.inserted = set(ids), []
    def open_trade_ids(self): return set(self.ids)
    def insert_open(self, trade, when): self.inserted.append((trade, when)); self.ids.add(trade["trade_id"])


def _raw(trade_id, pair="EUR_USD", client_id=None, stop=True):
    raw = {"id": trade_id, "instrument": pair, "currentUnits": "41666", "price": "1.08120",
           "openTime": "2026-11-16T14:00:01.000000000Z"}
    if client_id:
        raw["clientExtensions"] = {"id": client_id}
    if stop:
        raw["stopLossOrder"] = {"id": f"s{trade_id}", "state": "PENDING"}
    return raw


def test_own_unrecorded_trade_is_adopted_with_its_stop_others_are_left_alone(monkeypatch):
    import forex_execution as fe
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "published")
    ledger = _Ledger(ids={"7"})
    out = fe.adopt_own_trades([
        _raw("7", client_id="pub-fx-eur_usd-aaaaaaaaaaaaaaaa-t"),                   # already recorded
        _raw("9", client_id="pub-fx-eur_usd-bbbbbbbbbbbbbbbb-t"),                   # ours, unrecorded
        _raw("10", pair="USD_JPY", client_id="pub-fx-usd_jpy-cccccccccccccccc-t", stop=False),
        _raw("11"),                                                                # opened by hand
        _raw("12", client_id="pub-fx-usd_jpy-dddddddddddddddd-t"),                 # id of another pair
    ], ledger, NOW)
    assert out == {"adopted": ["9"], "no_stop": ["10"]}
    (trade, when), = ledger.inserted
    assert trade == {"trade_id": "9", "instrument": "EUR_USD", "signed_units": 41666.0,
                     "entry_price": 1.0812, "stop_order_id": "s9"}
    assert when.isoformat() == "2026-11-16T14:00:01+00:00"
