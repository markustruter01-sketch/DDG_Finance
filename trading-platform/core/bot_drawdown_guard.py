"""
bot_drawdown_guard.py — Per-bot high water mark (HWM) drawdown circuit breaker.

Tracks each bot's HWM in the bot_drawdown_hwm table.
If current equity drops ≥ pause_threshold_pct (default 8%) from HWM, the bot
should be paused. The caller (each bot's main cycle) is responsible for acting
on the return value.

Table: bot_drawdown_hwm
  bot_id              TEXT PRIMARY KEY
  hwm                 NUMERIC   — highest equity ever seen
  hwm_set_at          TIMESTAMPTZ
  last_check_at       TIMESTAMPTZ
  pause_threshold_pct NUMERIC   — default 0.08 (8%)
  is_paused_by_drawdown BOOLEAN
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from loguru import logger


def check_bot_drawdown(bot_id: str, current_equity: float) -> dict:
    """
    Check whether this bot has breached its HWM drawdown limit.

    Returns:
        {
          "should_pause": bool,
          "reason":       str,
          "drawdown_pct": float,     # positive = drawdown from HWM
          "hwm":          float,
          "current":      float,
        }
    """
    _STARTING = 100_000.0

    try:
        import psycopg2
        db_url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not db_url:
            return _ok(current_equity, _STARTING)

        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                # Upsert: create row if it doesn't exist
                cur.execute("""
                    INSERT INTO bot_drawdown_hwm (bot_id, hwm, hwm_set_at, last_check_at)
                    VALUES (%s, %s, NOW(), NOW())
                    ON CONFLICT (bot_id) DO NOTHING
                """, (bot_id, max(current_equity, _STARTING)))
                conn.commit()

                # Read current HWM + threshold
                cur.execute("""
                    SELECT hwm, pause_threshold_pct, is_paused_by_drawdown
                    FROM bot_drawdown_hwm
                    WHERE bot_id = %s
                """, (bot_id,))
                row = cur.fetchone()

            if row is None:
                return _ok(current_equity, _STARTING)

            hwm, threshold_pct, already_paused = row
            hwm = float(hwm)
            threshold_pct = float(threshold_pct)

            # Update HWM if equity is higher
            if current_equity > hwm:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE bot_drawdown_hwm
                        SET hwm = %s,
                            hwm_set_at = NOW(),
                            last_check_at = NOW(),
                            is_paused_by_drawdown = FALSE
                        WHERE bot_id = %s
                    """, (current_equity, bot_id))
                    conn.commit()
                return _ok(current_equity, current_equity)

            # Update last_check_at
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE bot_drawdown_hwm
                    SET last_check_at = NOW()
                    WHERE bot_id = %s
                """, (bot_id,))
                conn.commit()

            # Check drawdown
            drawdown_pct = (hwm - current_equity) / hwm if hwm > 0 else 0.0

            if drawdown_pct >= threshold_pct:
                reason = (
                    f"Drawdown {drawdown_pct * 100:.2f}% from HWM "
                    f"(${hwm:,.2f} → ${current_equity:,.2f}) — "
                    f"exceeds {threshold_pct * 100:.0f}% limit"
                )
                if not already_paused:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE bot_drawdown_hwm
                            SET is_paused_by_drawdown = TRUE
                            WHERE bot_id = %s
                        """, (bot_id,))
                        conn.commit()
                    logger.warning(
                        f"DrawdownGuard | {bot_id} PAUSED — {reason}"
                    )
                return {
                    "should_pause": True,
                    "reason": reason,
                    "drawdown_pct": round(drawdown_pct * 100, 2),
                    "hwm": round(hwm, 2),
                    "current": round(current_equity, 2),
                }

            # Within limit
            if already_paused:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE bot_drawdown_hwm
                        SET is_paused_by_drawdown = FALSE
                        WHERE bot_id = %s
                    """, (bot_id,))
                    conn.commit()

            return {
                "should_pause": False,
                "reason": "within_drawdown_limit",
                "drawdown_pct": round(drawdown_pct * 100, 2),
                "hwm": round(hwm, 2),
                "current": round(current_equity, 2),
            }

        finally:
            conn.close()

    except Exception as exc:
        logger.debug(f"DrawdownGuard | {bot_id} check failed (non-fatal): {exc}")
        return _ok(current_equity, _STARTING)


def _ok(current: float, hwm: float) -> dict:
    return {
        "should_pause": False,
        "reason": "drawdown_guard_unavailable",
        "drawdown_pct": 0.0,
        "hwm": round(hwm, 2),
        "current": round(current, 2),
    }


def get_all_drawdown_states() -> list[dict]:
    """Return all bot drawdown states — used by the weekly review endpoint."""
    try:
        import psycopg2, psycopg2.extras
        db_url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not db_url:
            return []
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT bot_id, hwm, hwm_set_at, last_check_at,
                           pause_threshold_pct, is_paused_by_drawdown
                    FROM bot_drawdown_hwm
                    ORDER BY bot_id
                """)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"DrawdownGuard | get_all failed: {exc}")
        return []
