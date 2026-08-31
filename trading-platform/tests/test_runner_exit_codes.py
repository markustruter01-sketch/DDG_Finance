from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def runner_module():
    path = Path(__file__).parents[2] / "kraken-bot" / "runner.py"
    spec = importlib.util.spec_from_file_location("test_runner_exit_code_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_deliberate_lease_refusal_returns_refusal_code(runner_module, monkeypatch):
    monkeypatch.setattr(runner_module, "_runner_can_trade", True)
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: False)
    monkeypatch.setattr(
        runner_module,
        "_runner_lock_failure_reason",
        "lease refused by another live runner",
    )

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    runner_module._shutdown_event.clear()


def test_uncaught_startup_failure_returns_crash_code(runner_module, monkeypatch):
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: True)
    monkeypatch.setattr(
        runner_module,
        "_assert_pause_alignment",
        lambda: (_ for _ in ()).throw(RuntimeError("startup boom")),
    )

    assert runner_module.main() == runner_module.EXIT_CRASH
    runner_module._shutdown_event.clear()


def _configure_refusal(
    runner_module,
    monkeypatch,
    *,
    environment: str,
    rows: list[dict],
    detail: dict,
):
    monkeypatch.setattr(runner_module, "_runner_can_trade", True)
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", environment)
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: False)
    monkeypatch.setattr(
        runner_module,
        "_runner_lock_failure_reason",
        "claim returned owned=False for oracle; refusal_cause=occupied_lease",
    )
    monkeypatch.setattr(runner_module, "_runner_lock_failure_detail", detail)
    monkeypatch.setattr(runner_module, "_list_runner_locks", lambda: rows)
    monkeypatch.setattr(runner_module, "_runner_lock_import_ok", True)
    monkeypatch.setattr(runner_module, "_shutdown_event", __import__("threading").Event())


def test_published_refusal_sends_alert_with_claim_lease_row(runner_module, monkeypatch):
    row = {
        "bot_id": "oracle",
        "environment": "published",
        "pid": 4242,
        "owner_token": "runner:v2:boot:42:nonce",
        "heartbeat_at": "2026-09-01T02:42:00+00:00",
    }
    alerts = []
    _configure_refusal(
        runner_module,
        monkeypatch,
        environment="published",
        rows=[],
        detail={
            "cause": "occupied_lease",
            "claim_result": {"owned": False, "lock": row},
        },
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    assert len(alerts) == 1
    field_value = alerts[0][1]["fields"][0]["value"]
    assert '"bot_id": "oracle"' in field_value
    assert '"environment": "published"' in field_value
    assert '"heartbeat_age_seconds"' in field_value
    assert "[]" not in field_value


def test_dev_refusal_logs_but_does_not_send_alert(runner_module, monkeypatch):
    row = {
        "bot_id": "oracle",
        "environment": "published",
        "pid": 4242,
        "owner_token": "runner:v2:boot:42:nonce",
        "heartbeat_at": "2026-09-01T02:42:00+00:00",
    }
    sends = []
    critical_logs = []
    _configure_refusal(
        runner_module,
        monkeypatch,
        environment="dev",
        rows=[row],
        detail={
            "cause": "occupied_lease",
            "claim_result": {"owned": False, "lock": row},
        },
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: sends.append((args, kwargs)),
    )
    monkeypatch.setattr(
        runner_module.logger,
        "critical",
        lambda message, *args, **kwargs: critical_logs.append(str(message)),
    )

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    assert sends == []
    assert any("LIVE STARTUP ABORTED" in message for message in critical_logs)
    assert any("lease_evidence" in message for message in critical_logs)


def test_refusal_alert_never_reports_empty_list_when_evidence_unreadable(
    runner_module, monkeypatch
):
    alerts = []
    _configure_refusal(
        runner_module,
        monkeypatch,
        environment="published",
        rows=[],
        detail={
            "cause": "claim_exception",
            "error": "database connection dropped",
            "claim_result": None,
        },
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    field_value = alerts[0][1]["fields"][0]["value"]
    assert "lease rows unreadable" in field_value
    assert "[]" not in field_value
