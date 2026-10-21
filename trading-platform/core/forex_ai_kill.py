"""The one switch that turns off every AI call for Forex (registered plan item 8.10).

Stored in bots_state.metadata for forex_ai (no new table). Reading fails
closed: if the state cannot be read, the AI stays off.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from core import bot_state

BOT_ID = "forex_ai"


def set_ai_kill(on: bool, reason: str = "") -> None:
    """Flip the switch. Raises if nothing was written."""
    bot_state.merge_metadata(BOT_ID, {
        "ai_kill": bool(on),
        "ai_kill_reason": reason[:200],
        "ai_kill_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    logger.warning(f"Forex AI kill switch {'ON' if on else 'OFF'} reason={reason!r}")


def ai_kill_state() -> dict:
    """{'on': bool, 'reason': str, 'at': str|None}. Unreadable or missing = on."""
    try:
        meta = bot_state.read_metadata(BOT_ID)
    except Exception as exc:
        return {"on": True, "reason": f"state unreadable: {type(exc).__name__} (fail closed)", "at": None}
    if meta is None:
        return {"on": True, "reason": "no bots_state row (fail closed)", "at": None}
    return {"on": bool(meta.get("ai_kill", False)),
            "reason": meta.get("ai_kill_reason", ""), "at": meta.get("ai_kill_at")}
