from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np

from analysis import research_ledger
from core.market_clock import is_nyse_session_date, previous_nyse_session_date
from core.metrics import risk_metrics


class _FakeCursor:
    def __init__(self, *, snapshots=None, activation=None):
        self.snapshots = snapshots or []
        self.activation = activation or []
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=()):
        self.executed.append((query, params))

    def fetchall(self):
        query = self.executed[-1][0]
        if "per_bot_vault_accounts" in query:
            return self.activation
        if "fleet_equity_snapshots" in query:
            return self.snapshots
        if "market_state" in query:
            return []
        return []

    def fetchone(self):
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def test_nyse_calendar_skips_weekends_and_holidays():
    assert not is_nyse_session_date(date(2026, 9, 5))
    assert not is_nyse_session_date(date(2026, 9, 7))
    assert is_nyse_session_date(date(2026, 9, 8))
    assert previous_nyse_session_date(date(2026, 9, 8)) == date(2026, 9, 4)


def test_legacy_snapshot_is_only_allowed_before_vault_activation():
    legacy = (
        datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc),
        100.0, None, None, None, "legacy",
    )
    assert research_ledger._snapshot_values(legacy, allow_pre_vault=True)["equity"] == 100
    assert research_ledger._snapshot_values(legacy, allow_pre_vault=False) is None


def test_enriched_snapshot_excludes_bil_and_voo_from_trading_equity():
    row = research_ledger.enriched_snapshot_from_portfolio({
        "bot_id": "oracle",
        "equity_usd": 1000,
        "positions": [
            {"symbol": "SPY", "market_value": 700},
            {"symbol": "BIL", "market_value": 200},
            {"symbol": "VOO", "market_value": 100},
        ],
    })
    assert row["vault_value_usd"] == 300
    assert row["trading_equity_usd"] == 700
    assert row["capital_base_usd"] == 700


def test_missing_live_source_writes_no_row(monkeypatch):
    cursor = _FakeCursor()
    monkeypatch.setattr(
        "db.postgres.get_conn", lambda: _FakeConnection(cursor)
    )
    result = research_ledger.snapshot_daily_returns(
        snapshot_date=date(2026, 9, 8)
    )
    assert result["status"] == "skipped"
    assert result["unavailable"]
    assert not any("INSERT INTO bot_daily_returns" in query for query, _ in cursor.executed)


def test_fleet_reader_intersects_actual_dates(monkeypatch):
    rows = {
        "oracle": [
            {"date": "2026-09-01", "daily_return": 0.01},
            {"date": "2026-09-02", "daily_return": 0.02},
        ],
        "spy_qqq_trend": [
            {"date": "2026-09-02", "daily_return": 0.03},
            {"date": "2026-09-03", "daily_return": 0.04},
        ],
    }
    monkeypatch.setattr(
        research_ledger,
        "get_bot_daily_returns",
        lambda bot_id, **kwargs: rows[bot_id],
    )
    result = research_ledger.get_fleet_daily_returns(
        ("oracle", "spy_qqq_trend")
    )
    assert result["dates"] == ["2026-09-02"]
    assert result["returns"] == {
        "oracle": [0.02],
        "spy_qqq_trend": [0.03],
    }
    assert result["common_data_points"] == 1


def test_sharpe_uses_shared_sample_daily_convention():
    returns = [0.01, 0.02, 0.00, -0.01, 0.015, 0.005, 0.012, -0.004, 0.008, 0.011]
    expected = (
        (np.mean(returns) - 0.05 / 252)
        / np.std(returns, ddof=1)
        * np.sqrt(252)
    )
    result = risk_metrics(returns)
    assert result["sharpe_ratio"] == round(float(expected), 3)
    assert result["data_points"] == 10


def test_backfill_is_repeatable_and_uses_pre_vault_total_equity(monkeypatch):
    snapshots = [
        ("oracle", date(2026, 9, 1), datetime(2026, 9, 1, 20, tzinfo=timezone.utc),
         100.0, None, None, None, "legacy"),
        ("oracle", date(2026, 9, 2), datetime(2026, 9, 2, 20, tzinfo=timezone.utc),
         101.0, None, None, None, "legacy"),
    ]
    cursors = []

    def make_conn():
        cursor = _FakeCursor(snapshots=snapshots)
        cursors.append(cursor)
        return _FakeConnection(cursor)

    monkeypatch.setattr("db.postgres.get_conn", make_conn)
    first = research_ledger.backfill_daily_returns(
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2)
    )
    second = research_ledger.backfill_daily_returns(
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2)
    )
    assert first["rows"] == second["rows"] == 1
    assert first["bots"]["oracle"]["first_date"] == "2026-09-02"
    inserts = [
        query for cursor in cursors for query, _ in cursor.executed
        if "INSERT INTO bot_daily_returns" in query
    ]
    assert len(inserts) == 2
    assert all("ON CONFLICT (date, bot_id)" in query for query in inserts)