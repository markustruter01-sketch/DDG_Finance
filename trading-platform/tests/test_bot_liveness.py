from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core import bot_liveness
from analysis import health_monitor


class _Cursor:
    description = [("bot_id",), ("paused",), ("start",), ("end",),
                   ("success",), ("count",), ("failures",), ("error",), ("status",)]

    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=()):
        placeholders = query.count("%s")
        if placeholders != len(params):
            raise AssertionError(
                f"SQL placeholder mismatch: {placeholders} placeholders "
                f"for {len(params)} parameters"
            )
        return None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_instance = _Cursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def _rows(now: datetime, *, failures=0, success_age=10, missing=False):
    values = []
    for bot_id in bot_liveness.ACTIVE_BOTS:
        success = None if missing and bot_id == "jerome_macro" else now - timedelta(seconds=success_age)
        values.append((
            bot_id, False, success, success, success, 5, failures, "boom", "error",
        ))
    return values


def _patch_liveness_db(monkeypatch, rows):
    monkeypatch.setattr(
        "db.postgres.get_conn",
        lambda: _Connection(rows),
    )


def test_three_consecutive_failures_trip_trigger(monkeypatch):
    now = datetime.now(timezone.utc)
    _patch_liveness_db(monkeypatch, _rows(now, failures=3))
    findings = bot_liveness.evaluate_liveness(now=now)
    assert any(f["trigger"] == "bot_cycle_failures" for f in findings)


def test_stale_last_success_trips_trigger(monkeypatch):
    now = datetime.now(timezone.utc)
    _patch_liveness_db(monkeypatch, _rows(now, success_age=10_801))
    findings = bot_liveness.evaluate_liveness(now=now)
    assert any(f["trigger"] == "bot_cycle_stale" for f in findings)


def test_missing_liveness_row_trips_trigger(monkeypatch):
    now = datetime.now(timezone.utc)
    _patch_liveness_db(monkeypatch, _rows(now, missing=True))
    findings = bot_liveness.evaluate_liveness(now=now)
    assert any(
        f["trigger"] == "bot_cycle_health_missing_or_never_succeeded"
        and f["bot_id"] == "jerome_macro"
        for f in findings
    )


def test_healthy_bot_has_no_liveness_findings(monkeypatch):
    now = datetime.now(timezone.utc)
    _patch_liveness_db(monkeypatch, _rows(now, success_age=10))
    assert bot_liveness.evaluate_liveness(now=now) == []


def test_empty_health_metrics_are_unknown_not_healthy():
    concentration = health_monitor._check_symbol_concentration("oracle")
    streak = health_monitor._check_loss_streak("oracle")
    assert concentration["status"] == "UNKNOWN"
    assert concentration["score"] != 100
    assert streak["status"] == "UNKNOWN"
    assert streak["score"] != 100