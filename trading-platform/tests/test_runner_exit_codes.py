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
    monkeypatch.setattr(runner_module, "_runner_lock_ready", False)
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
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[False, False, False, True],
    )
    monkeypatch.setattr(runner_module, "LEASE_WAIT_RETRY_SECONDS", 1)
    monkeypatch.setattr(runner_module, "LEASE_WAIT_ALERT_SECONDS", 2)

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert len(alerts) == 1
    field_value = alerts[0][1]["fields"][0]["value"]
    assert '"bot_id": "oracle"' in field_value
    assert '"environment": "published"' in field_value
    assert '"heartbeat_age_seconds"' in field_value
    assert "[]" not in field_value
    assert not harness["bot_thread_starts"]
    assert harness["heartbeat_statuses"].count("awaiting_leases") >= 1
    assert sum(event[0] == "health_server" for event in harness["events"]) == 1
    assert harness["clock"].seconds > runner_module.LEASE_WAIT_ALERT_SECONDS


def test_successful_first_claim_starts_server_and_bots_once(runner_module, monkeypatch):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[True],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    claims = []

    def claim_once():
        claims.append("claim")
        harness["events"].append(("claim",))
        runner_module._runner_lock_ready = True
        return True

    monkeypatch.setattr(runner_module, "_prepare_runner_locks", claim_once)

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert claims == ["claim"]
    assert harness["heartbeat_statuses"][0] == "starting"
    assert "awaiting_leases" not in harness["heartbeat_statuses"]
    assert harness["bot_thread_starts"] == ["bot-oracle"]
    assert sum(event[0] == "health_server" for event in harness["events"]) == 1
    assert harness["events"].index(("claim",)) < harness["events"].index(
        ("health_server",)
    )


def test_published_occupied_twice_then_free_waits_before_starting_bots(
    runner_module, monkeypatch
):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[False, False, True],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    monkeypatch.setattr(runner_module, "LEASE_WAIT_RETRY_SECONDS", 1)
    claim_count = 0
    waiting_logs = harness["waiting_logs"]

    def claim_until_free():
        nonlocal claim_count
        claim_count += 1
        harness["events"].append(("claim", claim_count))
        if claim_count < 3:
            _set_lock_failure(
                runner_module,
                monkeypatch,
                cause="occupied_lease",
                holder_environment="published",
                decision="remote_runner_heartbeat_fresh",
            )
            return False
        runner_module._runner_lock_ready = True
        harness["events"].append(("claim_succeeded", claim_count))
        return True

    monkeypatch.setattr(runner_module, "_prepare_runner_locks", claim_until_free)

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert claim_count == 3
    assert harness["heartbeat_statuses"].count("awaiting_leases") == 2
    assert "decision=remote_runner_heartbeat_fresh" in " ".join(waiting_logs)
    assert harness["events"].index(("claim", 1)) < harness["events"].index(
        ("health_server",)
    )
    successful_claim_index = harness["events"].index(("claim_succeeded", 3))
    first_bot_index = next(
        index
        for index, event in enumerate(harness["events"])
        if event[0] == "thread_started" and event[1].startswith("bot-")
    )
    assert successful_claim_index < first_bot_index
    assert not any(
        event[0] == "thread_started" and event[1].startswith("bot-")
        for event in harness["events"][:successful_claim_index]
    )
    assert sum(event[0] == "health_server" for event in harness["events"]) == 1


def test_published_lease_wait_continues_through_database_failure(
    runner_module, monkeypatch
):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[False, False, True],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    monkeypatch.setattr(runner_module, "LEASE_WAIT_RETRY_SECONDS", 1)
    claim_count = 0

    def fail_then_claim():
        nonlocal claim_count
        claim_count += 1
        if claim_count == 1:
            _set_lock_failure(
                runner_module,
                monkeypatch,
                cause="occupied_lease",
                holder_environment="published",
            )
            return False
        if claim_count == 2:
            _set_lock_failure(
                runner_module,
                monkeypatch,
                cause="postgresql_unavailable",
                holder_environment=None,
                decision="database_unavailable",
            )
            return False
        runner_module._runner_lock_ready = True
        return True

    monkeypatch.setattr(runner_module, "_prepare_runner_locks", fail_then_claim)

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert claim_count == 3
    assert any(
        "cause=postgresql_unavailable" in message
        for message in harness["waiting_logs"]
    )
    assert harness["bot_thread_starts"] == ["bot-oracle"]
    assert harness["heartbeat_statuses"].count("awaiting_leases") == 2


def test_shutdown_while_waiting_exits_successfully_without_bot_threads(
    runner_module, monkeypatch
):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[True],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    claim_calls = []

    def occupied():
        claim_calls.append("claim")
        _set_lock_failure(
            runner_module,
            monkeypatch,
            cause="occupied_lease",
            holder_environment="published",
        )
        return False

    monkeypatch.setattr(runner_module, "_prepare_runner_locks", occupied)

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert claim_calls == ["claim"]
    assert harness["heartbeat_statuses"] == ["starting", "awaiting_leases"]
    assert not harness["bot_thread_starts"]
    assert sum(event[0] == "health_server" for event in harness["events"]) == 1


def test_shutdown_during_successful_retry_does_not_start_bot_threads(
    runner_module, monkeypatch
):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[False],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    claim_count = 0

    def signal_shutdown_on_successful_retry():
        nonlocal claim_count
        claim_count += 1
        if claim_count == 1:
            _set_lock_failure(
                runner_module,
                monkeypatch,
                cause="occupied_lease",
                holder_environment="published",
            )
            return False
        harness["event"].set()
        runner_module._runner_lock_ready = True
        return True

    monkeypatch.setattr(
        runner_module,
        "_prepare_runner_locks",
        signal_shutdown_on_successful_retry,
    )

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert claim_count == 2
    assert not harness["bot_thread_starts"]
    assert harness["heartbeat_statuses"] == ["starting", "awaiting_leases"]
    assert sum(event[0] == "health_server" for event in harness["events"]) == 1


def test_published_runner_does_not_wait_for_dev_holder(
    runner_module, monkeypatch
):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[True],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    alerts = []
    _set_lock_failure(
        runner_module,
        monkeypatch,
        cause="occupied_lease",
        holder_environment="dev",
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: False)

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    assert len(alerts) == 1
    assert not harness["bot_thread_starts"]
    assert not any(event[0] == "health_server" for event in harness["events"])
    assert harness["event"].wait_calls == []


def test_published_non_occupied_failure_aborts_without_health_server(
    runner_module, monkeypatch
):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[True],
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "published")
    alerts = []
    _set_lock_failure(
        runner_module,
        monkeypatch,
        cause="postgresql_unavailable",
        holder_environment=None,
        decision="database_unavailable",
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )
    monkeypatch.setattr(runner_module, "_prepare_runner_locks", lambda: False)

    assert runner_module.main() == runner_module.EXIT_REFUSAL
    assert len(alerts) == 1
    assert not harness["bot_thread_starts"]
    assert not any(event[0] == "health_server" for event in harness["events"])
    assert harness["event"].wait_calls == []


def test_read_only_runner_skips_lease_waiting(runner_module, monkeypatch):
    harness = _configure_main_harness(
        runner_module,
        monkeypatch,
        wait_results=[True],
        live=False,
    )
    monkeypatch.setattr(runner_module, "RUNNER_ENVIRONMENT", "dev")
    claims = []
    monkeypatch.setattr(
        runner_module,
        "_prepare_runner_locks",
        lambda: claims.append("prepare") or True,
    )

    assert runner_module.main() == runner_module.EXIT_SUCCESS
    assert claims == ["prepare"]
    assert "awaiting_leases" not in harness["heartbeat_statuses"]
    assert harness["bot_thread_starts"] == ["bot-oracle"]
    assert sum(event[0] == "health_server" for event in harness["events"]) == 1


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
