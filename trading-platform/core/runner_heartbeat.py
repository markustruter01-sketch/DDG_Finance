"""Durable liveness for the multiplexed runner process.

This signal is intentionally separate from bot lease heartbeats.  A runner can
be alive while every bot is paused or waiting for its entry window, so the
runner instance itself must have an independent durable heartbeat.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger


RUNNER_LOOP_INTERVAL_SECONDS = 5.0
RUNNER_HEARTBEAT_FRESHNESS_MULTIPLIER = 3.0
RUNNER_HEARTBEAT_THRESHOLD_SECONDS = (
    RUNNER_LOOP_INTERVAL_SECONDS * RUNNER_HEARTBEAT_FRESHNESS_MULTIPLIER
)


class RunnerHeartbeatReadError(RuntimeError):
    """Raised when the durable runner heartbeat cannot be read."""


def freshness_threshold_seconds(loop_interval_seconds: float = RUNNER_LOOP_INTERVAL_SECONDS) -> float:
    """Return the fail-closed freshness threshold derived from the loop interval."""
    return float(loop_interval_seconds) * RUNNER_HEARTBEAT_FRESHNESS_MULTIPLIER


def write_runner_heartbeat(
    *,
    instance_token: str,
    pid: int,
    environment: str,
    execution_mode: str,
    started_at: datetime,
    loop_count: int,
    bots_registered: int,
    status: str,
    beat_at: datetime | None = None,
) -> bool:
    """Insert or update one runner-instance heartbeat row.

    A unique instance token means a restart creates a new durable row while
    each loop update remains idempotent for the current process.
    """
    beat_at = beat_at or datetime.now(timezone.utc)
    try:
        from db.postgres import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runner_heartbeat (
                        instance_token, pid, environment, execution_mode,
                        started_at, last_beat_at, loop_count, bots_registered, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (instance_token) DO UPDATE SET
                        pid = EXCLUDED.pid,
                        environment = EXCLUDED.environment,
                        execution_mode = EXCLUDED.execution_mode,
                        last_beat_at = EXCLUDED.last_beat_at,
                        loop_count = EXCLUDED.loop_count,
                        bots_registered = EXCLUDED.bots_registered,
                        status = EXCLUDED.status
                    """,
                    (
                        instance_token,
                        int(pid),
                        environment,
                        execution_mode,
                        started_at,
                        beat_at,
                        int(loop_count),
                        int(bots_registered),
                        status,
                    ),
                )
        return True
    except Exception as exc:
        logger.critical(
            f"Runner heartbeat | durable write failed | "
            f"instance_token={instance_token} loop_count={loop_count}: {exc}"
        )
        return False


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_token": row["instance_token"],
        "pid": int(row["pid"]),
        "environment": row["environment"],
        "execution_mode": row["execution_mode"],
        "started_at": row["started_at"],
        "last_beat_at": row["last_beat_at"],
        "loop_count": int(row["loop_count"]),
        "bots_registered": int(row["bots_registered"]),
        "status": row["status"],
    }


def get_runner_status(
    *,
    now: datetime | None = None,
    max_age_seconds: float | None = None,
) -> dict[str, Any]:
    """Return the latest runner row and an ALIVE/STALE/ABSENT verdict.

    Database errors are raised as ``RunnerHeartbeatReadError`` so callers
    cannot accidentally render a failed read as a healthy runner.
    """
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    threshold = (
        freshness_threshold_seconds()
        if max_age_seconds is None
        else float(max_age_seconds)
    )
    try:
        from db.postgres import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT instance_token, pid, environment, execution_mode,
                           started_at, last_beat_at, loop_count, bots_registered, status
                    FROM runner_heartbeat
                    ORDER BY last_beat_at DESC
                    LIMIT 1
                    """
                )
                columns = [description[0] for description in cur.description]
                raw_row = cur.fetchone()
    except Exception as exc:
        raise RunnerHeartbeatReadError(str(exc)) from exc

    if raw_row is None:
        return {
            "verdict": "ABSENT",
            "age_seconds": None,
            "threshold_seconds": threshold,
            "row": None,
            "instance_token": None,
            "pid": None,
            "environment": None,
            "execution_mode": None,
            "started_at": None,
            "last_beat_at": None,
            "loop_count": None,
            "bots_registered": None,
            "status": None,
        }

    row = _normalise_row(dict(zip(columns, raw_row)))
    last_beat_at = row["last_beat_at"]
    if last_beat_at.tzinfo is None:
        last_beat_at = last_beat_at.replace(tzinfo=timezone.utc)
    age_seconds = max(
        0.0,
        (observed_at - last_beat_at.astimezone(timezone.utc)).total_seconds(),
    )
    verdict = "ALIVE" if age_seconds <= threshold else "STALE"
    return {
        "verdict": verdict,
        "age_seconds": age_seconds,
        "threshold_seconds": threshold,
        "row": row,
        **row,
    }