from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core import runner_heartbeat
from core.invariants import InvariantInputs, check_runner_heartbeat_fresh


class _Cursor:
    description = [
        ("instance_token",),
        ("pid",),
        ("environment",),
        ("execution_mode",),
        ("started_at",),
        ("last_beat_at",),
        ("loop_count",),
        ("bots_registered",),
        ("status",),
    ]

    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args):
        self.executed.append(args)

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row=None):
        self.cursor_instance = _Cursor(row)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def _row(last_beat_at):
    return (
        "runner:v2:test",
        123,
        "dev",
        "read_only",
        datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        last_beat_at,
        4,
        3,
        "running",
    )


def test_fresh_heartbeat_returns_alive():
    now = datetime(2026, 8, 31, 12, 0, 20, tzinfo=timezone.utc)
    with patch("db.postgres.get_conn", return_value=_Connection(_row(now - timedelta(seconds=4)))):
        result = runner_heartbeat.get_runner_status(now=now)

    assert result["verdict"] == "ALIVE"
    assert result["age_seconds"] == 4
    assert result["threshold_seconds"] == runner_heartbeat.RUNNER_HEARTBEAT_THRESHOLD_SECONDS
    assert result["row"]["instance_token"] == "runner:v2:test"


def test_stale_heartbeat_returns_stale():
    now = datetime(2026, 8, 31, 12, 1, tzinfo=timezone.utc)
    with patch("db.postgres.get_conn", return_value=_Connection(_row(now - timedelta(seconds=16)))):
        result = runner_heartbeat.get_runner_status(now=now)

    assert result["verdict"] == "STALE"
    assert result["age_seconds"] == 16


def test_no_heartbeat_row_returns_absent():
    with patch("db.postgres.get_conn", return_value=_Connection(None)):
        result = runner_heartbeat.get_runner_status(
            now=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        )

    assert result["verdict"] == "ABSENT"
    assert result["row"] is None
    assert result["instance_token"] is None


def test_unreadable_heartbeat_table_raises_not_healthy():
    with patch("db.postgres.get_conn", side_effect=RuntimeError("table unavailable")):
        with pytest.raises(runner_heartbeat.RunnerHeartbeatReadError):
            runner_heartbeat.get_runner_status()


def test_write_runner_heartbeat_upserts_instance_row():
    conn = _Connection()
    started_at = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    beat_at = started_at + timedelta(seconds=5)
    with patch("db.postgres.get_conn", return_value=conn):
        assert runner_heartbeat.write_runner_heartbeat(
            instance_token="runner:v2:test",
            pid=123,
            environment="dev",
            execution_mode="read_only",
            started_at=started_at,
            loop_count=1,
            bots_registered=3,
            status="running",
            beat_at=beat_at,
        )

    sql, params = conn.cursor_instance.executed[0]
    assert "ON CONFLICT (instance_token)" in sql
    assert params[:4] == ("runner:v2:test", 123, "dev", "read_only")
    assert params[5:] == (beat_at, 1, 3, "running")


def test_runner_heartbeat_invariant_passes_when_alive():
    result = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "ALIVE",
                "age_seconds": 4,
                "threshold_seconds": 15,
                "row": {"instance_token": "runner:v2:test"},
            }
        )
    )

    assert result["status"] == "PASS"


def test_runner_heartbeat_invariant_fails_when_stale_or_absent():
    stale = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "STALE",
                "age_seconds": 16,
                "threshold_seconds": 15,
                "row": {"instance_token": "runner:v2:test"},
            }
        )
    )
    absent = check_runner_heartbeat_fresh(
        InvariantInputs(
            runner_heartbeat={
                "verdict": "ABSENT",
                "age_seconds": None,
                "threshold_seconds": 15,
                "row": None,
            }
        )
    )

    assert stale["status"] == "FAIL"
    assert absent["status"] == "FAIL"


def test_runner_heartbeat_invariant_is_unknown_when_table_unreadable():
    result = check_runner_heartbeat_fresh(
        InvariantInputs(source_errors={"runner_heartbeat": "table unavailable"})
    )

    assert result["status"] == "UNKNOWN"