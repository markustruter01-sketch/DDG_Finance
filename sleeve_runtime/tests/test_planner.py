"""Tests for the live sleeve rebalance planner."""

from __future__ import annotations

import pytest

from sleeve_runtime.planner import plan_rebalance


def _plan(**kw):
    base = dict(weights={}, equity=100_000, cash=100_000, positions={}, prices={},
                stop_pct=0.20, cash_buffer_pct=0.01)
    base.update(kw)
    return plan_rebalance(**base)


def test_fresh_buy_whole_shares_with_stop_after_fill():
    p = _plan(weights={"SPY": 0.5}, prices={"SPY": 333.0})
    assert [(o.symbol, o.qty) for o in p.buys] == [("SPY", 150)]      # 50000/333 = 150.15
    assert p.cancel_stops == [] and p.sells == []
    [stop] = p.stops
    assert (stop.action, stop.qty, stop.stop) == ("place", 150, 266.4)


def test_close_position_cancels_stop_first_and_leaves_no_stop():
    p = _plan(weights={}, cash=0, positions={"TLT": 100}, prices={"TLT": 90.0})
    assert p.cancel_stops == ["TLT"]
    assert [(o.symbol, o.side, o.qty) for o in p.sells] == [("TLT", "sell", 100)]
    assert p.stops == [] and p.final_qty == {}


def test_unchanged_position_moves_its_stop_without_cancelling():
    p = _plan(weights={"GLD": 0.2}, equity=100_000, cash=80_000,
              positions={"GLD": 100}, prices={"GLD": 200.0})
    assert p.cancel_stops == [] and p.buys == [] and p.sells == []
    assert [(s.symbol, s.action, s.qty, s.stop) for s in p.stops] == [("GLD", "replace", 100, 160.0)]


def test_growing_position_resizes_its_stop():
    p = _plan(weights={"IEF": 0.3}, cash=90_000, positions={"IEF": 100}, prices={"IEF": 100.0})
    assert p.cancel_stops == ["IEF"]
    assert [(o.symbol, o.qty) for o in p.buys] == [("IEF", 200)]
    assert [(s.action, s.qty) for s in p.stops] == [("place", 300)]


def test_buys_scaled_down_to_available_cash_with_buffer():
    p = _plan(weights={"A": 0.5, "B": 0.5}, cash=50_000, prices={"A": 10.0, "B": 10.0})
    spend = sum(o.qty * 10.0 for o in p.buys)
    assert spend <= 50_000 - 0.01 * 100_000 and p.buy_scale < 1


def test_sell_proceeds_fund_buys_in_the_same_rebalance():
    p = _plan(weights={"B": 0.5}, cash=0, positions={"A": 5000}, prices={"A": 10.0, "B": 10.0})
    assert [(o.symbol, o.qty) for o in p.sells] == [("A", 5000)]
    assert [(o.symbol, o.qty) for o in p.buys] == [("B", 4900)]       # 50000 - 1000 buffer


def test_missing_price_leaves_position_and_stop_untouched():
    p = _plan(weights={"EEM": 0.0}, positions={"EEM": 50}, prices={"EEM": None})
    assert "EEM" in p.skipped and p.sells == [] and p.cancel_stops == []
    assert all(s.symbol != "EEM" for s in p.stops) and p.final_qty == {"EEM": 50}


@pytest.mark.parametrize("bad", [
    dict(weights={"A": -0.1}, prices={"A": 1.0}),
    dict(weights={"A": 0.7, "B": 0.6}, prices={"A": 1.0, "B": 1.0}),
    dict(positions={"A": 1.5}, prices={"A": 1.0}),
    dict(equity=0),
])
def test_rejects_unsafe_inputs(bad):
    with pytest.raises(ValueError):
        _plan(**bad)
