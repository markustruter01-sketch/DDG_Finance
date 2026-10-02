from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest

from analysis import fleet_test


def test_fleet_uses_three_independently_compounded_sleeves() -> None:
    sessions = (date(2020, 1, 2), date(2020, 1, 3))
    returns = {
        "bot1": (0.10, 0.0),
        "bot2": (-0.05, 0.10),
        "bot3": (0.0, 0.10),
    }

    metrics, curve = fleet_test._fleet_metrics(returns, sessions)

    assert curve[0]["equity"] == pytest.approx(305_000.0)
    assert curve[1]["equity"] == pytest.approx(324_500.0)
    assert metrics["total_return"] == pytest.approx(324_500.0 / 300_000.0 - 1)
    assert metrics["max_drawdown"] == pytest.approx(0.0)


def test_cost_bar_requires_both_conditions_and_includes_sharpe_boundary() -> None:
    at_boundary = fleet_test._evaluate_cost_bar(
        with_a_sharpe=0.45,
        without_a_sharpe=0.40,
        candidate_a_cagr=0.02,
        bil_cagr=0.01,
    )
    assert at_boundary == {
        "sharpe_delta": pytest.approx(0.05),
        "sharpe_bar_pass": True,
        "cagr_bar_pass": True,
        "status": "PASS",
    }

    cagr_tie = fleet_test._evaluate_cost_bar(0.45, 0.40, 0.01, 0.01)
    assert cagr_tie["sharpe_bar_pass"] is True
    assert cagr_tie["cagr_bar_pass"] is False
    assert cagr_tie["status"] == "FAIL"

    below_bar = fleet_test._evaluate_cost_bar(0.449, 0.40, 0.02, 0.01)
    assert below_bar["sharpe_bar_pass"] is False
    assert below_bar["status"] == "FAIL"


def test_daily_return_correlation_matrix_is_pearson() -> None:
    matrix = fleet_test._correlation_matrix(
        {
            "bot1": (0.01, -0.02, 0.03),
            "bot2": (-0.01, 0.02, -0.03),
            "bot3": (0.02, 0.01, 0.0),
        }
    )

    assert matrix["bot1"]["bot1"] == 1.0
    assert matrix["bot1"]["bot2"] == pytest.approx(-1.0)
    assert matrix["bot2"]["bot1"] == pytest.approx(-1.0)


def test_first_held_date_accepts_serialized_harness_event_dates() -> None:
    result = type(
        "FakeResult",
        (),
        {
            "events": (
                {"type": "trade", "date": "2018-04-03", "quantity_after": 1.0},
            )
        },
    )()

    assert fleet_test._first_held_date(result) == date(2018, 4, 3)


class StrictFakeCursor:
    """Fake cursor that rejects every SQL call with a placeholder mismatch."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._last_result: tuple[Any, ...] | None = None
        self._count_queries = 0
        self._next_run_id = 900

    def __enter__(self) -> StrictFakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        if query.count("%s") != len(parameters):
            raise AssertionError(
                f"Fake cursor received {query.count('%s')} placeholders "
                f"for {len(parameters)} parameters"
            )
        self.calls.append((query, parameters))
        normalized = " ".join(query.lower().split())
        if normalized.startswith("select count(*)"):
            self._count_queries += 1
            self._last_result = (0 if self._count_queries == 1 else 4,)
        elif normalized.startswith("insert into public.exploration_runs"):
            self._last_result = (self._next_run_id,)
            self._next_run_id += 1
        else:
            raise AssertionError(f"Unexpected SQL in fake: {query}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._last_result


class StrictFakeConnection:
    def __init__(self, cursor: StrictFakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> StrictFakeCursor:
        return self._cursor


def _insert_test_report() -> dict[str, Any]:
    records = []
    for cost in fleet_test.COST_SCENARIOS:
        for mode in ("with_candidate_A", "without_candidate_A"):
            records.append(
                {
                    "mode": mode,
                    "cost_bps": cost,
                    "source_run_refs": {
                        "bot1": 123,
                        "bot2": "in_memory_bil_buy_and_hold_5bps",
                        "bot3": 125,
                    },
                    "metrics": {
                        "sharpe": 0.2,
                        "total_return": 0.1,
                        "max_drawdown": 0.05,
                    },
                    "window": {
                        "start": "2018-04-03",
                        "end": "2022-12-30",
                        "session_count": 1000,
                    },
                    "sharpe_delta_with_minus_without": 0.04,
                    "candidate_a_cagr_full_period": 0.01,
                    "bil_cagr_full_period": 0.02,
                    "status": "FAIL",
                    "standalone_sharpes": {},
                    "correlation_matrix": {},
                    "sharpe_bar_pass": False,
                    "cagr_bar_pass": False,
                }
            )
    return {
        "_records": records,
        "overall_status": "FAIL",
        "actual_window": {
            "start": "2018-04-03",
            "end": "2022-12-30",
            "session_count": 1000,
        },
    }


def test_insert_appends_exactly_four_rows_with_strict_fake_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import db.research_postgres

    cursor = StrictFakeCursor()
    connection = StrictFakeConnection(cursor)

    @contextmanager
    def fake_research_connection():
        yield connection

    monkeypatch.setattr(
        db.research_postgres,
        "get_research_conn",
        fake_research_connection,
    )

    run_ids = fleet_test._insert_records(_insert_test_report())

    assert run_ids == [900, 901, 902, 903]
    insert_calls = [
        (query, params)
        for query, params in cursor.calls
        if query.lstrip().lower().startswith("insert into")
    ]
    assert len(insert_calls) == 4
    assert all(query.count("%s") == len(params) == 9 for query, params in insert_calls)
    assert all("research_ledger" not in query.lower() for query, _ in cursor.calls)


def test_checked_execute_fails_before_a_fake_can_accept_bad_parameters() -> None:
    cursor = StrictFakeCursor()

    with pytest.raises(ValueError, match="placeholder/parameter mismatch"):
        fleet_test._execute_checked(cursor, "SELECT %s, %s", (1,))

    assert cursor.calls == []
    with pytest.raises(AssertionError, match="Fake cursor received"):
        cursor.execute("SELECT %s", ())