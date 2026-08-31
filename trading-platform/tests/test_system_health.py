from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from core.bot_liveness import ACTIVE_BOTS
from routes import system


class _HealthCursor:
    def __init__(self, events: list[dict]):
        self.events = events
        self.description = []
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, *_params):
        if "system_degradations" in query:
            self.description = [
                ("component",), ("severity",), ("error_type",), ("message",), ("ts",),
            ]
            self._rows = [
                (
                    event["component"],
                    event["severity"],
                    event["error_type"],
                    event["message"],
                    event.get("ts"),
                )
                for event in self.events
            ]
        else:
            self.description = [("one",)]
            self._rows = []

    def fetchall(self):
        return self._rows


class _HealthConnection:
    def __init__(self, events: list[dict]):
        self.cursor_instance = _HealthCursor(events)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance


def _liveness_rows(now: datetime, *, stale_bot: str | None = None) -> list[dict]:
    rows = []
    for bot_id in ACTIVE_BOTS:
        age = 10 if bot_id != stale_bot else 108001
        rows.append(
            {
                "bot_id": bot_id,
                "portfolio_last_updated": now - timedelta(seconds=age),
                "cycle_last_success": now - timedelta(seconds=age),
                "cycle_status": "success",
                "consecutive_failures": 0,
                "paused": False,
            }
        )
    return rows


def _call_health_endpoint(
    monkeypatch, rows, events=None, *, patch_liveness=True, database_error=False
):
    if patch_liveness:
        monkeypatch.setattr("core.bot_liveness.get_architecture_liveness", lambda: rows)
    if database_error:
        def fail_database():
            raise RuntimeError("database unavailable")

        monkeypatch.setattr("db.postgres.get_conn", fail_database)
    else:
        monkeypatch.setattr(
            "db.postgres.get_conn",
            lambda: _HealthConnection(events or []),
        )
    monkeypatch.setattr(system, "get_job_status", lambda: [])
    monkeypatch.setattr(system, "get_last_run", lambda: {})
    monkeypatch.setattr(system, "get_account", lambda: {"equity": "100000"})
    monkeypatch.setattr("notifications.discord.is_configured", lambda: True)
    return asyncio.run(system.system_health_architecture())


def test_healthy_bots_report_healthy(monkeypatch):
    now = datetime.now(timezone.utc)
    response = _call_health_endpoint(monkeypatch, _liveness_rows(now))

    assert response["status"] == "healthy"
    assert all(
        response["nodes"][f"bot_{bot_id}"]["level"] == "green"
        for bot_id in ACTIVE_BOTS
    )


def test_stale_bot_cannot_report_green(monkeypatch):
    now = datetime.now(timezone.utc)
    response = _call_health_endpoint(
        monkeypatch, _liveness_rows(now, stale_bot="oracle")
    )

    oracle = response["nodes"]["bot_oracle"]
    assert oracle["level"] == "yellow"
    assert oracle["data_age_s"] > 108000
    assert "portfolio age" in oracle["detail"]
    assert response["status"] == "degraded"


def test_unresolved_high_severity_degradation_reports_degraded(monkeypatch):
    now = datetime.now(timezone.utc)
    response = _call_health_endpoint(
        monkeypatch,
        _liveness_rows(now),
        events=[
            {
                "component": "bot/oracle",
                "severity": "high",
                "error_type": "bot_stale_workflow",
                "message": "Oracle is stale",
            }
        ],
    )

    assert response["status"] == "degraded"
    assert response["unresolved_high_severity_count"] == 1
    assert response["nodes"]["degradation_events"]["level"] == "red"


def test_required_liveness_read_failure_reports_unknown(monkeypatch):
    def fail_liveness():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("core.bot_liveness.get_architecture_liveness", fail_liveness)
    response = _call_health_endpoint(monkeypatch, [], patch_liveness=False)

    assert response["status"] == "unknown"
    assert response["nodes"]["bot_oracle"]["level"] == "red"
    assert "read failed" in response["nodes"]["bot_oracle"]["detail"]


def test_required_database_read_failure_reports_unknown(monkeypatch):
    now = datetime.now(timezone.utc)
    response = _call_health_endpoint(
        monkeypatch,
        _liveness_rows(now),
        database_error=True,
    )

    assert response["status"] == "unknown"
    assert response["nodes"]["database"]["level"] == "red"