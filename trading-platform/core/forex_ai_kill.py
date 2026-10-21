"""The one switch that turns off every AI call for Forex (registered plan item 8.10).

Stored in bots_state.metadata for forex_ai (no new table). The heartbeat never
touches metadata, so the switch survives restarts. Reading fails closed: if the
state cannot be read, the AI stays off.
"""

from __future__ import annotations

from loguru import logger

BOT_ID = "forex_ai"


def _conn():
    from db.postgres import get_conn
    return get_conn()


def set_ai_kill(on: bool, reason: str = "") -> None:
    """Flip the switch. Raises if nothing was written."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bots_state
                   SET metadata = COALESCE(metadata, '{}'::jsonb)
                                  || jsonb_build_object('ai_kill', %s::boolean,
                                                        'ai_kill_reason', %s::text,
                                                        'ai_kill_at', to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
                 WHERE bot_id = %s
                """,
                (on, reason[:200], BOT_ID),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"set_ai_kill: no bots_state row for {BOT_ID}")
    logger.warning(f"Forex AI kill switch {'ON' if on else 'OFF'} reason={reason!r}")


def ai_kill_state() -> dict:
    """{'on': bool, 'reason': str, 'at': str|None}. Unreadable or missing = on."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT metadata FROM bots_state WHERE bot_id = %s", (BOT_ID,))
                row = cur.fetchone()
        if row is None:
            return {"on": True, "reason": "no bots_state row (fail closed)", "at": None}
        meta = row[0] or {}
        return {"on": bool(meta.get("ai_kill", False)),
                "reason": meta.get("ai_kill_reason", ""), "at": meta.get("ai_kill_at")}
    except Exception as exc:
        return {"on": True, "reason": f"state unreadable: {type(exc).__name__} (fail closed)", "at": None}
