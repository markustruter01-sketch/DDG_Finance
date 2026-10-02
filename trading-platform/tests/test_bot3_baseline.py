from __future__ import annotations

import contextlib
import datetime as dt
from types import SimpleNamespace

import pytest

from analysis import backtest_harness
from analysis import bot3_baseline as baseline


def test_quarterly_schedule_uses_first_common_session_on_or_before_day_seven():
    sessions = [
        dt.date(2020, 1, 2),
        dt.date(2020, 1, 3),
        dt.date(2020, 1, 8),
        dt.date(2020, 4, 1),
        dt.date(2020, 7, 3),
        dt.date(2020, 10, 5),
        dt.date(2020, 10, 8),
    ]

    assert baseline.quarterly_rebalance_sessions(sessions) == {
        dt.date(2020, 1, 2),
        dt.date(2020, 4, 1),
        dt.date(2020, 7, 3),
        dt.date(2020, 10, 5),
    }


def test_inverse_volatility_weights_obey_bounds_and_sum_to_one():
    weights = baseline.bounded_inverse_vol_weights(
        {"BTC-USD": 0.01, "ETH-USD": 0.05, "GLD": 0.2, "SLV": 10.0}
    )

    assert set(weights) == set(baseline.ASSETS)
    assert all(0.10 - 1e-12 <= weight <= 0.40 + 1e-12 for weight in weights.values())
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["BTC-USD"] == pytest.approx(0.40)
    assert weights["SLV"] == pytest.approx(0.10)
    assert weights["ETH-USD"] == pytest.approx(0.40)


def test_crypto_cap_uses_dynamic_three_times_bot3_equity_proxy():
    targets = {
        "BTC-USD": 0.30,
        "ETH-USD": 0.20,
        "GLD": 0.30,
        "SLV": 0.20,
    }

    at_100k = baseline.apply_dynamic_crypto_cap(targets, 100_000.0)
    at_200k = baseline.apply_dynamic_crypto_cap(targets, 200_000.0)

    assert at_100k["BTC-USD"] + at_100k["ETH-USD"] == pytest.approx(0.15)
    assert at_100k["GLD"] == pytest.approx(0.51)
    assert at_100k["SLV"] == pytest.approx(0.34)
    assert (at_200k["BTC-USD"] + at_200k["ETH-USD"]) * 200_000.0 == pytest.approx(
        30_000.0
    )
    assert (at_100k["BTC-USD"] + at_100k["ETH-USD"]) * 100_000.0 == pytest.approx(
        15_000.0
    )
    assert sum(at_100k.values()) == pytest.approx(1.0)


def test_drift_band_holds_at_five_points_but_cap_exceedance_forces_trim():
    target = {
        "BTC-USD": 0.075,
        "ETH-USD": 0.075,
        "GLD": 0.42,
        "SLV": 0.42,
    }
    within_band = dict(target, **{"BTC-USD": 0.125, "ETH-USD": 0.025})

    assert not baseline.should_rebalance(within_band, target, 100_000.0)
    outside_band = dict(target, **{"BTC-USD": 0.126, "ETH-USD": 0.024})
    assert baseline.should_rebalance(outside_band, target, 100_000.0)

    crypto_over_cap = dict(target, **{"BTC-USD": 0.11, "ETH-USD": 0.05})
    assert baseline.should_rebalance(crypto_over_cap, target, 100_000.0)


def test_fixed_entry_relative_stops_use_close_breaches_for_crypto_and_metals():
    entries = {
        "BTC-USD": 100.0,
        "ETH-USD": 200.0,
        "GLD": 50.0,
        "SLV": 25.0,
    }

    assert baseline.fixed_stop_breaches(
        entries,
        {
            "BTC-USD": 75.0,
            "ETH-USD": 151.0,
            "GLD": 45.0,
            "SLV": 22.49,
        },
    ) == {"BTC-USD", "GLD", "SLV"}


class _PlaceholderCheckingCursor:
    def __init__(self):
        self.row = (17,)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        placeholder_count = query.count("%s")
        if placeholder_count != len(params):
            raise RuntimeError(
                f"placeholder/parameter mismatch: {placeholder_count} != {len(params)}"
            )

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self):
        self.fake_cursor = _PlaceholderCheckingCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.fake_cursor


def test_exploration_insert_placeholder_count_and_mismatch_failure(monkeypatch):
    fake_connection = _FakeConnection()

    @contextlib.contextmanager
    def fake_research_connection():
        yield fake_connection

    monkeypatch.setattr(
        backtest_harness,
        "get_research_conn",
        fake_research_connection,
    )
    result = backtest_harness.BacktestResult(
        equity_curve=(),
        events=(),
        metrics={"sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0},
        parameters={"cost_bps": 5},
        data_window={"requested_start": "2008-01-01"},
    )

    assert backtest_harness.append_exploration_run(
        result,
        strategy_family=baseline.STRATEGY_FAMILY,
    ) == 17
    with pytest.raises(RuntimeError, match="placeholder/parameter mismatch"):
        fake_connection.fake_cursor.execute("SELECT %s, %s", (1,))