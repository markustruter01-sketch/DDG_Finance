from __future__ import annotations

from fastapi.testclient import TestClient

from core import runner_heartbeat
from main import API_PREFIX, app


def _liveness_path() -> str:
    prefix = API_PREFIX.rstrip("/")
    return f"{prefix}/liveness" if prefix else "/liveness"


def test_liveness_returns_503_for_stale_heartbeat_without_auth(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)
    monkeypatch.setattr(
        runner_heartbeat,
        "get_runner_status",
        lambda: {"verdict": "STALE", "age_seconds": 16.25},
    )

    client = TestClient(app)
    response = client.get(_liveness_path())
    client.close()

    assert response.status_code == 503
    assert response.json() == {"runner": "STALE", "age_seconds": 16.25}


def test_liveness_returns_503_for_absent_heartbeat_without_auth(monkeypatch):
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)
    monkeypatch.setattr(
        runner_heartbeat,
        "get_runner_status",
        lambda: {"verdict": "ABSENT", "age_seconds": None},
    )

    client = TestClient(app)
    response = client.get(_liveness_path())
    client.close()

    assert response.status_code == 503
    assert response.json() == {"runner": "ABSENT", "age_seconds": None}