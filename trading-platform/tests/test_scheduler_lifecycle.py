from __future__ import annotations

from unittest.mock import Mock

import pytest

import main


def test_workspace_environment_disables_scheduler_without_registering_jobs(
    monkeypatch,
):
    monkeypatch.delenv("RUNNER_ENVIRONMENT", raising=False)
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    scheduler_factory = Mock()
    monkeypatch.setattr(main, "get_scheduler", scheduler_factory)
    info_messages: list[str] = []
    monkeypatch.setattr(
        main,
        "logger",
        Mock(info=info_messages.append),
    )

    assert main._scheduler_enabled_for_current_environment() is False
    assert main._start_scheduler(False) is None
    main._add_scheduler_job(None, id="must_not_register")
    main._register_yahoo_refresh_jobs(None)

    scheduler_factory.assert_not_called()
    assert info_messages == ["scheduler disabled (workspace)"]


def test_published_environment_starts_the_existing_scheduler_and_keeps_job_path(
    monkeypatch,
):
    monkeypatch.delenv("RUNNER_ENVIRONMENT", raising=False)
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    scheduler = Mock()
    scheduler.get_jobs.return_value = ["existing-job-a", "existing-job-b"]
    scheduler_factory = Mock(return_value=scheduler)
    monkeypatch.setattr(main, "get_scheduler", scheduler_factory)

    assert main._scheduler_enabled_for_current_environment() is True
    assert main._start_scheduler(True) is scheduler
    main._add_scheduler_job(scheduler, id="existing-main-lifespan-job")

    scheduler_factory.assert_called_once_with()
    scheduler.start.assert_called_once_with()
    scheduler.add_job.assert_called_once_with(id="existing-main-lifespan-job")


def test_unknown_runner_environment_fails_closed_before_scheduler_creation(
    monkeypatch,
):
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "unknown")
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    scheduler_factory = Mock()
    monkeypatch.setattr(main, "get_scheduler", scheduler_factory)

    with pytest.raises(RuntimeError, match="Unknown RUNNER_ENVIRONMENT='unknown'"):
        main._scheduler_enabled_for_current_environment()

    scheduler_factory.assert_not_called()