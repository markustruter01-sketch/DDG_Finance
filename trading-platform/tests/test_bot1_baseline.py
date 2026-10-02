from __future__ import annotations

from datetime import date, timedelta
from math import cos, pi, sin

import pytest

from analysis import bot1_baseline as baseline


BASE = date(2018, 1, 2)


def _history(count: int, *, pattern: str = "flat") -> dict[str, dict[date, float]]:
    dates = [BASE + timedelta(days=index) for index in range(count)]
    series: dict[str, dict[date, float]] = {}
    for symbol_index, symbol in enumerate(baseline.UNIVERSE):
        prices = [100.0]
        for index in range(1, count):
            if pattern == "trend":
                daily_return = 0.002 + 0.001 * sin(
                    2 * pi * (index + symbol_index * 4) / (19 + symbol_index % 5)
                )
            else:
                daily_return = 0.0
            prices.append(prices[-1] * (1 + daily_return))
        series[symbol] = dict(zip(dates, prices, strict=True))
    return series


def _bars(history: dict[str, dict[date, float]]) -> dict:
    return {
        symbol: {
            day: (close * 1.01, close * 0.99, close)
            for day, close in values.items()
        }
        for symbol, values in history.items()
    }


def test_correlation_matches_live_tail_alignment_when_dates_differ() -> None:
    closes = [100.0]
    for index in range(1, 25):
        daily_return = 0.005 + 0.001 * sin(2 * pi * index / 7)
        closes.append(closes[-1] * (1 + daily_return))
    left = {
        BASE + timedelta(days=index): close
        for index, close in enumerate(closes)
    }
    right = {
        BASE + timedelta(days=100 + index): close
        for index, close in enumerate(closes)
    }

    left_returns = baseline._asof_returns(
        left,
        BASE + timedelta(days=24),
        60,
        calendar_days=90,
    )
    right_returns = baseline._asof_returns(
        right,
        BASE + timedelta(days=124),
        60,
        calendar_days=90,
    )

    assert left_returns == pytest.approx(right_returns)
    assert baseline._pearson(left_returns, right_returns) == pytest.approx(1.0)


def test_entry_ema_uses_full_history_while_f18_exit_uses_last_50_closes() -> None:
    values = [200.0] * 200 + [100.0 + index * 0.1 for index in range(50)]
    entry_ema = baseline.ema_last(values, baseline.FAST_EMA)
    f18_exit_ema = baseline.ema_last(values[-50:], baseline.FAST_EMA)

    assert entry_ema > values[-1]
    assert f18_exit_ema < values[-1]
    assert entry_ema != pytest.approx(f18_exit_ema)

    day = BASE + timedelta(days=249)
    dates = [BASE + timedelta(days=index) for index in range(250)]
    custom = {symbol: {day_: 100.0 for day_ in dates} for symbol in baseline.UNIVERSE}
    custom["SPY"] = dict(zip(dates, values, strict=True))
    signal = baseline.Bot1BaselineSignal(
        (day, day + timedelta(days=1)),
        atr_history={},
    )
    signal.quantities["SPY"] = 100.0
    signal.cash = baseline.STARTING_EQUITY - 100.0 * 100.0
    signal.positions["SPY"] = {
        "entry_date": day - timedelta(days=10),
        "entry_price": 100.0,
        "high_water": values[-1],
        "original_quantity": 100.0,
        "remaining": 1.0,
        "tp1": True,
        "tp2": True,
    }

    # A whole-history EMA would exit here; live F18's last-50 EMA does not.
    target = signal(custom, day)
    assert target is None
    assert "SPY" in signal.positions
    assert not signal.pending


def test_close_stop_triggers_exit_and_take_profits_are_ordered_and_once() -> None:
    dates = [BASE + timedelta(days=index) for index in range(8)]
    held_history = {
        symbol: {day: 100.0 for day in dates}
        for symbol in baseline.UNIVERSE
    }
    next_day = dates[-1] + timedelta(days=1)
    for values in held_history.values():
        values[next_day] = 100.0
    held_history["SPY"][next_day] = 113.0
    signal = baseline.Bot1BaselineSignal((dates[-1], next_day, next_day + timedelta(days=1)), {})
    signal.quantities["SPY"] = 120.0
    signal.cash = baseline.STARTING_EQUITY - 120.0 * 100.0
    signal.positions["SPY"] = {
        "entry_date": dates[-1] - timedelta(days=6),
        "entry_price": 100.0,
        "high_water": 100.0,
        "original_quantity": 120.0,
        "remaining": 1.0,
        "tp1": False,
        "tp2": False,
    }
    held_history["SPY"][dates[-1]] = 113.0

    target = signal(held_history, dates[-1])

    # TP2 is checked first and only one tier is marked in a single cycle.
    current_equity = signal.cash + 120.0 * 113.0
    assert target["SPY"] == pytest.approx(
        120.0 * (1 - 0.333) * 113.0 / current_equity
    )
    assert [action for action, symbol, _ in signal.pending if symbol == "SPY"] == [
        "tp2",
    ]
    signal(held_history, next_day)
    assert signal.positions["SPY"]["tp2"] is True
    assert [action for action, symbol, _ in signal.pending if symbol == "SPY"] == [
        "tp1",
    ]

    stop_signal = baseline.Bot1BaselineSignal((dates[-1], dates[-1] + timedelta(days=1)), {})
    stop_signal.quantities["SPY"] = 120.0
    stop_signal.cash = baseline.STARTING_EQUITY - 120.0 * 100.0
    stop_signal.positions["SPY"] = {
        "entry_date": dates[-1] - timedelta(days=6),
        "entry_price": 100.0,
        "high_water": 110.0,
        "original_quantity": 120.0,
        "remaining": 1.0,
        "tp1": True,
        "tp2": True,
    }
    held_history["SPY"][dates[-1]] = 100.0
    stop_target = stop_signal(held_history, dates[-1])
    assert stop_target["SPY"] == 0.0
    assert ("exit", "SPY", None) in stop_signal.pending


def test_candidate_warmup_and_portfolio_caps() -> None:
    history = _history(205, pattern="trend")
    dates = sorted(history["SPY"])
    atr_history = _bars(history)
    signal = baseline.Bot1BaselineSignal(
        (dates[-2], dates[-1], dates[-1] + timedelta(days=1)),
        atr_history,
    )

    short_history = {
        symbol: dict(list(values.items())[:-1])
        for symbol, values in history.items()
    }
    assert signal(short_history, dates[-2]) is None
    assert signal(history, dates[-1]) is not None
    targets = signal.last_targets

    assert 1 <= len(targets) <= baseline.MAX_POSITIONS
    assert sum(targets.values()) <= baseline.MAX_GROSS + 1e-12
    assert all(weight <= baseline.MAX_NAME_WEIGHT + 1e-12 for weight in targets.values())


def test_entry_and_regime_use_their_live_history_windows(monkeypatch) -> None:
    history = _history(330, pattern="trend")
    dates = sorted(history["SPY"])
    signal = baseline.Bot1BaselineSignal(
        (dates[-2], dates[-1], dates[-1] + timedelta(days=1)),
        _bars(history),
    )

    entry_lengths = []
    original_ema_last = baseline.ema_last

    def record_entry_length(values, span):
        if span in (baseline.FAST_EMA, baseline.SLOW_EMA):
            entry_lengths.append(len(values))
        return original_ema_last(values, span)

    monkeypatch.setattr(baseline, "ema_last", record_entry_length)

    regime_lengths = []
    original_regime = signal._regional_regime

    def record_regime_length(values):
        regime_lengths.append(len(values))
        return original_regime(values)

    signal._regional_regime = record_regime_length
    signal(history, dates[-1])

    assert regime_lengths and set(regime_lengths) == {310}
    assert 250 in entry_lengths
    assert 245 in entry_lengths
    assert max(entry_lengths) == 250


def test_candidate_requires_own_atr_history_even_after_close_warmup() -> None:
    history = _history(210, pattern="trend")
    dates = sorted(history["SPY"])
    atr_history = _bars(history)
    atr_history["SPY"] = {}
    signal = baseline.Bot1BaselineSignal((dates[-1], dates[-1] + timedelta(days=1)), atr_history)

    signal(history, dates[-1])
    assert "SPY" not in signal.last_targets


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: tuple[str, tuple] | None = None

    def execute(self, query: str, parameters: tuple) -> None:
        self.executed = (query, parameters)


def test_fake_cursor_placeholder_parameter_mismatch_fails_before_execute() -> None:
    cursor = _FakeCursor()
    with pytest.raises(ValueError, match="placeholder/parameter mismatch"):
        baseline._execute_checked(cursor, "SELECT %s, %s", (1,))
    assert cursor.executed is None

    baseline._execute_checked(cursor, "SELECT %s, %s", (1, 2))
    assert cursor.executed == ("SELECT %s, %s", (1, 2))


def test_signal_handles_symbols_without_a_current_point_in_time_close() -> None:
    day = BASE
    next_day = day + timedelta(days=1)
    history = {symbol: {} for symbol in baseline.UNIVERSE}
    history["SPY"] = {day: 100.0}
    signal = baseline.Bot1BaselineSignal((day, next_day), atr_history={})

    assert signal(history, day) is None
    assert not signal.positions
    assert all(quantity == 0 for quantity in signal.quantities.values())


def test_equal_weight_benchmark_rebalances_for_new_eligibility_and_new_year() -> None:
    first_day = date(2020, 1, 2)
    join_day = date(2020, 6, 1)
    unchanged_day = date(2020, 6, 2)
    next_year_day = date(2021, 1, 4)
    signal = baseline._equal_weight_universe_signal()

    def asof_history(day: date, eligible: set[str]):
        history = {symbol: {} for symbol in baseline.UNIVERSE}
        for symbol in eligible:
            history[symbol] = {
                day - timedelta(days=offset): 100.0
                for offset in range(199, -1, -1)
            }
        return history

    initial = signal(asof_history(first_day, {"SPY", "QQQ"}), first_day)
    assert initial == {"QQQ": 0.5, "SPY": 0.5}

    joined = signal(
        asof_history(join_day, {"SPY", "QQQ", "EEM"}),
        join_day,
    )
    assert joined == pytest.approx(
        {"EEM": 1 / 3, "QQQ": 1 / 3, "SPY": 1 / 3}
    )

    assert signal(
        asof_history(unchanged_day, {"SPY", "QQQ", "EEM"}),
        unchanged_day,
    ) is None
    yearly = signal(
        asof_history(next_year_day, {"SPY", "QQQ", "EEM"}),
        next_year_day,
    )
    assert yearly == pytest.approx(
        {"EEM": 1 / 3, "QQQ": 1 / 3, "SPY": 1 / 3}
    )


def test_point_in_time_spec_leaves_frozen_v1_hash_unchanged() -> None:
    assert baseline.spec_hash() == (
        "7708be0e4007ccd95e5aede6429d06e60ed0463cd7fca3b341466be67b196745"
    )
    assert baseline.spec_hash(baseline.SPEC_V2) != baseline.spec_hash()


def test_point_in_time_diagnostics_use_the_spy_calendar_label() -> None:
    dates = [
        date(2008, 1, 2) + timedelta(days=index)
        for index in range(205)
    ]
    panel = {
        symbol: dict.fromkeys(dates, 100.0)
        for symbol in baseline.UNIVERSE
    }

    record = baseline.run_scenarios(
        panel,
        atr_history={},
        calendar="point_in_time",
    )[0]

    assert record.diagnostics["actual_spy_first_session"] == "2008-01-02"
    assert "actual_common_first_session" not in record.diagnostics
    assert "late_listing_calendar_note" not in record.diagnostics
    assert record.diagnostics["calendar_note"].startswith("SPY valid-close")