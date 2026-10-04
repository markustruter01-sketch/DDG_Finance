from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

import pytest

from analysis import research_ledger
from core.bot_registry import active_bot_ids


BOT_IDS = tuple(active_bot_ids())
SNAPSHOT_DATE = date(2026, 9, 8)


class _SnapshotCursor:
    def __init__(
        self,
        portfolio_rows,
        previous_equity,
        *,
        benchmark_rows=None,
        canonical_conflicts=None,
    ):
        self.portfolio_rows = portfolio_rows
        self.previous_equity = previous_equity
        self.benchmark_rows = benchmark_rows or [
            (SNAPSHOT_DATE, 500.0),
            (SNAPSHOT_DATE - timedelta(days=1), 499.0),
        ]
        self.canonical_conflicts = canonical_conflicts or set()
        self.insert_params = []
        self.executed = []
        self._rows = []
        self._one = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=()):
        placeholders = query.count("%s")
        if placeholders != len(params):
            raise AssertionError(
                f"SQL placeholder mismatch: {placeholders} placeholders "
                f"for {len(params)} parameters: {query!r}"
            )
        self.executed.append((query, params))
        normalised = " ".join(query.lower().split())
        if "from bot_portfolio" in normalised:
            self._rows = self.portfolio_rows
            return
        if "from market_state" in normalised:
            self._rows = self.benchmark_rows
            return
        if "select equity_close from bot_daily_returns" in normalised:
            bot_id = params[0]
            previous = self.previous_equity.get(bot_id)
            self._one = (previous,) if previous is not None else None
            return
        if "insert into bot_daily_returns" in normalised:
            self.insert_params.append(params)
            self.rowcount = (
                0
                if (params[0], params[1]) in self.canonical_conflicts
                else 1
            )

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _SnapshotConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def _portfolio_rows(
    *,
    equities=None,
    last_updated=None,
):
    equities = equities or {
        "oracle": 100_000.0,
        "spy_qqq_trend": 101_000.0,
        "jerome_macro": 102_000.0,
        "forex_ai": 103_000.0,
    }
    last_updated = last_updated or datetime.now(timezone.utc)
    return [
        (
            bot_id,
            equities[bot_id],
            50_000.0,
            [{"symbol": "SPY", "value_usd": 50_000.0}],
            last_updated,
        )
        for bot_id in BOT_IDS
    ]


def _run_snapshot(monkeypatch, cursor, degradation_calls):
    monkeypatch.setattr(
        "db.postgres.get_conn",
        lambda: _SnapshotConnection(cursor),
    )
    monkeypatch.setattr(
        "core.degradation_tracker.record_degradation",
        lambda **kwargs: degradation_calls.append(kwargs) or True,
    )
    return research_ledger.snapshot_daily_returns(snapshot_date=SNAPSHOT_DATE)


def _insert_for(cursor, bot_id):
    return next(params for params in cursor.insert_params if params[1] == bot_id)


def test_fresh_portfolio_writes_provenance_and_computes_return(monkeypatch):
    now = datetime.now(timezone.utc)
    cursor = _SnapshotCursor(
        _portfolio_rows(),
        {
            "oracle": 99_000.0,
            "spy_qqq_trend": 100_000.0,
            "jerome_macro": 101_000.0,
            "forex_ai": 102_000.0,
        },
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)
    oracle = _insert_for(cursor, "oracle")

    assert result["status"] == "written"
    assert result["stale_count"] == 0
    assert result["skipped_count"] == 0
    assert oracle[4] == pytest.approx(100_000 / 99_000 - 1)
    assert oracle[12] == "bot_portfolio_fresh"
    assert oracle[13] == "equity_pct_change"
    assert oracle[14] == cursor.portfolio_rows[0][4]
    assert oracle[16] is False
    assert oracle[17] is not None
    assert oracle[18] is False
    assert oracle[17] >= now - timedelta(seconds=5)
    assert degradation_calls == []


def test_daily_returns_insert_columns_placeholders_and_params_match(monkeypatch):
    cursor = _SnapshotCursor(
        _portfolio_rows(),
        {bot_id: 99_000.0 for bot_id in BOT_IDS},
    )
    degradation_calls = []

    _run_snapshot(monkeypatch, cursor, degradation_calls)

    inserts = [
        (query, params)
        for query, params in cursor.executed
        if "insert into bot_daily_returns" in query.lower()
    ]
    assert len(inserts) == len(BOT_IDS)
    for query, params in inserts:
        match = re.search(
            r"INSERT\s+INTO\s+bot_daily_returns\s*\((.*?)\)\s*VALUES\s*\((.*?)\)",
            query,
            re.IGNORECASE | re.DOTALL,
        )
        assert match is not None
        columns = [column.strip() for column in match.group(1).split(",")]
        placeholders = match.group(2).count("%s")
        assert len(columns) == placeholders == len(params)


def test_stale_portfolio_writes_null_return_and_records_degradation(monkeypatch):
    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=research_ledger.STALE_AFTER_SECONDS + 1
    )
    cursor = _SnapshotCursor(
        _portfolio_rows(last_updated=stale_at),
        {bot_id: 99_000.0 for bot_id in BOT_IDS},
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)
    oracle = _insert_for(cursor, "oracle")

    assert result["stale_count"] == len(BOT_IDS)
    assert result["skipped_count"] == 0
    assert oracle[3] == 100_000.0
    assert oracle[4] is None
    assert oracle[12] == "bot_portfolio_stale:last_updated_exceeded_threshold"
    assert oracle[13] == "equity_pct_change_stale_last_known"
    assert oracle[14] == stale_at
    assert len(degradation_calls) == len(BOT_IDS)
    assert {call["error_type"] for call in degradation_calls} == {
        "daily_return_portfolio_stale"
    }


def test_portfolio_51_minutes_old_is_fresh_and_gets_return(monkeypatch):
    last_updated = datetime.now(timezone.utc) - timedelta(minutes=51)
    cursor = _SnapshotCursor(
        _portfolio_rows(last_updated=last_updated),
        {
            "oracle": 99_000.0,
            "spy_qqq_trend": 100_000.0,
            "jerome_macro": 101_000.0,
            "forex_ai": 102_000.0,
        },
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)
    oracle = _insert_for(cursor, "oracle")

    assert result["stale_count"] == 0
    assert result["skipped_count"] == 0
    assert oracle[4] == pytest.approx(100_000 / 99_000 - 1)
    assert oracle[12] == "bot_portfolio_fresh"
    assert oracle[13] == "equity_pct_change"
    assert degradation_calls == []


def test_fresh_unchanged_equity_remains_real_zero(monkeypatch):
    cursor = _SnapshotCursor(
        _portfolio_rows(),
        {bot_id: 100_000.0 + index * 1_000.0 for index, bot_id in enumerate(BOT_IDS)},
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)
    oracle = _insert_for(cursor, "oracle")

    assert result["stale_count"] == 0
    assert oracle[4] == 0.0
    assert oracle[12] == "bot_portfolio_fresh"
    assert oracle[13] == "equity_pct_change"
    assert degradation_calls == []


@pytest.mark.parametrize(
    "bad_equity",
    [None, 0.0, -1.0, float("nan"), float("inf")],
)
def test_unusable_equity_skips_row_and_records_degradation(monkeypatch, bad_equity):
    equities = {
        "oracle": bad_equity,
        "spy_qqq_trend": 101_000.0,
        "jerome_macro": 102_000.0,
        "forex_ai": 103_000.0,
    }
    cursor = _SnapshotCursor(
        _portfolio_rows(equities=equities),
        {bot_id: 99_000.0 for bot_id in BOT_IDS},
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)

    assert result["skipped_count"] == 1
    assert result["outcomes"][0]["bot_id"] == "oracle"
    assert result["outcomes"][0]["status"] == "skipped"
    assert all(params[1] != "oracle" for params in cursor.insert_params)
    assert len(cursor.insert_params) == len(BOT_IDS) - 1
    assert len(degradation_calls) == 1
    assert degradation_calls[0]["error_type"] == "daily_return_invalid_equity"
    assert degradation_calls[0]["bot_id"] == "oracle"


def test_canonical_existing_row_is_not_overwritten(monkeypatch):
    cursor = _SnapshotCursor(
        _portfolio_rows(),
        {bot_id: 99_000.0 for bot_id in BOT_IDS},
        canonical_conflicts={(SNAPSHOT_DATE, "oracle")},
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)

    assert result["skipped_count"] == 1
    oracle_outcome = next(
        outcome for outcome in result["outcomes"] if outcome["bot_id"] == "oracle"
    )
    assert oracle_outcome == {
        "bot_id": "oracle",
        "status": "skipped",
        "reason": "canonical_row_exists",
    }
    assert len(cursor.insert_params) == len(BOT_IDS)
    assert any(
        call["error_type"] == "daily_return_canonical_conflict"
        for call in degradation_calls
    )


def test_one_stale_bot_does_not_block_other_bots(monkeypatch):
    fresh = datetime.now(timezone.utc)
    stale = fresh - timedelta(seconds=research_ledger.STALE_AFTER_SECONDS + 1)
    rows = [
        ("oracle", 100_000.0, 50_000.0, [], fresh),
        ("spy_qqq_trend", 101_000.0, 50_000.0, [], stale),
        ("jerome_macro", 102_000.0, 50_000.0, [], fresh),
        ("forex_ai", 103_000.0, 50_000.0, [], fresh),
    ]
    cursor = _SnapshotCursor(
        rows,
        {bot_id: 99_000.0 for bot_id in BOT_IDS},
    )
    degradation_calls = []

    result = _run_snapshot(monkeypatch, cursor, degradation_calls)

    assert len(cursor.insert_params) == len(BOT_IDS)
    assert result["stale_count"] == 1
    assert result["skipped_count"] == 0
    assert {outcome["bot_id"] for outcome in result["outcomes"]} == set(BOT_IDS)