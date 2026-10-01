from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest

from analysis import backtest_harness as harness


BASE = date(2022, 1, 3)


def _days(count: int) -> list[date]:
    return [BASE + timedelta(days=index) for index in range(count)]


def _panel(
    series: dict[str, list[float]],
    *,
    days: list[date] | None = None,
    flagged_rows_dropped: int = 0,
) -> harness.PricePanel:
    session_days = days or _days(len(next(iter(series.values()))))
    closes = {
        symbol: dict(zip(session_days, values, strict=True))
        for symbol, values in series.items()
    }
    return harness.PricePanel(closes, flagged_rows_dropped)


def _signal_on(day: date, targets: dict[str, float]):
    def signal(_history, current_day):
        return targets if current_day == day else None

    return signal


def _run(
    panel: harness.PricePanel,
    signal,
    *,
    end: date | None = None,
    cost_bps: float = 0,
    borrow_fee_rate: float = 0,
    risk_free_rate: float = 0,
    margin_rate: float = 0,
    max_gross: float = 1.5,
    starting_equity: float = 100.0,
    whole_shares: bool = False,
    trail_pct: float | None = None,
) -> harness.BacktestResult:
    available_dates = sorted(
        set.intersection(*(set(prices) for prices in panel.closes.values()))
    )
    return harness.run_backtest(
        panel,
        signal,
        available_dates[0],
        end or available_dates[-1],
        cost_bps=cost_bps,
        borrow_fee_rate=borrow_fee_rate,
        risk_free_rate=risk_free_rate,
        margin_rate=margin_rate,
        max_gross=max_gross,
        starting_equity=starting_equity,
        whole_shares=whole_shares,
        trail_pct=trail_pct,
    )


def test_buy_and_hold_tracks_price_return_less_entry_cost() -> None:
    days = _days(4)
    panel = _panel({"AAA": [10, 10, 12, 12]}, days=days)
    result = _run(
        panel,
        _signal_on(days[0], {"AAA": 1.0}),
        cost_bps=100,
        starting_equity=1_000,
    )

    assert result.equity_curve[0]["equity"] == pytest.approx(1_000)
    assert result.equity_curve[1]["equity"] == pytest.approx(990)
    assert result.equity_curve[-1]["equity"] == pytest.approx(1_190)
    assert result.metrics["total_return"] == pytest.approx(0.19)
    assert result.metrics["total_costs"] == pytest.approx(10)


def test_short_position_gains_when_price_falls() -> None:
    days = _days(4)
    panel = _panel({"AAA": [10, 10, 8, 8]}, days=days)
    result = _run(panel, _signal_on(days[0], {"AAA": -0.5}))

    assert result.equity_curve[-1]["equity"] == pytest.approx(110)
    assert result.metrics["total_return"] == pytest.approx(0.10)
    assert result.equity_curve[1]["cash"] == pytest.approx(150)


def test_margin_interest_and_borrow_fees_use_exact_calendar_day_accrual() -> None:
    days = [date(2022, 1, 3), date(2022, 1, 4), date(2022, 1, 6)]
    long_panel = _panel({"AAA": [10, 10, 10]}, days=days)
    margin_result = _run(
        long_panel,
        _signal_on(days[0], {"AAA": 1.5}),
        end=days[-1],
        margin_rate=0.365,
        max_gross=1.5,
    )
    short_panel = _panel({"AAA": [10, 10, 10]}, days=days)
    borrow_result = _run(
        short_panel,
        _signal_on(days[0], {"AAA": -0.5}),
        end=days[-1],
        borrow_fee_rate=0.365,
    )

    assert margin_result.metrics["total_interest"] == pytest.approx(0.1)
    assert margin_result.metrics["total_borrow_fees"] == pytest.approx(0)
    assert borrow_result.metrics["total_interest"] == pytest.approx(0)
    assert borrow_result.metrics["total_borrow_fees"] == pytest.approx(0.1)


def test_gross_exposure_is_scaled_to_the_configured_cap() -> None:
    days = _days(3)
    panel = _panel(
        {
            "AAA": [10, 10, 10],
            "BBB": [10, 10, 10],
        },
        days=days,
    )
    result = _run(
        panel,
        _signal_on(days[0], {"AAA": 1.2, "BBB": -1.0}),
        max_gross=1.5,
    )

    first_invested = result.equity_curve[1]
    assert first_invested["gross_exposure"] / first_invested["equity"] == pytest.approx(1.5)
    assert result.metrics["average_gross_exposure"] <= 1.5


@pytest.mark.parametrize(
    ("prices", "targets", "expected_side", "trigger_index", "exit_index"),
    [
        ([100, 100, 120, 100, 90], {"AAA": 0.5}, "long", 3, 4),
        ([100, 100, 80, 90, 100], {"AAA": -0.5}, "short", 3, 4),
    ],
)
def test_trailing_stops_trigger_on_close_and_exit_at_next_close(
    prices: list[float],
    targets: dict[str, float],
    expected_side: str,
    trigger_index: int,
    exit_index: int,
) -> None:
    days = _days(len(prices))
    panel = _panel({"AAA": prices}, days=days)
    result = _run(
        panel,
        _signal_on(days[0], targets),
        trail_pct=0.10,
    )

    triggered = next(
        event
        for event in result.events
        if event["type"] == "trailing_stop_triggered"
    )
    exited = next(
        event for event in result.events if event["type"] == "trailing_stop_exit"
    )
    assert triggered["side"] == expected_side
    assert triggered["date"] == days[trigger_index].isoformat()
    assert exited["date"] == days[exit_index].isoformat()
    assert result.equity_curve[trigger_index]["gross_exposure"] > 0
    assert result.equity_curve[exit_index]["gross_exposure"] == pytest.approx(0)


def test_signal_on_day_t_executes_at_next_close_and_gets_no_future_history() -> None:
    days = _days(4)
    panel = _panel({"AAA": [10, 20, 20, 20]}, days=days)
    future_day = days[-1]

    def signal(history, decision_day):
        assert all(day <= decision_day for day in history["AAA"])
        if decision_day < future_day:
            with pytest.raises(KeyError):
                _ = history["AAA"][future_day]
        return {"AAA": 1.0} if decision_day == days[0] else None

    result = _run(panel, signal)
    first_trade = next(event for event in result.events if event["type"] == "trade")

    assert first_trade["date"] == days[1].isoformat()
    assert first_trade["price"] == pytest.approx(20)
    assert first_trade["quantity_change"] == pytest.approx(5)
    assert result.equity_curve[0]["equity"] == pytest.approx(100)


def test_holdout_run_requires_registered_uncompleted_experiment() -> None:
    days = [harness.EXPLORE_END, harness.EXPLORE_END + timedelta(days=1)]
    panel = _panel({"AAA": [10, 10]}, days=days)

    with pytest.raises(ValueError, match="registered research_ledger experiment"):
        harness.run_backtest(
            panel,
            lambda _history, _day: None,
            days[0],
            days[1],
            cost_bps=0,
            borrow_fee_rate=0,
            risk_free_rate=0,
        )


@pytest.mark.parametrize(
    ("ledger_row", "should_raise"),
    [
        ((True,), False),
        ((False,), True),
        (None, True),
    ],
)
def test_holdout_accepts_only_existing_experiments_without_results(
    monkeypatch: pytest.MonkeyPatch,
    ledger_row: tuple[bool] | None,
    should_raise: bool,
) -> None:
    days = [harness.EXPLORE_END, harness.EXPLORE_END + timedelta(days=1)]
    panel = _panel({"AAA": [10, 10]}, days=days)

    class LedgerCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, params: tuple[int]) -> None:
            assert "FROM research_ledger" in query
            assert params == (17,)

        def fetchone(self):
            return ledger_row

    class LedgerConnection:
        def cursor(self) -> LedgerCursor:
            return LedgerCursor()

    @contextmanager
    def fake_research_connection():
        yield LedgerConnection()

    monkeypatch.setattr(harness, "get_research_conn", fake_research_connection)
    call = lambda: harness.run_backtest(
        panel,
        lambda _history, _day: None,
        days[0],
        days[1],
        cost_bps=0,
        borrow_fee_rate=0,
        risk_free_rate=0,
        registered_experiment_id=17,
    )
    if should_raise:
        with pytest.raises(ValueError, match="exists and has no results recorded"):
            call()
    else:
        assert call().data_window["requested_end"] == days[1].isoformat()


def test_quality_flagged_rows_are_dropped_without_price_filling() -> None:
    days = _days(4)
    panel = harness._panel_from_rows(
        [
            ("AAA", days[0], 10, None),
            ("AAA", days[1], 999, "suspect_bad_print"),
            ("AAA", days[2], 12, None),
            ("AAA", days[3], 13, None),
        ]
    )
    result = _run(panel, lambda _history, _day: None)

    assert panel.flagged_rows_dropped == 1
    assert days[1] not in panel.closes["AAA"]
    assert [point["date"] for point in result.equity_curve] == [
        days[0], days[2], days[3]
    ]
    assert result.data_window["flagged_rows_dropped"] == 1


def test_margin_call_is_recorded_and_position_is_reduced_to_gross_cap() -> None:
    days = _days(3)
    panel = _panel({"AAA": [10, 10, 4]}, days=days)
    result = _run(
        panel,
        _signal_on(days[0], {"AAA": 1.5}),
        max_gross=1.5,
    )

    margin_call = next(
        event for event in result.events if event["type"] == "margin_call"
    )
    after_call = result.equity_curve[-1]
    assert margin_call["equity_to_gross_before"] < 0.30
    assert after_call["gross_exposure"] / after_call["equity"] == pytest.approx(1.5)


class _CheckingCursor:
    def __init__(self) -> None:
        self.last_query = ""
        self.last_params: tuple[Any, ...] = ()

    def __enter__(self) -> "_CheckingCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        placeholders = len(re.findall(r"(?<!%)%s", query))
        values = tuple(params or ())
        if placeholders != len(values):
            raise AssertionError(
                f"SQL has {placeholders} %s placeholders but received {len(values)} parameters"
            )
        self.last_query = query
        self.last_params = values

    def fetchone(self) -> tuple[int]:
        return (71,)


class _CheckingConnection:
    def __init__(self) -> None:
        self.last_cursor = _CheckingCursor()

    def cursor(self) -> _CheckingCursor:
        return self.last_cursor


def test_exploration_run_insert_uses_existing_columns_and_checked_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    days = _days(3)
    panel = _panel({"AAA": [10, 10, 11]}, days=days)
    result = _run(panel, _signal_on(days[0], {"AAA": 0.5}))
    connection = _CheckingConnection()

    @contextmanager
    def fake_research_connection():
        yield connection

    monkeypatch.setattr(harness, "get_research_conn", fake_research_connection)
    with pytest.raises(AssertionError, match="placeholders"):
        connection.last_cursor.execute("SELECT %s, %s", (1,))

    run_id = harness.append_exploration_run(
        result,
        strategy_family="synthetic_test",
        notes="fake-only test",
    )

    assert run_id == 71
    assert len(re.findall(r"(?<!%)%s", connection.last_cursor.last_query)) == len(
        connection.last_cursor.last_params
    )
    assert "INSERT INTO exploration_runs" in connection.last_cursor.last_query
    assert "results" not in connection.last_cursor.last_query
