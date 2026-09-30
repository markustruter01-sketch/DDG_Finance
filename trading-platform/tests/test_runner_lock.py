from __future__ import annotations

import sys
from datetime import datetime, timezone
from threading import Event
from unittest.mock import MagicMock, patch

from core import runner_lock


def _fake_conn():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    def execute(query, params=None):
        expected = str(query).count("%s")
        actual = len(params) if params is not None else 0
        if expected != actual:
            raise AssertionError(
                f"SQL placeholder count {expected} does not match parameter count {actual}"
            )

    cursor.execute.side_effect = execute
    return conn, cursor


def test_claim_returns_owned_row():
    conn, cursor = _fake_conn()
    cursor.fetchone.side_effect = [
        None,
        (
            "oracle",
            "published",
            101,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            "runner-a",
        ),
    ]
    with patch("db.postgres.is_pg_available", return_value=True), patch(
        "db.postgres.get_conn"
    ) as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock("oracle", "published", 101, 10800)

    assert result["owned"] is True
    assert result["lock"]["environment"] == "published"


def test_fresh_other_environment_is_refused():
    conn, cursor = _fake_conn()
    cursor.fetchone.return_value = (
        "oracle",
        "published",
        101,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc),
        "runner-a",
    )
    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock("oracle", "dev", 202, 10800)

    assert result["owned"] is False
    assert result["lock"]["environment"] == "published"


def _lock_row(
    *,
    heartbeat_at,
    environment="published",
    pid=101,
    token="runner-a",
    boot_id=None,
    start_time_ticks=None,
):
    return (
        "oracle",
        environment,
        pid,
        heartbeat_at,
        heartbeat_at,
        token,
        boot_id,
        start_time_ticks,
    )


def test_stale_dead_owner_is_taken_over(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        pid=101,
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=202,
        token="runner-b",
    )
    cursor.fetchone.side_effect = [old, replacement]
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: False)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 202, 10800, owner_token="runner-b"
        )

    assert result["owned"] is True
    assert result["lock"]["pid"] == 202


def test_same_environment_dead_pid_is_reclaimed_even_when_fresh(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=101,
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=202,
        token="runner-b",
    )
    cursor.fetchone.side_effect = [old, replacement]
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: False)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 202, 10800, owner_token="runner-b"
        )

    assert result["owned"] is True


def test_live_competing_owner_is_never_displaced(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=101,
    )
    cursor.fetchone.return_value = old
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 202, 10800, owner_token="runner-b"
        )

    assert result["owned"] is False
    assert result["lock"]["pid"] == 101


def test_remote_holder_with_recent_runner_heartbeat_is_refused(monkeypatch):
    conn, cursor = _fake_conn()
    heartbeat_age_seconds = 10
    old = _lock_row(
        heartbeat_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        pid=101,
        token="runner:v2:holder-boot:100:holder",
    )
    cursor.fetchone.side_effect = [
        old,
        (heartbeat_age_seconds <= runner_lock.HOLDER_SILENCE_SECONDS,),
    ]
    monkeypatch.setattr(
        runner_lock,
        "_pid_is_alive",
        lambda _pid: (_ for _ in ()).throw(AssertionError("remote PID checked locally")),
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            202,
            60,
            owner_token="runner:v2:caller-boot:200:caller",
        )

    assert result["owned"] is False
    assert result["decision"] == "remote_runner_heartbeat_fresh"
    assert result["lock"]["pid"] == 101
    heartbeat_query = next(
        call for call in cursor.execute.call_args_list
        if "FROM runner_heartbeat" in str(call.args[0])
    )
    assert "NOW()" in str(heartbeat_query.args[0])
    assert heartbeat_query.args[1] == (
        runner_lock.HOLDER_SILENCE_SECONDS,
        "runner:v2:holder-boot:100:holder",
    )


def test_remote_holder_with_stale_runner_heartbeat_is_taken_over(monkeypatch):
    conn, cursor = _fake_conn()
    heartbeat_age_seconds = 120
    old = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=101,
        token="runner:v2:holder-boot:100:holder",
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=202,
        token="runner:v2:caller-boot:200:caller",
    )
    cursor.fetchone.side_effect = [
        old,
        (heartbeat_age_seconds <= runner_lock.HOLDER_SILENCE_SECONDS,),
        replacement,
    ]
    monkeypatch.setattr(
        runner_lock,
        "_pid_is_alive",
        lambda _pid: (_ for _ in ()).throw(AssertionError("remote PID checked locally")),
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            202,
            10800,
            owner_token="runner:v2:caller-boot:200:caller",
        )

    assert result["owned"] is True
    assert result["decision"] == "remote_runner_heartbeat_stale"
    assert result["lock"]["pid"] == 202


def test_remote_holder_without_heartbeat_and_fresh_lease_is_refused(monkeypatch):
    conn, cursor = _fake_conn()
    current = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=101,
        token="runner:v2:holder-boot:100:holder",
    )
    cursor.fetchone.side_effect = [current, None]
    monkeypatch.setattr(
        runner_lock,
        "_pid_is_alive",
        lambda _pid: (_ for _ in ()).throw(AssertionError("remote PID checked locally")),
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            202,
            10800,
            owner_token="runner:v2:caller-boot:200:caller",
        )

    assert result["owned"] is False
    assert result["decision"] == "remote_runner_heartbeat_missing_or_unreadable"
    assert result["lock"]["pid"] == 101


def test_remote_holder_heartbeat_read_failure_is_fail_closed(monkeypatch):
    conn, cursor = _fake_conn()
    current = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=101,
        token="runner:v2:holder-boot:100:holder",
    )
    cursor.fetchone.return_value = current
    check_placeholders = cursor.execute.side_effect

    def fail_heartbeat_read(query, params=None):
        check_placeholders(query, params)
        if "FROM runner_heartbeat" in str(query):
            raise RuntimeError("runner heartbeat table unavailable")

    cursor.execute.side_effect = fail_heartbeat_read
    monkeypatch.setattr(
        runner_lock,
        "_pid_is_alive",
        lambda _pid: (_ for _ in ()).throw(AssertionError("remote PID checked locally")),
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            202,
            10800,
            owner_token="runner:v2:caller-boot:200:caller",
        )

    assert result["owned"] is False
    assert result["decision"] == "remote_runner_heartbeat_missing_or_unreadable"
    assert result["lock"]["pid"] == 101


def test_remote_holder_without_heartbeat_and_stale_lease_is_taken_over(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        pid=101,
        token="runner:v2:holder-boot:100:holder",
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=202,
        token="runner:v2:caller-boot:200:caller",
    )
    cursor.fetchone.side_effect = [old, None, replacement]
    monkeypatch.setattr(
        runner_lock,
        "_pid_is_alive",
        lambda _pid: (_ for _ in ()).throw(AssertionError("remote PID checked locally")),
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            202,
            10800,
            owner_token="runner:v2:caller-boot:200:caller",
        )

    assert result["owned"] is True
    assert result["decision"] == "stale_lease_process_identity_mismatch"
    assert result["lock"]["pid"] == 202


def test_missing_lease_row_is_claimed_with_decision():
    conn, cursor = _fake_conn()
    inserted = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        pid=202,
        token="runner-b",
    )
    cursor.fetchone.side_effect = [None, inserted]

    with patch("db.postgres.is_pg_available", return_value=True), patch(
        "db.postgres.get_conn"
    ) as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 202, 10800, owner_token="runner-b"
        )

    assert result["owned"] is True
    assert result["decision"] == "no_existing_lease"


def test_same_process_instance_can_refresh_stale_lease(monkeypatch):
    conn, cursor = _fake_conn()
    current = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        environment="published",
        pid=101,
        token="runner-a",
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=101,
        token="runner-a",
    )
    cursor.fetchone.side_effect = [current, replacement]
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 101, 60, owner_token="runner-a"
        )

    assert result["owned"] is True


def test_replacement_with_reused_pid_is_taken_over_by_new_token(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        environment="published",
        pid=22,
        token="runner:v2:boot-a:100:old-process",
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=22,
        token="runner:v2:boot-a:200:new-process",
    )
    cursor.fetchone.side_effect = [old, replacement]
    monkeypatch.setattr(
        runner_lock,
        "_read_process_identity",
        lambda _pid: {"boot_id": "boot-a", "start_time_ticks": 200},
    )
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            22,
            10800,
            owner_token="runner:v2:boot-a:200:new-process",
        )

    assert result["owned"] is True
    assert result["lock"]["pid"] == 22
    assert result["lock"]["owner_token"] == "runner:v2:boot-a:200:new-process"


def test_stale_legacy_published_lease_is_taken_over_with_different_pid(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        environment="published",
        pid=22,
        token="legacy:published:22:1787874045",
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=23,
        token="new-process-token",
    )
    cursor.fetchone.side_effect = [old, replacement]
    # The stale legacy PID can belong to another published artifact process.
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            23,
            10800,
            owner_token="runner:v2:boot-a:200:new-process",
        )

    assert result["owned"] is True
    assert result["lock"]["pid"] == 23
    assert result["lock"]["owner_token"] == "new-process-token"


def test_stale_reused_pid_with_identity_mismatch_is_taken_over(monkeypatch):
    conn, cursor = _fake_conn()
    old = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        environment="published",
        pid=22,
        token="runner:v2:boot-a:100:old-process",
        boot_id="boot-a",
        start_time_ticks=100,
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=23,
        token="runner:v2:boot-a:200:new-process",
        boot_id="boot-a",
        start_time_ticks=200,
    )
    cursor.fetchone.side_effect = [old, replacement]
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)
    monkeypatch.setattr(
        runner_lock,
        "_read_process_identity",
        lambda _pid: {"boot_id": "boot-a", "start_time_ticks": 200},
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            23,
            10800,
            owner_token="runner:v2:boot-a:200:new-process",
        )

    assert result["owned"] is True
    assert result["lock"]["pid"] == 23
    assert result["lock"]["owner_token"] == "runner:v2:boot-a:200:new-process"


def test_stale_owner_with_matching_identity_is_refused(monkeypatch):
    conn, cursor = _fake_conn()
    current = _lock_row(
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        environment="published",
        pid=101,
        token="runner:v2:boot-a:100:old-process",
        boot_id="boot-a",
        start_time_ticks=100,
    )
    cursor.fetchone.return_value = current
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)
    monkeypatch.setattr(
        runner_lock,
        "_read_process_identity",
        lambda _pid: {"boot_id": "boot-a", "start_time_ticks": 100},
    )

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle",
            "published",
            101,
            10800,
            owner_token="runner:v2:boot-a:100:new-process",
        )

    assert result["owned"] is False
    assert result["lock"]["owner_token"] == "runner:v2:boot-a:100:old-process"


def test_fresh_legacy_published_lease_is_refused(monkeypatch):
    conn, cursor = _fake_conn()
    current = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=22,
        token="legacy:published:22:1787874045",
    )
    cursor.fetchone.return_value = current
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 23, 10800, owner_token="new-process-token"
        )

    assert result["owned"] is False
    assert result["lock"]["owner_token"] == "legacy:published:22:1787874045"


def test_runner_shutdown_release_is_scoped_to_instance_token(monkeypatch):
    sys.path.insert(0, "/home/runner/workspace/kraken-bot")
    import runner

    calls = []
    monkeypatch.setattr(runner, "_runner_lock_ready", True)
    monkeypatch.setattr(
        runner,
        "_release_runner_locks",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 3,
    )
    runner._owned_lock_bot_ids.update({"oracle", "jerome_macro", "spy_qqq_trend"})

    runner._release_owned_runner_locks()

    assert calls == [
        (
            (runner.RUNNER_ENVIRONMENT, runner.os.getpid()),
            {"owner_token": runner.RUNNER_OWNER_TOKEN},
        )
    ]
    assert not runner._owned_lock_bot_ids


def test_read_only_runner_preparation_does_not_claim_leases(monkeypatch):
    sys.path.insert(0, "/home/runner/workspace/kraken-bot")
    import runner

    monkeypatch.setattr(runner, "_runner_can_trade", False)
    monkeypatch.setattr(runner, "RUNNER_EXECUTION_MODE", "read_only")
    monkeypatch.setattr(runner, "_ensure_runner_lock_table", lambda: True)
    monkeypatch.setattr(runner, "_log_runner_locks", lambda _prefix: None)
    monkeypatch.setattr(
        runner,
        "_claim_runner_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read-only runner claimed a lease")
        ),
    )

    assert runner._prepare_runner_locks() is True


def test_live_runner_exits_nonzero_when_lease_preparation_fails(monkeypatch):
    sys.path.insert(0, "/home/runner/workspace/kraken-bot")
    import runner

    alerts = []
    monkeypatch.setattr(runner, "_runner_can_trade", True)
    monkeypatch.setattr(runner, "RUNNER_ENVIRONMENT", "published")
    monkeypatch.setattr(runner, "RUNNER_EXECUTION_MODE", "live")
    monkeypatch.setattr(runner, "_runner_lock_ready", False)
    monkeypatch.setattr(runner, "_shutdown_event", Event())
    monkeypatch.setattr(runner, "_prepare_runner_locks", lambda: False)
    monkeypatch.setattr(
        runner,
        "_runner_lock_failure_reason",
        "lease refused for oracle",
    )
    monkeypatch.setattr(
        runner,
        "_list_runner_locks",
        lambda: [{
            "bot_id": "oracle",
            "environment": "published",
            "pid": 22,
            "owner_token": "old-token",
            "heartbeat_at": "2026-09-01T02:42:00+00:00",
        }],
    )
    monkeypatch.setattr(
        "notifications.discord.alert_critical",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )
    start_health = MagicMock()
    monkeypatch.setattr(runner, "_start_health_server", start_health)

    assert runner.main() == runner.EXIT_REFUSAL
    assert alerts
    assert start_health.call_count == 0