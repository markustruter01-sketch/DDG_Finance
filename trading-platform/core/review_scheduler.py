"""Scheduled review flags for the canonical equity fleet."""

from __future__ import annotations

from datetime import date
from loguru import logger


def _upsert_flag(flag_key: str, title: str, description: str,
                 due_date: date, priority: str = "medium") -> None:
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO review_flags
                        (flag_key, title, description, due_date, priority, status)
                    VALUES (%s, %s, %s, %s, %s, 'pending')
                    ON CONFLICT (flag_key) DO UPDATE SET
                        title=EXCLUDED.title, description=EXCLUDED.description,
                        due_date=EXCLUDED.due_date, priority=EXCLUDED.priority
                """, (flag_key, title, description, due_date, priority))
    except Exception as exc:
        logger.debug("ReviewScheduler | upsert failed: %s", exc)


def _resolve_flag_if_condition(flag_key: str, condition: bool, note: str = "") -> None:
    if not condition:
        return
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE review_flags
                    SET status='auto_resolved', resolved_at=NOW(), resolved_note=%s
                    WHERE flag_key=%s AND status='pending'
                """, (note, flag_key))
    except Exception as exc:
        logger.debug("ReviewScheduler | resolve failed: %s", exc)


def run_scheduled_checks() -> None:
    """Review current performance data without querying retired tables."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*)::int, COALESCE(SUM(realized_pnl), 0)
                    FROM trades
                    WHERE status IN ('Closed_Win', 'Closed_Loss')
                      AND closed_at >= NOW() - INTERVAL '30 days'
                """)
                trade_count, pnl = cur.fetchone()
                cur.execute("""
                    SELECT bot_id, status, consecutive_failures
                    FROM bot_cycle_health
                    WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                """)
                cycles = cur.fetchall()

        _upsert_flag(
            "fleet_30_day_review",
            "Active fleet 30-day performance review",
            f"{trade_count} closed trades; realized P&L ${float(pnl):,.2f}. "
            "Review before changing any strategy or allocation.",
            date.today(),
            "high" if trade_count < 3 else "medium",
        )
        failures = [(b, f) for b, status, f in cycles if (f or 0) > 0 or status == "error"]
        _upsert_flag(
            "fleet_cycle_health_review",
            "Active fleet cycle-health review",
            f"Current cycle-health failures: {failures or 'none'}.",
            date.today(),
            "high" if failures else "low",
        )
        _resolve_flag_if_condition(
            "fleet_cycle_health_review", not failures,
            "All canonical bot cycles report success or intentional pause.",
        )
        logger.info("ReviewScheduler | canonical checks complete")
    except Exception as exc:
        logger.error("ReviewScheduler | checks failed: %s", exc)