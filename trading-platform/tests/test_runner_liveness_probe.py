from __future__ import annotations

import asyncio

from core import scheduler


class _Response:
    status_code = 200

    def json(self):
        return {"service": "kraken-bot-runner"}


class _ApiResponse:
    status_code = 200

    def json(self):
        return {"fleet_total": {"equity": 123}}


class _HealthyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, *_args, **_kwargs):
        return _Response()


class _FailingClient(_HealthyClient):
    async def get(self, *_args, **_kwargs):
        raise TimeoutError("simulated runner outage")


class _ApiClient(_HealthyClient):
    async def get(self, *_args, **_kwargs):
        return _ApiResponse()


class _CapturingApiClient(_HealthyClient):
    request_headers = None

    async def get(self, *_args, **kwargs):
        self.request_headers = kwargs.get("headers")
        return _ApiResponse()


class _RecordingScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, **kwargs):
        self.jobs.append(kwargs)


def test_runner_probe_alerts_after_threshold(monkeypatch):
    alerts = []
    scheduler._runner_liveness_failures = 0
    scheduler._runner_liveness_alerted = False
    scheduler.RUNNER_HEALTH_FAILURE_THRESHOLD = 2
    monkeypatch.setattr(
        scheduler.httpx,
        "AsyncClient",
        lambda **_kwargs: _FailingClient(),
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    asyncio.run(scheduler._probe_runner_liveness())
    assert scheduler._runner_liveness_failures == 1
    assert alerts == []
    asyncio.run(scheduler._probe_runner_liveness())

    assert scheduler._runner_liveness_failures == 2
    assert scheduler._runner_liveness_alerted is True
    assert len(alerts) == 1


def test_runner_probe_clears_failure_state_on_recovery(monkeypatch):
    scheduler._runner_liveness_failures = 2
    scheduler._runner_liveness_alerted = True
    monkeypatch.setattr(
        scheduler.httpx,
        "AsyncClient",
        lambda **_kwargs: _HealthyClient(),
    )

    asyncio.run(scheduler._probe_runner_liveness())

    assert scheduler._runner_liveness_failures == 0
    assert scheduler._runner_liveness_alerted is False


def test_authenticated_api_probe_fails_closed_when_secret_missing(monkeypatch):
    scheduler._trading_api_liveness_failures = 0
    scheduler._trading_api_liveness_alerted = False
    monkeypatch.delenv("TRADING_API_SECRET", raising=False)
    monkeypatch.setattr(
        scheduler.httpx,
        "AsyncClient",
        lambda **_kwargs: _FailingClient(),
    )

    asyncio.run(scheduler._probe_trading_api_liveness())

    assert scheduler._trading_api_liveness_failures == 1
    assert scheduler._trading_api_liveness_alerted is False


def test_authenticated_api_probe_recovers_with_secret(monkeypatch):
    scheduler._trading_api_liveness_failures = 1
    scheduler._trading_api_liveness_alerted = True
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setattr(
        scheduler.httpx,
        "AsyncClient",
        lambda **_kwargs: _ApiClient(),
    )

    asyncio.run(scheduler._probe_trading_api_liveness())

    assert scheduler._trading_api_liveness_failures == 0
    assert scheduler._trading_api_liveness_alerted is False


def test_authenticated_api_probe_sends_secret_header_without_logging_value(monkeypatch):
    client = _CapturingApiClient()
    scheduler._trading_api_liveness_failures = 0
    scheduler._trading_api_liveness_alerted = False
    monkeypatch.setenv("TRADING_API_SECRET", "test-api-secret")
    monkeypatch.setattr(scheduler.httpx, "AsyncClient", lambda **_kwargs: client)

    asyncio.run(scheduler._probe_trading_api_liveness())

    assert client.request_headers == {
        "X-Trading-API-Secret": "test-api-secret",
        "User-Agent": "trading-api-authenticated-liveness",
    }
    assert scheduler._trading_api_liveness_failures == 0


def test_authenticated_api_probe_is_registered_when_published_flag_is_enabled(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("TRADING_API_LIVENESS_ENABLED", "1")
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    job_ids = {job["id"] for job in recording_scheduler.jobs}
    assert "published_trading_api_liveness" in job_ids