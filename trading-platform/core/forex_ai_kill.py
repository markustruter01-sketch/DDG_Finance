"""The one switch that turns off every AI call for Forex (registered plan item 8.10).

Two sources, stored in bots_state.metadata for forex_ai (no new table):
- "ai_kill": set here through the Finance API (/forex-ai/kill routes);
- "ai_kill_control": DDG Control's requested state, which Finance PULLS each
  hourly forex cycle (the Finance deployment is private, so Control cannot
  call in). Finance reads GET <Control>/api/inbound/finance/forex-ai-switch
  with the same bearer key it already uses to push the fleet snapshot.
AI is off if EITHER source says off. Reading fails closed: if the state
cannot be read, the AI stays off. Control unreachable = keep the last state.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from core import bot_state

BOT_ID = "forex_ai"
CONTROL_SWITCH_PATH = "/inbound/finance/forex-ai-switch"
_PUSH_SUFFIX = "/inbound/fleet"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_ai_kill(on: bool, reason: str = "") -> None:
    """Flip the Finance-side switch. Raises if nothing was written."""
    bot_state.merge_metadata(BOT_ID, {
        "ai_kill": bool(on), "ai_kill_reason": reason[:200], "ai_kill_at": _now(),
    })
    logger.warning(f"Forex AI kill switch {'ON' if on else 'OFF'} reason={reason!r}")


def ai_kill_state() -> dict:
    """{'on', 'reason', 'at', 'local', 'control'}. Unreadable or missing = on."""
    try:
        meta = bot_state.read_metadata(BOT_ID)
    except Exception as exc:
        return {"on": True, "reason": f"state unreadable: {type(exc).__name__} (fail closed)", "at": None}
    if meta is None:
        return {"on": True, "reason": "no bots_state row (fail closed)", "at": None}
    local = bool(meta.get("ai_kill", False))
    control = meta.get("ai_kill_control") or {}
    control_off = bool(control.get("ai_off", False))
    if local:
        reason, at = meta.get("ai_kill_reason", ""), meta.get("ai_kill_at")
    elif control_off:
        reason, at = f"DDG Control: {control.get('reason') or 'no reason given'}", control.get("changed_at")
    else:
        reason, at = "", None
    return {"on": local or control_off, "reason": reason, "at": at,
            "local": local, "control": control}


def control_switch_url() -> str | None:
    """Derived from the fleet push URL, so no new setting is needed."""
    push = os.environ.get("DDG_FLEET_PUSH_URL", "").strip().rstrip("/")
    if not push.endswith(_PUSH_SUFFIX):
        return None
    return push[: -len(_PUSH_SUFFIX)] + CONTROL_SWITCH_PATH


def sync_from_control(http_get: Callable[..., Any] | None = None) -> str:
    """Read DDG Control's requested state and store it. Never raises.
    Any failure keeps the stored state as it was."""
    url, key = control_switch_url(), os.environ.get("FLEET_INBOUND_KEY", "").strip()
    if not url or not key:
        return "not configured"
    try:
        if http_get is None:
            import httpx
            http_get = httpx.get
        resp = http_get(url, headers={"Authorization": f"Bearer {key}"}, timeout=10.0)
        if resp.status_code == 404:
            return "control endpoint not built yet"
        if resp.status_code != 200:
            return f"read failed: HTTP {resp.status_code}"
        body = resp.json()
        ai_off = body.get("ai_off") if isinstance(body, dict) else None
        if not isinstance(ai_off, bool):
            return "invalid answer (kept last state)"
        bot_state.merge_metadata(BOT_ID, {"ai_kill_control": {
            "ai_off": ai_off,
            "reason": str(body.get("reason") or "")[:150],
            "changed_at": str(body.get("changed_at") or "")[:40],
            "read_at": _now(),
        }})
        return f"ai_off={ai_off}"
    except Exception as exc:
        return f"read failed: {type(exc).__name__} (kept last state)"
