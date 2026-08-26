from __future__ import annotations

import asyncio

from core import scheduler


class _Response:
    status_code = 200

    def json(self):
        return {"service": "kraken-bot-runner"}


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