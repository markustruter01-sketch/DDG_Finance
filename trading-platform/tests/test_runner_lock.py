from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from core import runner_lock


def _fake_conn():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
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


def _lock_row(*, heartbeat_at, environment="published", pid=101, token="runner-a"):
    return ("oracle", environment, pid, heartbeat_at, heartbeat_at, token)


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
        heartbeat_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
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
        token="legacy:published:22:1787873030",
    )
    replacement = _lock_row(
        heartbeat_at=datetime.now(timezone.utc),
        environment="published",
        pid=22,
        token="new-process-token",
    )
    cursor.fetchone.side_effect = [old, replacement]
    # The PID is visible because it is the replacement process itself.
    monkeypatch.setattr(runner_lock, "_pid_is_alive", lambda _pid: True)

    with patch("db.postgres.get_conn") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        result = runner_lock.claim_lock(
            "oracle", "published", 22, 10800, owner_token="new-process-token"
        )

    assert result["owned"] is True
    assert result["lock"]["pid"] == 22
    assert result["lock"]["owner_token"] == "new-process-token"


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