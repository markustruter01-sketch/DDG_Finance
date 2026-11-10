"""Broker quirks: the real engine and executor against a misbehaving broker.

Rule under test (Step 2 item 10, finance-2027-plan.md): whatever the broker
does, every holding that needs a stop ends up PROTECTED (a live stop covering
its whole shares) or ALARMED (a critical alarm naming it), never silently
naked; and the next stop check repairs anything left alarmed.
"""
from __future__ import annotations

from datetime import date

from broker_harness import (FakeAlpaca, critical_alarms, fixed_plan, ledger, make_engine,
                            needs_db, protection_report, seed_holding)
from sleeve_runtime.trend_executor import close_flat_rows, execute_rebalance

PRICES = {"SPY": 700.0, "QQQ": 600.0, "SGOV": 100.0, "BIL": 91.5}


def _setup(monkeypatch, **broker_kw):
    broker = FakeAlpaca(prices=dict(PRICES), cash=50_000.0, **broker_kw)
    engine = make_engine(monkeypatch, broker, bot_ids=("jerome_macro",))
    seed_holding(engine, broker, "jerome_macro", "SPY", 40, stop=560.0)
    broker.positions["BIL"] = 50.0                   # live accounts always hold T-bill funds
    return broker, engine


def _rebalance(engine, targets, stops):
    return execute_rebalance(
        engine, bot_id="jerome_macro", bars={}, signal_day=date(2026, 11, 9),
        vault=set(), cash_park={"SGOV"}, unpark=lambda e, live: None,
        risk_check=lambda: {"allowed": True, "reasons": []},
        plan_fn=fixed_plan(targets, PRICES, stops))


def _repair(engine):
    engine.reconcile_protective_stops("jerome_macro", engine.get_db_positions("jerome_macro"))


@needs_db
def test_rate_limited_stop_submit_is_alarmed_then_repaired(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.fail_next("submit_order", n=2)            # 429 on the sell AND the stop re-check
    report = _rebalance(engine, {"SPY": 30}, {"SPY": 560.0})
    assert report["done"] is False                   # reported, not hidden
    assert protection_report(broker, "jerome_macro", report["unprotected"]) == {"SPY": "alarmed"}
    _repair(engine)
    assert protection_report(broker, "jerome_macro") == {"SPY": "protected"}


@needs_db
def test_rejected_stop_is_alarmed_never_silently_naked(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.reject_next("stop", n=2)                  # after the partial sell and in step 3
    report = _rebalance(engine, {"SPY": 30}, {"SPY": 560.0})
    assert broker.positions["SPY"] == 30
    assert protection_report(broker, "jerome_macro", report["unprotected"]) == {"SPY": "alarmed"}
    assert any("symbol=SPY" in a for a in critical_alarms("jerome_macro"))
    _repair(engine)
    assert protection_report(broker, "jerome_macro") == {"SPY": "protected"}


@needs_db
def test_top_up_lifts_the_stop_first_and_protects_the_whole_position(monkeypatch):
    """Alpaca rejects a buy while a sell stop is open (wash-trade rule)."""
    broker, engine = _setup(monkeypatch)
    report = _rebalance(engine, {"SPY": 50}, {"SPY": 560.0})
    assert report["errors"] == []
    assert broker.positions["SPY"] == 50
    (stop,) = broker.open_stops("SPY")
    assert stop.qty == 50
    assert ledger("jerome_macro")["SPY"]["stop_order_id"] == stop.id


@needs_db
def test_partial_fill_on_a_top_up_still_protects_every_share(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.partial_fill_next(0.5)                    # 10 asked, 5 filled, rest cancelled
    report = _rebalance(engine, {"SPY": 50}, {"SPY": 560.0})
    assert broker.positions["SPY"] == 45
    assert any("partial fill" in e for e in report["errors"])
    (stop,) = broker.open_stops("SPY")
    assert stop.qty == 45


@needs_db
def test_new_position_partial_fill_is_recorded_and_protected(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.partial_fill_next(0.4)
    _rebalance(engine, {"SPY": 40, "QQQ": 10}, {"SPY": 560.0, "QQQ": 480.0})
    assert broker.positions["QQQ"] == 4
    assert ledger("jerome_macro")["QQQ"]["qty"] == 4
    assert protection_report(broker, "jerome_macro") == {"QQQ": "protected", "SPY": "protected"}


@needs_db
def test_empty_positions_reply_never_closes_ledger_rows(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.empty_positions_next(1)
    live = engine.get_positions()
    assert live == []
    assert close_flat_rows(engine, "jerome_macro", live, engine.get_db_positions("jerome_macro")) == []
    assert "SPY" in ledger("jerome_macro")
    assert protection_report(broker, "jerome_macro") == {"SPY": "protected"}


@needs_db
def test_gap_through_the_stop_closes_the_row_and_places_no_new_stop(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.gap_to("SPY", 500.0)                      # opens below the 560 stop: fills at 500
    assert "SPY" not in broker.positions
    closed = close_flat_rows(engine, "jerome_macro", engine.get_positions(),
                             engine.get_db_positions("jerome_macro"))
    assert closed == ["SPY"] and "SPY" not in ledger("jerome_macro")
    _repair(engine)                                  # nothing to protect, nothing placed
    assert broker.open_stops("SPY") == []
    assert critical_alarms("jerome_macro") == []


@needs_db
def test_full_close_whose_sell_is_refused_is_alarmed_then_repaired(monkeypatch):
    broker, engine = _setup(monkeypatch)
    row = ledger("jerome_macro")["SPY"]
    broker.fail_next("submit_order", n=1, error="Connection reset by peer")
    ok = engine.close_position("SPY", bot_id="jerome_macro", stop_order_id=row["stop_order_id"],
                               stop_price=row["stop_price"])
    assert ok is False and broker.positions["SPY"] == 40
    assert protection_report(broker, "jerome_macro") in ({"SPY": "protected"}, {"SPY": "alarmed"})
    _repair(engine)
    assert protection_report(broker, "jerome_macro") == {"SPY": "protected"}


@needs_db
def test_partial_sell_that_never_fills_puts_the_stop_back(monkeypatch):
    broker, engine = _setup(monkeypatch)
    broker.market_open = True
    real_submit = broker.submit_order

    def no_fill_market(**kw):                       # accepted, then sits unfilled
        if kw.get("type") == "market":
            broker.market_open = False
            try:
                return real_submit(**kw)
            finally:
                broker.market_open = True
        return real_submit(**kw)

    monkeypatch.setattr(broker, "submit_order", no_fill_market)
    ok = engine.close_partial("SPY", 10, bot_id="jerome_macro",
                              stop_order_id=ledger("jerome_macro")["SPY"]["stop_order_id"],
                              stop_price=560.0)
    assert ok is False and broker.positions["SPY"] == 40
    (stop,) = broker.open_stops("SPY")
    assert stop.qty == 40


@needs_db
def test_stale_cancelled_stop_in_the_list_never_counts_as_protection(monkeypatch):
    broker, engine = _setup(monkeypatch, cancel_lag_s=3600)
    (old,) = broker.open_stops("SPY")
    broker.cancel_order(old.id)                      # cancelled, still listed as open
    _repair(engine)
    (stop,) = broker.open_stops("SPY")
    assert stop.id != old.id and stop.qty == 40
