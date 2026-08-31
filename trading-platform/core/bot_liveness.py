"""Durable canonical bot-cycle liveness and fail-closed safety findings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

ACTIVE_BOTS = ("oracle", "spy_qqq_trend", "jerome_macro")
DEFAULT_CYCLE_INTERVALS = {
    "oracle": 3600,
    "spy_qqq_trend": 3600,
    "jerome_macro": 3600,
}
# Portfolio heartbeats have deliberately different tolerances because the
# equity bots and Jerome do not run on identical market-hour schedules.
# Keep these values aligned with the reporting stale-bot check.
PORTFOLIO_STALE_THRESHOLDS = {
    "oracle": 108000,
    "spy_qqq_trend": 108000,
    "jerome_macro": 50000,
}


def _canonical(bot_id: str) -> str:
    try:
        from core.bot_registry import normalise_bot_id
        return normalise_bot_id(bot_id) or bot_id
    except Exception:
        return bot_id


def write_cycle(
    bot_id: str,
    *,
    cycle_start: datetime,
    cycle_end: datetime,
    cycle_count: int,
    status: str,
    last_error: str | None = None,
    success: bool = False,
    consecutive_failures: int = 0,
) -> bool:
    """Upsert one complete cycle outcome. This is intentionally independent of bot_state."""
    canonical = _canonical(bot_id)
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_cycle_health (
                        bot_id, last_cycle_start, last_cycle_end, last_success_at,
                        cycle_count, consecutive_failures, last_error, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (bot_id) DO UPDATE SET
                        last_cycle_start = EXCLUDED.last_cycle_start,
                        last_cycle_end = EXCLUDED.last_cycle_end,
                        last_success_at = CASE
                            WHEN EXCLUDED.last_success_at IS NOT NULL
                            THEN EXCLUDED.last_success_at
                            ELSE bot_cycle_health.last_success_at
                        END,
                        cycle_count = EXCLUDED.cycle_count,
                        consecutive_failures = EXCLUDED.consecutive_failures,
                        last_error = EXCLUDED.last_error,
                        status = EXCLUDED.status
                    """,
                    (
                        canonical, cycle_start, cycle_end,
                        cycle_end if success else None, cycle_count,
                        consecutive_failures, (last_error or "")[:1000], status,
                    ),
                )
        return True
    except Exception as exc:
        logger.critical(f"Liveness | durable cycle write failed for {canonical}: {exc}")
        return False


def get_architecture_liveness() -> list[dict[str, Any]]:
    """Read the canonical bot heartbeat sources for the health architecture.

    Unlike the general portfolio helper, this function deliberately lets
    database errors propagate. A health endpoint must not turn a failed
    required read into a green response.
    """
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.bot_id,
                       p.last_updated AS portfolio_last_updated,
                       h.last_success_at AS cycle_last_success,
                       h.status AS cycle_status,
                       h.consecutive_failures,
                       COALESCE(s.paused, FALSE) AS paused
                FROM (VALUES ('oracle'), ('spy_qqq_trend'), ('jerome_macro')) AS b(bot_id)
                LEFT JOIN bot_portfolio p ON p.bot_id = b.bot_id
                LEFT JOIN bot_cycle_health h ON h.bot_id = b.bot_id
                LEFT JOIN bots_state s ON s.bot_id = b.bot_id
                ORDER BY b.bot_id
                """
            )
            columns = [description[0] for description in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def evaluate_liveness(
    *,
    now: datetime | None = None,
    cycle_intervals: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Return safety findings; absent data is a finding, never an empty result."""
    now = now or datetime.now(timezone.utc)
    intervals = {**DEFAULT_CYCLE_INTERVALS, **(cycle_intervals or {})}
    findings: list[dict[str, Any]] = []
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT b.bot_id, COALESCE(s.paused, FALSE),
                           h.last_cycle_start, h.last_cycle_end, h.last_success_at,
                           h.cycle_count, h.consecutive_failures, h.last_error, h.status
                    FROM (VALUES ('oracle'), ('spy_qqq_trend'), ('jerome_macro')) AS b(bot_id)
                    LEFT JOIN bot_cycle_health h ON h.bot_id = b.bot_id
                    LEFT JOIN bots_state s ON s.bot_id = b.bot_id
                    ORDER BY b.bot_id
                    """
                )
                rows = cur.fetchall()
    except Exception as exc:
        logger.critical(f"Liveness | health query failed: {exc}")
        return [{
            "trigger": "bot_cycle_health_unavailable",
            "detail": str(exc),
            "severity": "critical",
        }]

    for bot_id, paused_from_join, start, end, success_at, count, failures, error, status in rows:
        # The query's COALESCE is intentionally fail-closed for missing bots_state.
        # A missing bots_state row must not suppress liveness findings.
        paused = bool(paused_from_join)
        if paused:
            continue
        if success_at is None:
            findings.append({
                "trigger": "bot_cycle_health_missing_or_never_succeeded",
                "bot_id": bot_id,
                "detail": "unpaused bot has no last_success_at",
                "severity": "critical",
            })
            continue
        if int(failures or 0) >= 3:
            findings.append({
                "trigger": "bot_cycle_failures",
                "bot_id": bot_id,
                "detail": f"consecutive_failures={int(failures)} last_error={error or ''}",
                "severity": "critical",
            })
        interval = float(intervals.get(bot_id, 3600))
        age = (now - success_at.astimezone(timezone.utc)).total_seconds()
        if age > 3 * interval:
            findings.append({
                "trigger": "bot_cycle_stale",
                "bot_id": bot_id,
                "detail": f"last_success_age_seconds={age:.1f} threshold_seconds={3 * interval:.1f}",
                "severity": "critical",
            })
    return findings