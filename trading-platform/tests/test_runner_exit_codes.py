from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def runner_module():
    path = Path(__file__).parents[2] / "kraken-bot" / "runner.py"
    spec = importlib.util.spec_from_file_location("test_runner_exit_code_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_runner_heartbeat_during_main_tests(runner_module, monkeypatch):
    monkeypatch.setattr(
        runner_module,
        "_record_runner_heartbeat",
        lambda *_args, **_kwargs: True,
    )


class _FakeClock:
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += float(seconds)


class _ScriptedEvent:
    def __init__(self, clock, wait_results):
        self.clock = clock
        self.wait_results = list(wait_results)
        self.wait_calls = []
        self._is_set = False

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        should_stop = self.wait_results.pop(0) if self.wait_results else True
        if should_stop:
            self._is_set = True
        elif timeout is not None:
            self.clock.advance(timeout)
        return should_stop

    def is_set(self):
        return self._is_set

    def set(self):
        self._is_set = True


def _configure_main_harness(
    runner_module,
    monkeypatch,
    *,
    wait_results,
    live=True,
):
    clock = _FakeClock()
    shutdown_event = _ScriptedEvent(clock, wait_results)
    events = []
    heartbeat_statuses = []
    bot_thread_starts = []
    waiting_logs = []

    class RecordingThread:
        def __init__(self, target=None, args=(), daemon=None, name=None, **_kwargs):
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name

        def start(self):
            events.append(("thread_started", self.name))
            if self.name and self.name.startswith("bot-"):
                bot_thread_starts.append(self.name)

        def join(self, timeout=None):
            return None

    def record_heartbeat(loop_count, status):
        heartbeat_statuses.append(status)
        events.append(("heartbeat", status))
        return True

    monkeypatch.setattr(
        runner_module,
        "threading",
        SimpleNamespace(Thread=RecordingThread),
    )
    monkeypatch.setattr(
        runner_module,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, sleep=lambda _seconds: None),
    )
    monkeypatch.setattr(runner_module, "_shutdown_event", shutdown_event)
    monkeypatch.setattr(runner_module, "_runner_can_trade", live)
    monkeypatch.setattr(
        runner_module,
        "RUNNER_EXECUTION_MODE",
        "live" if live else "read_only",
    )
    monkeypatch.setattr(runner_module, "_record_runner_heartbeat", record_heartbeat)
    monkeypatch.setattr(
        runner_module,
        "_start_health_server",
        lambda: events.append(("health_server",)),
    )
    monkeypatch.setattr(runner_module, "_probe_trading_api", lambda: None)
    monkeypatch.setattr(runner_module, "_assert_pause_alignment", lambda: True)
    monkeypatch.setattr(runner_module, "_update_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module, "_run_bot_loop", lambda *_args: None)
    monkeypatch.setattr(runner_module, "_release_owned_runner_locks", lambda: None)
    monkeypatch.setattr(
        runner_module,
        "_lease_refusal_evidence",
        lambda: ([], "test evidence unavailable"),
    )
    monkeypatch.setattr(runner_module, "BOTS", [("oracle", "test_strategy", "run")])
    monkeypatch.setattr(runner_module, "_RUNNER_LOOP_INTERVAL_SECONDS", 1)
    monkeypatch.setattr(runner_module, "LEASE_WAIT_RETRY_SECONDS", 1)
    monkeypatch.setattr(runner_module.logger, "warning", waiting_logs.append)
    return {
        "clock": clock,
        "event": shutdown_event,
        "events": events,
        "heartbeat_statuses": heartbeat_statuses,
        "bot_thread_starts": bot_thread_starts,
        "waiting_logs": waiting_logs,
    }


def _set_lock_failure(
    runner_module,
    monkeypatch,
    *,
    cause,
    holder_environment="published",
    decision="remote_runner_heartbeat_fresh",
):
    claim_result = {
        "owned": False,
        "decision": decision,
    }
    if holder_environment is not None:
        claim_result["lock"] = {
            "bot_id": "oracle",
            "environment": holder_environment,
            "pid": 4242,
            "owner_token": "runner:v2:published-boot:42:holder",
            "heartbeat_at": "2026-09-30T00:00:00+00:00",
        }
    monkeypatch.setattr(
        runner_module,
        "_runner_lock_failure_reason",
        f"claim refused; cause={cause}",
    )
    monkeypatch.setattr(
        runner_module,
        "_runner_lock_failure_detail",
        {
            "cause": cause,
            "bot_id": "oracle",
            "claim_result": claim_result,
        },
    )
    monkeypatch.setattr(runner_module, "_runner_lock_ready", False)


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
