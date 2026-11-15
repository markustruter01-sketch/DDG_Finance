"""Lost order replies: the real engine and executor against a broker that takes
an order and then loses the reply (16 Nov 2026 order-path audit, F1).

The Alpaca library resends a request that got HTTP 504. If the first try had
been accepted, a resent order is refused as a duplicate client ID and a
resent stop replace finds the old stop already replaced. Rule under test:
every order reaches the broker exactly once, is recorded once, and every
holding ends up protected. Never a second order, never a short.
"""
from __future__ import annotations

from datetime import date

import pytest

from broker_harness import (FakeAlpaca, critical_alarms, fixed_plan, ledger, make_engine,
                            needs_db, protection_report, seed_holding)
from sleeve_runtime.trend_executor import execute_rebalance

PRICES = {"SPY": 700.0, "QQQ": 600.0, "SGOV": 100.0, "BIL": 91.5}
BOT = "jerome_macro"


def _setup(monkeypatch):
    broker = FakeAlpaca(prices=dict(PRICES), cash=50_000.0)
    engine = make_engine(monkeypatch, broker, bot_ids=(BOT,))
    seed_holding(engine, broker, BOT, "SPY", 40, stop=560.0)
    return broker, engine


def _rebalance(engine, targets, stops):
    return execute_rebalance(
        engine, bot_id=BOT, bars={}, signal_day=date(2026, 11, 16),
        vault=set(), cash_park={"SGOV"}, unpark=lambda e, live: None,
        risk_check=lambda: {"allowed": True, "reasons": []},
        plan_fn=fixed_plan(targets, PRICES, stops))


def _orders(broker, symbol, side, order_type):
    return [o for o in broker.orders.values()
            if o.symbol == symbol and o.side == side and o.type == order_type]


@needs_db
@pytest.mark.parametrize("resend", [True, False], ids=["504-resend", "read-time-out"])
def test_new_buy_whose_reply_is_lost_is_bought_once_recorded_and_protected(monkeypatch, resend):
    broker, engine = _setup(monkeypatch)
    broker.lose_reply_next(resend=resend, order_type="market")
    report = _rebalance(engine, {"SPY": 40, "QQQ": 10}, {"SPY": 560.0, "QQQ": 480.0})
    assert len(_orders(broker, "QQQ", "buy", "market")) == 1
    assert broker.positions["QQQ"] == 10
    assert ledger(BOT)["QQQ"]["qty"] == 10
    assert protection_report(broker, BOT) == {"QQQ": "protected", "SPY": "protected"}
    assert report["errors"] == []


@needs_db
@pytest.mark.parametrize("resend", [True, False], ids=["504-resend", "read-time-out"])
def test_full_close_whose_reply_is_lost_sells_once_and_never_goes_short(monkeypatch, resend):
    broker, engine = _setup(monkeypatch)
    broker.lose_reply_next(resend=resend, order_type="market")
    report = _rebalance(engine, {"SPY": 0}, {})
    assert len(_orders(broker, "SPY", "sell", "market")) == 1
    assert "SPY" not in broker.positions                # flat, not short
    assert "SPY" not in ledger(BOT)
    assert report["errors"] == []


@needs_db
def test_partial_sell_whose_reply_is_lost_sells_once_and_reprotects(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.lose_reply_next(order_type="market")
    report = _rebalance(engine, {"SPY": 30}, {"SPY": 560.0})
    assert len(_orders(broker, "SPY", "sell", "market")) == 1
    assert broker.positions["SPY"] == 30
    (stop,) = broker.open_stops("SPY")
    assert stop.qty == 30
    assert report["errors"] == []


@needs_db
def test_new_stop_whose_reply_is_lost_is_placed_once_and_recorded(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.lose_reply_next(order_type="stop")
    _rebalance(engine, {"SPY": 40, "QQQ": 10}, {"SPY": 560.0, "QQQ": 480.0})
    (stop,) = broker.open_stops("QQQ")
    assert len(_orders(broker, "QQQ", "sell", "stop")) == 1
    assert ledger(BOT)["QQQ"]["stop_order_id"] == stop.id
    assert critical_alarms(BOT) == []


@needs_db
def test_stop_replace_whose_reply_is_lost_adopts_the_live_replacement(monkeypatch):
    broker, engine = _setup(monkeypatch)
    old_id = ledger(BOT)["SPY"]["stop_order_id"]
    broker.lose_reply_next(method="replace_order")
    new_id = engine.ensure_protective_stop(BOT, "SPY", 600.0, old_id)    # ratchet 560 -> 600
    (stop,) = broker.open_stops("SPY")
    assert new_id == stop.id != old_id and stop.stop_price == 600.0
    assert ledger(BOT)["SPY"]["stop_order_id"] == stop.id
    assert critical_alarms(BOT) == []                 # no false "naked" alarm
    assert len(_orders(broker, "SPY", "sell", "stop")) == 2   # the old (replaced) and its successor
