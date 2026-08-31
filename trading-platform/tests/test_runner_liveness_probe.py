from __future__ import annotations

import asyncio

import pytest

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


@pytest.fixture(autouse=True)
def _configured_runner_url(monkeypatch):
    monkeypatch.delenv("RUNNER_HEALTH_URL", raising=False)
    monkeypatch.delenv("RUNNER_HEALTH_ALLOWED_HOST", raising=False)
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_URL",
        "https://runner.example.test/health",
    )
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_ALLOWED_HOST",
        "runner.example.test",
    )


@pytest.fixture(autouse=True)
def _capture_runner_audit(monkeypatch):
    records = []
    monkeypatch.setattr(
        scheduler,
        "_record_runner_liveness_audit",
        lambda result, **kwargs: records.append({"result": result, **kwargs}),
    )
    return records


def test_runner_probe_alerts_after_threshold(monkeypatch, _capture_runner_audit):
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
    assert [record["alert_transition"] for record in _capture_runner_audit] == [
        "none",
        "raised",
    ]
    assert all(record["result"] == "unreachable" for record in _capture_runner_audit)
    assert all(record["error_class"] == "TimeoutError" for record in _capture_runner_audit)


def test_runner_probe_clears_failure_state_on_recovery(monkeypatch, _capture_runner_audit):
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
    assert _capture_runner_audit == [
        {
            "result": "healthy",
            "endpoint_url": "https://runner.example.test/health",
            "error_class": None,
            "reason": None,
            "consecutive_failures": 0,
            "alert_transition": "recovered",
        }
    ]


def test_runner_probe_records_unreachable_failure(monkeypatch, _capture_runner_audit):
    scheduler._runner_liveness_failures = 0
    scheduler._runner_liveness_alerted = False
    monkeypatch.setattr(
        scheduler.httpx,
        "AsyncClient",
        lambda **_kwargs: _FailingClient(),
    )

    asyncio.run(scheduler._probe_runner_liveness())

    assert _capture_runner_audit == [
        {
            "result": "unreachable",
            "endpoint_url": "https://runner.example.test/health",
            "error_class": "TimeoutError",
            "reason": None,
            "consecutive_failures": 1,
            "alert_transition": "none",
        }
    ]


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
        "X-Trading-API-Internal-Secret": "test-api-secret",
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


def test_runner_probe_is_registered_with_explicit_published_monitoring(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("TRADING_API_LIVENESS_ENABLED", "1")
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    job_ids = {job["id"] for job in recording_scheduler.jobs}
    assert "published_runner_liveness" in job_ids


def test_runner_probe_is_not_registered_for_loopback_endpoint(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("TRADING_API_LIVENESS_ENABLED", "1")
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_URL",
        "https://127.0.0.2/health",
    )
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_ALLOWED_HOST",
        "127.0.0.2",
    )
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    job_ids = {job["id"] for job in recording_scheduler.jobs}
    assert "published_runner_liveness" not in job_ids
    assert "published_trading_api_liveness" in job_ids


def test_runner_probe_is_not_registered_for_unlisted_host(
    monkeypatch, _capture_runner_audit
):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("TRADING_API_LIVENESS_ENABLED", "1")
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_URL",
        "https://unexpected.example.test/health",
    )
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    job_ids = {job["id"] for job in recording_scheduler.jobs}
    assert "published_runner_liveness" not in job_ids
    assert _capture_runner_audit == [
        {
            "result": "invalid_endpoint",
            "endpoint_url": None,
            "error_class": "InvalidRunnerHealthEndpoint",
            "reason": (
                "runner liveness monitoring skipped because endpoint configuration "
                "is invalid"
            ),
            "consecutive_failures": 0,
            "alert_transition": "none",
        }
    ]


def test_runner_probe_records_skipped_monitoring_when_not_enabled(
    monkeypatch, _capture_runner_audit
):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.delenv("TRADING_API_LIVENESS_ENABLED", raising=False)
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    assert _capture_runner_audit[0] == {
        "result": "skipped",
        "endpoint_url": None,
        "error_class": "MonitoringDisabled",
        "reason": "published runner liveness monitoring is not enabled",
        "consecutive_failures": 0,
        "alert_transition": "none",
    }


def test_trusted_local_runner_endpoint_is_registered(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("TRADING_API_LIVENESS_ENABLED", "1")
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_URL",
        scheduler.TRUSTED_LOCAL_RUNNER_HEALTH_URL,
    )
    monkeypatch.setattr(scheduler, "RUNNER_HEALTH_ALLOWED_HOST", "")
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    job_ids = {job["id"] for job in recording_scheduler.jobs}
    assert "published_runner_liveness" in job_ids


def test_malformed_runner_port_does_not_crash_registration(monkeypatch):
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("TRADING_API_LIVENESS_ENABLED", "1")
    monkeypatch.setattr(
        scheduler,
        "RUNNER_HEALTH_URL",
        "https://runner.example.test:99999/health",
    )
    recording_scheduler = _RecordingScheduler()

    scheduler._register_jobs(recording_scheduler)

    job_ids = {job["id"] for job in recording_scheduler.jobs}
    assert "published_runner_liveness" not in job_ids
    assert "published_trading_api_liveness" in job_ids