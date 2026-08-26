"""Database-backed runner ownership leases.

The published runner and a development runner can execute the same code against
the same broker accounts.  This module provides a small PostgreSQL lease table
so only one live runner can own each canonical bot at a time.
"""
from __future__ import annotations

from typing import Any


LOCK_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS runner_account_locks (
    bot_id        TEXT PRIMARY KEY,
    environment   TEXT NOT NULL,
    pid           INTEGER NOT NULL,
    heartbeat_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acquired_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    }


def list_locks() -> list[dict[str, Any]]:
    """Return all current ownership rows for diagnostics and health output."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bot_id, environment, pid, heartbeat_at, acquired_at
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
) -> dict[str, Any]:
    """Atomically claim a bot lease, or return the fresh current owner."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runner_account_locks
                    (bot_id, environment, pid, heartbeat_at, acquired_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (bot_id) DO UPDATE SET
                    environment  = EXCLUDED.environment,
                    pid          = EXCLUDED.pid,
                    heartbeat_at = EXCLUDED.heartbeat_at,
                    acquired_at  = EXCLUDED.acquired_at
                WHERE runner_account_locks.heartbeat_at
                      < NOW() - (%s * INTERVAL '1 second')
                   OR (
                        runner_account_locks.environment = EXCLUDED.environment
                        AND runner_account_locks.pid = EXCLUDED.pid
                   )
                RETURNING bot_id, environment, pid, heartbeat_at, acquired_at
                """,
                (bot_id, environment, int(pid), float(stale_after_seconds)),
            )
            row = cur.fetchone()
            if row is not None:
                return {"owned": True, "lock": _lock_row(row)}

            cur.execute(
                """
                SELECT bot_id, environment, pid, heartbeat_at, acquired_at
                FROM runner_account_locks
                WHERE bot_id = %s
                """,
                (bot_id,),
            )
            return {"owned": False, "lock": _lock_row(cur.fetchone())}


def refresh_lock(bot_id: str, environment: str, pid: int) -> bool:
    """Refresh only the lease currently owned by this exact process."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE runner_account_locks
                SET heartbeat_at = NOW()
                WHERE bot_id = %s AND environment = %s AND pid = %s
                """,
                (bot_id, environment, int(pid)),
            )
            return cur.rowcount == 1


def release_locks(environment: str, pid: int) -> int:
    """Release only leases owned by this exact process."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM runner_account_locks
                WHERE environment = %s AND pid = %s
                """,
                (environment, int(pid)),
            )
            return cur.rowcount