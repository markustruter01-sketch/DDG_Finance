"""TREND-V1-B executor against a fake broker+ledger (no network, no DB)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from research_harness.explore.trend_v1 import UNIVERSE
from sleeve_runtime import trend_executor as te

BOT = "oracle"
# Tue 3 Nov 2026, 10:00 New York: the month's first close (Mon 2 Nov) is final.
NOV3_OPEN = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
UP = {"SPY", "GLD", "TLT"}


def _bars(end: date, extra=("EPOL", "EWZ")):
    out = {}
    for s in (*UNIVERSE, *extra):
        series, d, px = [], end - timedelta(days=440), 100.0
        while d <= end:
            if d.weekday() < 5:
                px *= 1.001 if s in UP else 0.999
                px *= 1.004 if len(series) % 2 else 0.996
                series.append({"day": d, "close": round(px, 4)})
            d += timedelta(days=1)
        out[s] = series
    return out


BARS = _bars(date(2026, 11, 3))          # includes the forming 3 Nov bar; executor must drop it
LAST = {s: [b for b in v if b["day"] <= date(2026, 11, 2)][-1]["close"] for s, v in BARS.items()}


class FakeEngine:
    def __init__(self, positions, cash, rows, *, market_open=True):
        self.pos = dict(positions)                 # symbol -> qty
        self.cash = cash
        self.px = dict(LAST, BIL=91.0, VOO=630.0, SGOV=100.0)
        self.rows = {r["symbol"]: [dict(r)] for r in rows}
        self.stops: dict[str, tuple[int, float]] = {}
        self.market_open = market_open
        self.orders: list[tuple] = []
        self.fail_close: set[str] = set()
        self.fill_ratio: dict[str, float] = {}
        self.no_stop: set[str] = set()
        self._oid = 0

    # broker reads
    def get_account(self):
        lmv = sum(q * self.px[s] for s, q in self.pos.items())
        return {"equity": self.cash + lmv, "cash": self.cash, "buying_power": self.cash,
                "long_market_value": lmv}

    def get_positions(self):
        return [{"symbol": s, "qty": q, "entry_price": self.px[s], "current_price": self.px[s],
                 "unrealised_pnl_usd": 0.0, "market_value": q * self.px[s]}
                for s, q in self.pos.items() if q > 1e-9]

    def is_market_open(self):
        return self.market_open

    # ledger
    def get_db_positions(self, bot_id):
        return [r for rs in self.rows.values() for r in rs]

    def record_close(self, bot_id, symbol, reason, pnl):
        self.orders.append(("record_close", symbol, reason))
        self.rows.pop(symbol, None)

    def record_open(self, bot_id, symbol, direction, qty, entry, atr, notional, stop, tp1, tp2, hold):
        self.rows[symbol] = [{"symbol": symbol, "qty": qty, "stop_price": stop, "stop_order_id": None}]
        return True

    def record_resize(self, bot_id, symbol, added, broker_qty, avg):
        rs = self.rows.get(symbol) or []
        if len(rs) != 1:
            return False
        rs[0]["qty"] = broker_qty
        return True

    # orders
    def _has_pending_owned_exit(self, bot_id, symbol):
        return False

    def close_position(self, symbol, *, bot_id=None, stop_order_id=None, stop_price=None):
        if symbol in self.fail_close:
            return False
        self.orders.append(("sell_all", symbol, self.pos[symbol]))
        self.cash += self.pos.pop(symbol) * self.px[symbol]
        self.stops.pop(symbol, None)
        return True

    def close_partial(self, symbol, qty, *, bot_id=None, stop_order_id=None, stop_price=None):
        self.orders.append(("sell", symbol, qty))
        self.pos[symbol] -= qty
        self.cash += qty * self.px[symbol]
        self.ensure_protective_stop(bot_id, symbol, stop_price)
        return True

    def buy_market(self, symbol, shares):
        self._oid += 1
        filled = int(shares * self.fill_ratio.get(symbol, 1.0))
        cost = filled * self.px[symbol]
        assert cost <= self.cash + 1e-6, f"would overspend on {symbol}"
        self.orders.append(("buy", symbol, filled))
        self.pos[symbol] = self.pos.get(symbol, 0) + filled
        self.cash -= cost
        self._last = (str(self._oid), "filled" if filled == shares else "partially_filled", filled, self.px[symbol])
        return {"order_id": str(self._oid), "symbol": symbol, "qty": shares}

    def poll_entry_order(self, order_id, *, max_polls=20, interval_seconds=3.0):
        oid, status, filled, px = self._last
        return {"order_id": oid, "status": status, "filled_qty": filled, "filled_avg_price": px}

    def cancel_order(self, order_id):
        self._last = (self._last[0], "canceled", self._last[2], self._last[3])
        return True

    def ensure_protective_stop(self, bot_id, symbol, stop_price, stop_order_id=None):
        if symbol in self.no_stop:
            return None
        whole = int(self.pos.get(symbol, 0))
        if whole >= 1:
            self.stops[symbol] = (whole, round(stop_price, 2))
            for r in self.rows.get(symbol, []):
                r["stop_price"] = round(stop_price, 2)
        return "stop"

    def _find_owned_stop(self, bot_id, symbol, stop_order_id):
        return self.stops.get(symbol)


def _legacy_engine(**kw):
    positions = {"EPOL": 263, "EWZ": 106.88, "SPY": 15, "BIL": 31.9, "VOO": 4.14, "SGOV": 200}
    rows = [{"symbol": s, "qty": q, "stop_price": 1.0, "stop_order_id": f"s-{s}"}
            for s, q in (("EPOL", 263), ("EWZ", 106.88), ("SPY", 15))]
    eng = FakeEngine(positions, 40_000.0, rows, **kw)
    eng.stops = {"EPOL": (263, 41.46), "EWZ": (106, 40.82), "SPY": (15, 710.76)}   # legacy stops
    return eng


def _run(engine, state=None, now=NOV3_OPEN, tripped=False):
    box = {"state": dict(state or {}), "alerts": [], "parked": 0, "unparked": 0}

    def unpark(e, live):
        box["unparked"] += 1
        if "SGOV" in e.pos:
            e.close_position("SGOV")

    out = te.run_trend_cycle(
        engine, bot_id=BOT, fetch_bars=lambda symbols, start: {s: BARS[s] for s in symbols if s in BARS},
        vault={"BIL", "VOO"}, cash_park={"SGOV"},
        read_state=lambda: box["state"], write_state=lambda st: box["state"].update(st) or None,
        kill_tripped=lambda: tripped, unpark=unpark,
        park=lambda e, live, cash: box.__setitem__("parked", box["parked"] + 1),
        alert=lambda sev, msg: box["alerts"].append((sev, msg)), now=now)
    return out, box


def test_cutover_sells_legacy_buys_trend_and_protects_everything():
    eng = _legacy_engine()
    out, box = _run(eng)
    assert out["status"] == "rebalanced", box
    assert ("sell_all", "EPOL", 263) in eng.orders and ("sell_all", "EWZ", 106.88) in eng.orders
    assert {"EPOL", "EWZ"}.isdisjoint(eng.pos)                       # fraction sold too
    assert {s for s in eng.pos if s not in {"BIL", "VOO"}} == UP      # vault untouched
    assert eng.pos["BIL"] == 31.9 and eng.pos["VOO"] == 4.14
    for s in UP:                                                      # 20% below the 2 Nov close
        assert eng.stops[s] == (int(eng.pos[s]), round(LAST[s] * 0.8, 2))
        assert len(eng.rows[s]) == 1
    assert eng.cash >= 0 and box["unparked"] == 1 and box["parked"] == 1
    assert box["state"]["done"] is True and box["state"]["attempts"] == 1
    assert box["state"]["signal_day"] == "2026-11-02" and box["alerts"] == []


def test_second_run_after_done_places_no_orders():
    eng = _legacy_engine()
    _, box = _run(eng)
    n = len(eng.orders)
    out, _ = _run(eng, state=box["state"], now=NOV3_OPEN + timedelta(hours=1))
    assert out["status"] == "no rebalance due" and len(eng.orders) == n


@pytest.mark.parametrize("kw,now,tripped,status", [
    ({"market_open": False}, NOV3_OPEN, False, "market closed"),
    ({}, NOV3_OPEN, True, "kill switch tripped: no trading"),
    ({}, datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc), False, "no rebalance due"),   # mid-month
    ({}, datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc), False, "no rebalance due"),    # first close not final
])
def test_no_orders_when_not_allowed_or_not_due(kw, now, tripped, status):
    eng = _legacy_engine(**kw)
    out, _ = _run(eng, now=now, tripped=tripped)
    assert out["status"] == status
    assert [o for o in eng.orders if o[0] != "record_close"] == []


def test_failed_sell_is_reported_retried_and_capped():
    eng = _legacy_engine()
    eng.fail_close = {"EPOL"}
    out, box = _run(eng)
    assert out["status"] == "rebalance attempt 1 incomplete"
    assert box["state"]["done"] is False and any("EPOL" in e for e in box["state"]["errors"])
    assert eng.pos["EPOL"] == 263 and eng.cash >= 0                  # buys fitted the cash really there
    assert box["alerts"] and box["alerts"][0][0] == "error"
    state = box["state"]
    for i in (2, 3):
        out, b = _run(eng, state=state, now=NOV3_OPEN + timedelta(hours=i))
        state = b["state"]
    assert state["attempts"] == 3
    n = len(eng.orders)
    out, _ = _run(eng, state=state, now=NOV3_OPEN + timedelta(hours=4))
    assert out["status"] == "no rebalance due" and len(eng.orders) == n


def test_partial_buy_fill_is_recorded_protected_and_reported():
    eng = _legacy_engine()
    eng.fill_ratio = {"GLD": 0.5}
    out, box = _run(eng)
    assert any("partial fill" in e for e in box["state"]["errors"])
    assert eng.stops["GLD"][0] == int(eng.pos["GLD"]) and eng.rows["GLD"][0]["qty"] == eng.pos["GLD"]


def test_missing_stop_raises_a_critical_alert():
    eng = _legacy_engine()
    eng.no_stop = {"TLT"}
    out, box = _run(eng)
    assert box["alerts"][0][0] == "critical" and "TLT" in box["alerts"][0][1]
    assert box["state"]["done"] is False


def test_symbol_with_two_ledger_rows_is_frozen():
    eng = _legacy_engine()
    eng.rows["EPOL"].append(dict(eng.rows["EPOL"][0]))
    _run(eng)
    assert eng.pos["EPOL"] == 263 and not any(o[1] == "EPOL" for o in eng.orders if o[0] != "record_close")


def test_flat_rows_closed_but_not_on_an_empty_broker_reply():
    eng = _legacy_engine(market_open=False)
    del eng.pos["EPOL"]                                               # its stop filled
    _run(eng)
    assert ("record_close", "EPOL", te.FLAT_EXIT_REASON) in eng.orders
    empty = FakeEngine({}, 1000.0, [{"symbol": "SPY", "qty": 1, "stop_price": 1, "stop_order_id": None}],
                       market_open=False)
    _run(empty)
    assert empty.orders == []


def test_signal_day_window():
    s = {}
    d = [date(2026, 10, 30), date(2026, 11, 2)]
    assert te.signal_day_if_due(d, date(2026, 11, 3), s) == date(2026, 11, 2)
    four = d + [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)]
    assert te.signal_day_if_due(four, date(2026, 11, 6), s) is None
    assert te.signal_day_if_due(d, date(2026, 11, 3), {"month": "2026-11", "done": True}) is None
    assert te.signal_day_if_due(d, date(2026, 11, 3), {"month": "2026-10", "done": True}) == date(2026, 11, 2)
    assert te.signal_day_if_due(d, date(2026, 11, 9), s) is None              # feed stale for a week
    attempts = {"month": "2026-11", "attempts": 3}
    assert te.signal_day_if_due(d, date(2026, 11, 3), attempts) is None


def test_crash_mid_rebalance_is_recorded_alerted_and_not_looped():
    eng = _legacy_engine()

    def boom(*a, **k):
        raise ConnectionError("broker down")

    eng.buy_market = boom
    out, box = _run(eng)
    assert out["status"] == "rebalance attempt 1 crashed"
    assert box["state"]["attempts"] == 1 and box["state"]["done"] is False
    assert box["alerts"][0][0] == "critical"
    assert all(s in eng.stops for s in eng.pos if s in UP)        # anything bought stayed protected


def test_gap_up_never_overspends_and_parked_cash_only_counts_once_sold():
    eng = _legacy_engine()
    for s in UP:
        eng.px[s] = LAST[s] * 1.15            # opened 15% above the last close
    eng.cash = 0.0                            # all spare cash is parked in SGOV ...
    out, box = _run(eng)                      # ... and the fake's buy asserts on overspend
    assert eng.cash >= 0


def test_buy_is_cut_to_the_cash_in_the_account():
    eng = FakeEngine({}, 1_000.0, [])
    eng.px["SPY"] = 110.0                       # opened above the 100 close
    err = te._buy(eng, BOT, "SPY", 50, 80.0, 100.0, None)
    assert eng.pos["SPY"] == 9 and eng.cash >= 0  # 1000 // (100 * 1.02) = 9
    assert "cut 50->9 to fit cash" in err and eng.stops["SPY"] == (9, 80.0)
    assert te._buy(FakeEngine({}, 50.0, []), BOT, "SPY", 5, 80.0, 100.0, None) == "SPY: no cash for even one share"


def test_unpark_failure_means_no_buys_beyond_real_cash():
    eng = _legacy_engine()
    eng.cash = 0.0
    eng.fail_close = {"SGOV"}                 # parked cash could not be sold
    box_unpark = []

    def run():
        return te.run_trend_cycle(
            eng, bot_id=BOT, fetch_bars=lambda symbols, start: {s: BARS[s] for s in symbols if s in BARS},
            vault={"BIL", "VOO"}, cash_park={"SGOV"}, read_state=lambda: {},
            write_state=lambda st: None, kill_tripped=lambda: False,
            unpark=lambda e, live: box_unpark.append(e.close_position("SGOV")),
            park=lambda *a: None, alert=lambda *a: None, now=NOV3_OPEN)

    run()
    assert box_unpark == [False] and eng.cash >= 0 and eng.pos["SGOV"] == 200
