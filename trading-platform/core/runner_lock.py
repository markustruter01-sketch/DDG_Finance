"""Database-backed runner ownership leases.

The published runner and a development runner can execute the same code against
the same broker accounts.  This module provides a small PostgreSQL lease table
so only one live runner can own each canonical bot at a time.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any


LOCK_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS runner_account_locks (
    bot_id       TEXT PRIMARY KEY,
    environment  TEXT NOT NULL,
    pid          INTEGER NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acquired_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    owner_token  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runner_account_locks_heartbeat
    ON runner_account_locks (heartbeat_at);
"""


def ensure_lock_table() -> bool:
    """Create the lease table, returning False when PostgreSQL is unavailable."""
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(LOCK_TABLE_DDL)
            # Existing deployments predate owner tokens. Backfill deterministically
            # before making the column non-null so a schema upgrade is safe.
            cur.execute(
                """
                ALTER TABLE runner_account_locks
                ADD COLUMN IF NOT EXISTS owner_token TEXT
                """
            )
            cur.execute(
                """
                UPDATE runner_account_locks
                SET owner_token = CONCAT(
                    'legacy:', environment, ':', pid, ':',
                    EXTRACT(EPOCH FROM heartbeat_at)::bigint
                )
                WHERE owner_token IS NULL OR owner_token = ''
                """
            )
            cur.execute(
                """
                ALTER TABLE runner_account_locks
                ALTER COLUMN owner_token SET DEFAULT ''
                """
            )
            cur.execute(
                """
                ALTER TABLE runner_account_locks
                ALTER COLUMN owner_token SET NOT NULL
                """
            )
    return True


def _lock_row(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "bot_id": row[0],
        "environment": row[1],
        "pid": int(row[2]),
        "heartbeat_at": row[3].isoformat() if row[3] else None,
        "acquired_at": row[4].isoformat() if row[4] else None,
        "owner_token": row[5] if len(row) > 5 else None,
    }


def _read_process_identity(pid: int) -> dict[str, str | int | None]:
    """Read the boot ID and kernel start-time ticks for a process.

    Linux exposes both values without requiring ptrace or process cooperation.
    The pair distinguishes a PID that was reused by a later process, including
    reuse inside the same container where os.kill(pid, 0) still succeeds.
    """
    boot_id: str | None = None
    start_time_ticks: int | None = None
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as handle:
            boot_id = handle.read().strip() or None
    except (FileNotFoundError, OSError):
        pass

    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as handle:
            stat_line = handle.read()
        closing_paren = stat_line.rfind(")")
        if closing_paren == -1:
            raise ValueError("malformed process stat")
        # Fields after the command name start at field 3. Field 22
        # (starttime) is therefore index 19 in this suffix.
        stat_fields = stat_line[closing_paren + 2 :].split()
        start_time_ticks = int(stat_fields[19])
    except (FileNotFoundError, OSError, IndexError, TypeError, ValueError):
        pass

    return {
        "boot_id": boot_id,
        "start_time_ticks": start_time_ticks,
    }


def _identity_matches(
    stored_identity: tuple[str | None, int | None],
    requested_identity: dict[str, str | int | None],
) -> bool | None:
    """Return True/False when comparable, otherwise None for unknown."""
    stored_boot_id, stored_start_time = stored_identity
    requested_boot_id = requested_identity.get("boot_id")
    requested_start_time = requested_identity.get("start_time_ticks")
    if (
        not stored_boot_id
        or stored_start_time is None
        or not requested_boot_id
        or requested_start_time is None
    ):
        return None
    return (
        stored_boot_id == requested_boot_id
        and stored_start_time == int(requested_start_time)
    )


def _token_identity(owner_token: str | None) -> tuple[str | None, int | None]:
    """Extract the process identity carried by a v2 owner token."""
    if not owner_token:
        return None, None
    parts = owner_token.split(":", 4)
    if len(parts) != 5 or parts[0] != "runner" or parts[1] != "v2":
        return None, None
    if parts[2] == "unknown" or parts[3] == "unknown":
        return None, None
    try:
        return parts[2], int(parts[3])
    except ValueError:
        return None, None


def make_owner_token(pid: int, nonce: str | None = None) -> str:
    """Create a unique lease token carrying boot and process start identity."""
    identity = _read_process_identity(int(pid))
    boot_id = identity.get("boot_id") or "unknown"
    start_time_ticks = identity.get("start_time_ticks")
    start_value = (
        str(int(start_time_ticks))
        if start_time_ticks is not None
        else "unknown"
    )
    return f"runner:v2:{boot_id}:{start_value}:{nonce or uuid.uuid4().hex}"


def _pid_is_alive(pid: int) -> bool:
    """Return whether this environment can still observe the recorded PID."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but this process cannot signal it.
        return True
    except OSError:
        return False
    return True


def _heartbeat_is_stale(heartbeat_at: Any, stale_after_seconds: float) -> bool:
    if heartbeat_at is None:
        return True
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - heartbeat_at).total_seconds()
    return age_seconds > float(stale_after_seconds)


def list_locks() -> list[dict[str, Any]]:
    """Return all current ownership rows for diagnostics and health output."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bot_id, environment, pid, heartbeat_at, acquired_at, owner_token
                FROM runner_account_locks
                ORDER BY bot_id
                """
            )
            return [
                lock
                for lock in (_lock_row(row) for row in cur.fetchall())
                if lock is not None
            ]


def claim_lock(
    bot_id: str,
    environment: str,
    pid: int,
    stale_after_seconds: float,
    owner_token: str | None = None,
) -> dict[str, Any]:
    """Atomically claim a bot lease, or return the current owner.

    A unique owner token and the process identity distinguish a replacement
    process from a reused PID. Fresh owners are never displaced. A stale lease
    is reclaimable when its stored process identity differs from this caller,
    even if the recorded PID is currently alive.
    """
    from db.postgres import get_conn

    requested_token = owner_token or f"legacy:{environment}:{int(pid)}"
    requested_identity = _token_identity(requested_token)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bot_id, environment, pid, heartbeat_at, acquired_at, owner_token
                FROM runner_account_locks
                WHERE bot_id = %s
                FOR UPDATE
                """,
                (bot_id,),
            )
            current = cur.fetchone()
            if current is None:
                cur.execute(
                    """
                    INSERT INTO runner_account_locks
                        (bot_id, environment, pid, heartbeat_at, acquired_at, owner_token)
                    VALUES (%s, %s, %s, NOW(), NOW(), %s)
                    RETURNING bot_id, environment, pid, heartbeat_at, acquired_at, owner_token
                    """,
                    (
                        bot_id,
                        environment,
                        int(pid),
                        requested_token,
                    ),
                )
                return {"owned": True, "lock": _lock_row(cur.fetchone())}

            current_environment = current[1]
            current_pid = int(current[2])
            current_token = current[5] if len(current) > 5 else ""
            current_token = current_token or ""
            stored_identity = _token_identity(current_token)
            identity = (
                _identity_matches(
                    stored_identity,
                    {
                        "boot_id": requested_identity[0],
                        "start_time_ticks": requested_identity[1],
                    },
                )
                if current_pid == int(pid)
                else False
            )
            stored_identity_present = (
                bool(stored_identity[0])
                and stored_identity[1] is not None
            )
            same_owner = (
                current_environment == environment
                and current_pid == int(pid)
                and (
                    owner_token is None
                    or current_token == requested_token
                )
            )
            owner_alive = _pid_is_alive(current_pid)
            stale = _heartbeat_is_stale(current[3], stale_after_seconds)
            dead_same_environment = (
                current_environment == environment and not owner_alive
            )
            identity_proves_reuse = (
                stale
                and identity is False
                and current_environment == environment
            )
            legacy_identity_unknown_takeover = (
                stale
                and identity is None
                and not stored_identity_present
                and current_environment == environment
            )
            can_takeover = (
                dead_same_environment
                or (stale and not owner_alive)
                or identity_proves_reuse
                or legacy_identity_unknown_takeover
            )

            if same_owner or can_takeover:
                cur.execute(
                    """
                    UPDATE runner_account_locks
                    SET environment = %s,
                        pid = %s,
                        heartbeat_at = NOW(),
                        acquired_at = NOW(),
                        owner_token = %s
                    WHERE bot_id = %s
                    RETURNING bot_id, environment, pid, heartbeat_at, acquired_at, owner_token
                    """,
                    (
                        environment,
                        int(pid),
                        requested_token,
                        bot_id,
                    ),
                )
                return {"owned": True, "lock": _lock_row(cur.fetchone())}

            return {"owned": False, "lock": _lock_row(current)}


def refresh_lock(
    bot_id: str,
    environment: str,
    pid: int,
    owner_token: str | None = None,
) -> bool:
    """Refresh only the lease currently owned by this exact process instance."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            if owner_token:
                cur.execute(
                    """
                    UPDATE runner_account_locks
                    SET heartbeat_at = NOW()
                    WHERE bot_id = %s AND environment = %s
                      AND pid = %s AND owner_token = %s
                    """,
                    (bot_id, environment, int(pid), owner_token),
                )
            else:
                cur.execute(
                    """
                    UPDATE runner_account_locks
                    SET heartbeat_at = NOW()
                    WHERE bot_id = %s AND environment = %s AND pid = %s
                    """,
                    (bot_id, environment, int(pid)),
                )
            return cur.rowcount == 1


def release_locks(
    environment: str,
    pid: int,
    owner_token: str | None = None,
) -> int:
    """Release only leases owned by this exact process instance."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            if owner_token:
                cur.execute(
                    """
                    DELETE FROM runner_account_locks
                    WHERE environment = %s AND pid = %s AND owner_token = %s
                    """,
                    (environment, int(pid), owner_token),
                )
            else:
                cur.execute(
                    """
                    DELETE FROM runner_account_locks
                    WHERE environment = %s AND pid = %s
                    """,
                    (environment, int(pid)),
                )
            return cur.rowcount