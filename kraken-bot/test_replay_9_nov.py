"""Replay of the 9 Nov 2026 Atlas rebalance (the stop-loss incident).

Start state and orders are from production (read 10 Nov 2026):
- Atlas (oracle) held SPY 42 (stop 604.58), QQQ 31 (stop 552.39), GLD 8,
  UUP 398, DBC 98 (stop-free sleeve), SGOV 118.374190978 (cash park), BIL/VOO (vault).
- 15:13 UTC it sold GLD 8, QQQ 7, SPY 10, UUP 5 and bought DBC 25.
- The new stops would sit 20% under the day's prices (Atlas V2 placed
  SPY 588.23 / QQQ 524.88 at the same moment), so SPY/QQQ needed a NEW stop
  level, which takes the engine's replace path.
- Alpaca's open-orders list kept showing the cancelled stops for ~45 s+.

Live result that day: SPY 32 and QQQ 24 left with no stop for 6+ hours, and
the SGOV unpark failed on a rounded quantity. The fixed code must end with
both protected and SGOV sold; the old behaviour must reproduce the incident
(so this replay really models what happened).
"""
from __future__ import annotations

from datetime import date

import pytest

from broker_harness import (FakeAlpaca, critical_alarms, fixed_plan, ledger, make_engine,
                            needs_db, protection_report, seed_holding)
from sleeve_runtime.trend_executor import execute_rebalance

PRICES = {"SPY": 735.29, "QQQ": 656.10, "GLD": 370.00, "UUP": 28.97, "DBC": 30.98,
          "SGOV": 100.50, "BIL": 91.50, "VOO": 600.00}
TARGETS = {"SPY": 32, "QQQ": 24, "GLD": 0, "UUP": 393, "DBC": 123}
NEW_STOPS = {"SPY": 588.23, "QQQ": 524.88}


def _atlas_before_9_nov(monkeypatch, *, cancel_lag_s=60.0):
    broker = FakeAlpaca(prices=dict(PRICES), cash=14_000.0, cancel_lag_s=cancel_lag_s)
    engine = make_engine(monkeypatch, broker)
    seed_holding(engine, broker, "oracle", "SPY", 42, stop=604.58)
    seed_holding(engine, broker, "oracle", "QQQ", 31, stop=552.39)
    for sym, qty in (("GLD", 8), ("UUP", 398), ("DBC", 98)):
        seed_holding(engine, broker, "oracle", sym, qty)
    broker.positions.update({"SGOV": 118.374190978, "BIL": 51.398162849, "VOO": 0.000000982})
    return broker, engine


def _rebalance(engine):
    return execute_rebalance(
        engine, bot_id="oracle", bars={}, signal_day=date(2026, 11, 9),
        vault={"BIL", "VOO"}, cash_park={"SGOV"},
        unpark=lambda e, live: e.close_position("SGOV"),
        risk_check=lambda: {"allowed": True, "reasons": []},
        plan_fn=fixed_plan(TARGETS, PRICES, NEW_STOPS))


@needs_db
def test_9_nov_rebalance_now_ends_with_every_holding_protected(monkeypatch):
    broker, engine = _atlas_before_9_nov(monkeypatch)
    report = _rebalance(engine)

    assert report["errors"] == [] and report["done"] is True
    assert {s: broker.positions.get(s) for s in TARGETS} == {
        "SPY": 32, "QQQ": 24, "GLD": None, "UUP": 393, "DBC": 123}
    assert protection_report(broker, "oracle") == {"QQQ": "protected", "SPY": "protected"}
    # each holding has exactly one live stop, at the new level, sized to the holding
    for sym, qty in (("SPY", 32), ("QQQ", 24)):
        (stop,) = broker.open_stops(sym)
        assert (stop.qty, stop.stop_price) == (qty, NEW_STOPS[sym])
        row = ledger("oracle")[sym]
        assert row["stop_order_id"] == stop.id and row["stop_price"] == NEW_STOPS[sym]
    assert "SGOV" not in broker.positions        # unpark sold the exact broker quantity
    assert critical_alarms("oracle") == []


@needs_db
def test_old_behaviour_reproduces_the_incident(monkeypatch):
    """Switch the fix off (trust the stale open-orders list): SPY and QQQ end
    with no stop at the broker, exactly as on 9 Nov."""
    broker, engine = _atlas_before_9_nov(monkeypatch, cancel_lag_s=3600)
    monkeypatch.setattr(type(engine), "_still_open", lambda self, order: True)
    _rebalance(engine)

    assert broker.open_stops("SPY") == [] and broker.open_stops("QQQ") == []
    alarms = " ".join(critical_alarms("oracle"))
    assert "symbol=SPY" in alarms and "symbol=QQQ" in alarms


@needs_db
@pytest.mark.parametrize("lag", [0.0, 5.0, 300.0])
def test_result_does_not_depend_on_how_long_the_list_lags(monkeypatch, lag):
    broker, engine = _atlas_before_9_nov(monkeypatch, cancel_lag_s=lag)
    report = _rebalance(engine)
    assert report["errors"] == []
    assert protection_report(broker, "oracle") == {"QQQ": "protected", "SPY": "protected"}


@needs_db
def test_paused_stop_check_repairs_the_9_nov_aftermath(monkeypatch):
    """The state Atlas was left in (holdings, ledger, no stops) is repaired by
    one reconcile pass, which paused bots now run every cycle."""
    broker, engine = _atlas_before_9_nov(monkeypatch, cancel_lag_s=3600)
    monkeypatch.setattr(type(engine), "_still_open", lambda self, order: True)
    _rebalance(engine)
    assert broker.open_stops("SPY") == []
    monkeypatch.undo()                       # back to the fixed code (and real time module)
    broker.clock.sleep(600)                  # 10 minutes later
    engine = make_engine(monkeypatch, broker, bot_ids=())
    engine.reconcile_protective_stops("oracle", engine.get_db_positions("oracle"))
    assert protection_report(broker, "oracle") == {"QQQ": "protected", "SPY": "protected"}
