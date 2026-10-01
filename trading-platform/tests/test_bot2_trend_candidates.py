from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, timedelta
from math import sqrt
from statistics import stdev
from typing import Any

import pytest

from analysis import bot2_trend_candidates as candidates
from analysis.backtest_harness import BacktestResult, PricePanel


BASE = date(2020, 1, 1)


def _history(
    *,
    count: int = 80,
    risk_returns: list[float] | None = None,
    cash_returns: list[float] | None = None,
) -> dict[str, dict[date, float]]:
    dates = [BASE + timedelta(days=index) for index in range(count)]
    risk_returns = risk_returns or [0.01 if i % 2 == 0 else -0.01 for i in range(count - 1)]
    cash_returns = cash_returns or [0.0] * (count - 1)
    assert len(risk_returns) == count - 1
    assert len(cash_returns) == count - 1

    def prices(returns: list[float]) -> list[float]:
        values = [100.0]
        for daily_return in returns:
            values.append(values[-1] * (1.0 + daily_return))
        return values

    return {
        "RISK": dict(zip(dates, prices(risk_returns), strict=True)),
        "BIL": dict(zip(dates, prices(cash_returns), strict=True)),
    }


def test_ema_signal_direction_and_strict_flat_band() -> None:
    assert candidates.classify_ema_trend(100.11, 100.0) == 1
    assert candidates.classify_ema_trend(100.05, 100.0) == 0
    assert candidates.classify_ema_trend(99.95, 100.0) == 0
    assert candidates.classify_ema_trend(99.89, 100.0) == -1


def test_ema_uses_recursive_adjust_false_convention() -> None:
    assert candidates.ema_last([100.0, 110.0], 3) == pytest.approx(105.0)


def test_equal_risk_weights_are_inverse_vol_and_respect_position_budget() -> None:
    weights = candidates.equal_risk_weights(
        {"LOW": 0.10, "HIGH": 0.20},
        {"LOW": 1, "HIGH": 1},
        total_gross_budget=0.5,
    )

    assert weights["LOW"] == pytest.approx(1 / 3)
    assert weights["HIGH"] == pytest.approx(1 / 6)
    assert weights["LOW"] * 0.10 == pytest.approx(weights["HIGH"] * 0.20)
    assert sum(abs(weight) for weight in weights.values()) == pytest.approx(0.5)


def test_target_volatility_scaling_targets_ten_percent_annualized() -> None:
    history = _history()
    target = candidates.scale_to_target_volatility(
        history,
        {"RISK": 0.5},
    )
    daily_returns = candidates._returns_by_symbol(history, ("RISK", "BIL"))
    combined = [
        target.get("RISK", 0.0) * daily_returns["RISK"][index]
        + target.get("BIL", 0.0) * daily_returns["BIL"][index]
        for index in range(len(daily_returns["RISK"]))
    ]

    assert stdev(combined) * sqrt(candidates.TRADING_DAYS_PER_YEAR) == pytest.approx(
        0.10,
        abs=1e-8,
    )


def test_target_volatility_scaling_respects_gross_cap() -> None:
    history = _history(
        risk_returns=[0.0001 if i % 2 == 0 else -0.0001 for i in range(79)]
    )
    target = candidates.scale_to_target_volatility(history, {"RISK": 1.0})

    assert sum(abs(weight) for weight in target.values()) <= 1.5 + 1e-9
    assert sum(abs(weight) for weight in target.values()) == pytest.approx(1.5)


def test_candidate_a_is_long_only_and_parks_inactive_allocation_in_bil() -> None:
    history = _history(count=220)
    target = candidates.build_candidate_targets(
        "A",
        history,
        {"RISK": -1},
        universe=("RISK",),
    )

    assert target == {"BIL": 1.0}
    assert all(weight >= 0 for weight in target.values())


def test_candidate_c_ignores_trend_signal_and_remains_long_only() -> None:
    history = _history(count=220)
    target = candidates.build_candidate_targets(
        "C",
        history,
        {"RISK": -1},
        universe=("RISK",),
    )

    assert target["RISK"] > 0
    assert target["BIL"] >= 0
    assert sum(target.values()) == pytest.approx(1.0)


def test_candidate_c_uses_one_entry_then_ignores_later_trend_signals() -> None:
    risk_returns = [0.001] * 219
    history = _history(
        count=220,
        risk_returns=risk_returns,
        cash_returns=[0.0001] * 219,
    )
    sessions = sorted(history["RISK"])[200:]
    signal = candidates.CandidateSignal("C", sessions, universe=("RISK",))
    seen: list[dict[str, float] | None] = []

    for day in sessions[:4]:
        as_of = {
            symbol: {close_day: value for close_day, value in values.items() if close_day <= day}
            for symbol, values in history.items()
        }
        seen.append(signal(as_of, day))

    assert seen[0] == {"BIL": 1.0}
    assert seen[1] is not None and seen[1]["RISK"] > 0
    assert seen[2:] == [None, None]


def test_candidate_d_is_a_fifty_fifty_signed_weight_blend() -> None:
    blended = candidates.blend_half_weights(
        {"AAA": 0.4, "BBB": -0.2},
        {"AAA": 0.2, "CCC": 0.6},
    )

    assert blended == pytest.approx({"AAA": 0.3, "BBB": -0.1, "CCC": 0.3})


def test_spec_hash_is_deterministic_and_covers_the_frozen_spec() -> None:
    encoded = candidates.canonical_spec_json()

    assert candidates.spec_hash() == candidates.spec_hash()
    assert candidates.SOURCE == "backtest_harness f7ff08e8"
    assert "2022-12-31" in encoded
    assert candidates.RUN_PLAN == (
        ("A", 5),
        ("B", 5),
        ("C", 5),
        ("D", 5),
        ("A", 10),
        ("B", 10),
        ("C", 10),
        ("D", 10),
    )


def test_window_return_uses_prior_close_for_weekend_start() -> None:
    curve = (
        {"date": date(2008, 8, 29), "equity": 100.0},
        {"date": date(2008, 9, 2), "equity": 110.0},
        {"date": date(2009, 3, 31), "equity": 120.0},
    )

    value = candidates._window_return(
        curve,
        date(2008, 9, 1),
        date(2009, 3, 31),
    )

    assert value == pytest.approx(0.20)


def test_daily_return_correlation_aligns_strategy_and_spy_close_intervals() -> None:
    days = [BASE + timedelta(days=index) for index in range(4)]
    spy_prices = [100.0, 101.0, 99.99, 101.9898]
    strategy_equity = [100.0, 102.0, 99.96, 103.9584]
    result = BacktestResult(
        equity_curve=tuple(
            {"date": day, "equity": equity}
            for day, equity in zip(days, strategy_equity, strict=True)
        ),
        events=(),
        metrics={},
        parameters={},
        data_window={},
    )

    correlation = candidates.correlation_with_spy(
        result,
        PricePanel({"SPY": dict(zip(days, spy_prices, strict=True))}),
    )

    assert correlation == pytest.approx(1.0)


def _fake_record(candidate: str, cost_bps: int) -> candidates.CandidateRun:
    result = BacktestResult(
        equity_curve=(),
        events=(),
        metrics={
            "sharpe": 0.25,
            "total_return": 0.05,
            "max_drawdown": 0.10,
        },
        parameters={"cost_bps": cost_bps},
        data_window={"requested_end": "2022-12-31"},
    )
    return candidates.CandidateRun(candidate, cost_bps, result, {})


class _CheckingCursor:
    def __init__(self) -> None:
        self.last_query = ""
        self.last_params: tuple[Any, ...] = ()
        self.insert_count = 0

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
        self.insert_count += 1

    def fetchone(self) -> tuple[int]:
        return (700 + self.insert_count,)


class _CheckingConnection:
    def __init__(self) -> None:
        self.last_cursor = _CheckingCursor()

    def cursor(self) -> _CheckingCursor:
        return self.last_cursor


def test_exploration_insert_writes_eight_rows_and_checks_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _CheckingConnection()

    @contextmanager
    def fake_research_connection():
        yield connection

    monkeypatch.setattr(candidates, "get_research_conn", fake_research_connection)
    with pytest.raises(AssertionError, match="placeholders"):
        connection.last_cursor.execute("SELECT %s, %s", (1,))

    records = [
        _fake_record(candidate, cost_bps)
        for candidate, cost_bps in candidates.RUN_PLAN
    ]
    run_ids = candidates.append_exploration_runs(
        records,
        frozen_spec_hash=candidates.spec_hash(),
    )

    assert run_ids == list(range(701, 709))
    assert connection.last_cursor.insert_count == 8
    assert "INSERT INTO exploration_runs" in connection.last_cursor.last_query
    assert connection.last_cursor.last_params[0] == "bot2_trend_v1"
    assert connection.last_cursor.last_params[4] == "backtest_harness f7ff08e8"
    assert connection.last_cursor.last_params[3] == candidates.spec_hash()
    assert len(
        re.findall(r"(?<!%)%s", connection.last_cursor.last_query)
    ) == len(connection.last_cursor.last_params)