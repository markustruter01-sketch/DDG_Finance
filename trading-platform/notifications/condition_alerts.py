"""Shared Discord delivery policy for persistent safety conditions.

Detection remains in the caller.  This module only gives detected conditions a
stable identity, suppresses repeated notifications for a short window, and
routes the first notification through the audited critical Discord path.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger


CONDITION_ALERT_SUPPRESSION_SECONDS = 15 * 60
REALTIME_CONDITION_SOURCES = {
    "kill_switch",
    "runner_liveness",
    "runner_heartbeat",
}
REALTIME_CONDITION_KEYS = {
    ("invariant", "strategy_positions_have_covering_stops"),
    ("invariant", "runner_heartbeat_is_fresh"),
}

_last_alert_at: dict[str, float] = {}


def is_realtime_condition(source: str, condition: str) -> bool:
    """Return whether a condition is allowed to alert outside the digest."""
    return (
        source.strip() in REALTIME_CONDITION_SOURCES
        or (source.strip(), condition.strip()) in REALTIME_CONDITION_KEYS
    )


def condition_key(
    source: str,
    condition: str,
    bot_id: str | None = None,
) -> str:
    """Return a stable identity that deliberately excludes volatile details."""
    scope = str(bot_id or "fleet").strip() or "fleet"
    return f"{source.strip()}::{condition.strip()}::{scope}"


def alert_condition(
    *,
    source: str,
    condition: str,
    title: str,
    description: str,
    bot_id: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> bool:
    """Send once per condition window; return whether a send was requested."""
    key = condition_key(source, condition, bot_id)
    observed_at = time.time() if now is None else float(now)
    last = _last_alert_at.get(key)
    if last is not None and observed_at - last < CONDITION_ALERT_SUPPRESSION_SECONDS:
        logger.warning(
            "Condition alert suppressed | "
            f"key={key} suppression_seconds={CONDITION_ALERT_SUPPRESSION_SECONDS}"
        )
        return False

    _last_alert_at[key] = observed_at
    try:
        from notifications.discord import alert_critical

        alert_critical(title, description, fields=fields)
    except Exception as exc:
        # The Discord implementation audits HTTP/thread failures itself.  This
        # guard covers a synchronous setup/import failure and permits a retry.
        _last_alert_at.pop(key, None)
        logger.error(f"Condition alert delivery failed | key={key} error={type(exc).__name__}")
        return False
    return True


def clear_condition(
    source: str,
    condition: str,
    bot_id: str | None = None,
    *,
    notify_recovery: bool = False,
) -> None:
    """Forget a recovered condition and optionally send one recovery message."""
    key = condition_key(source, condition, bot_id)
    if _last_alert_at.pop(key, None) is not None:
        logger.info(f"Condition alert cleared | key={key}")
        if notify_recovery:
            try:
                from notifications.discord import alert_critical

                alert_critical(
                    f"Recovered: {source}/{condition}",
                    f"The real-time condition `{condition}` has cleared.",
                    fields=[
                        {
                            "name": "Bot",
                            "value": str(bot_id or "fleet"),
                            "inline": True,
                        }
                    ],
                )
            except Exception as exc:
                logger.error(
                    "Condition recovery delivery failed | "
                    f"key={key} error={type(exc).__name__}"
                )


def reset_condition_alerts() -> None:
    """Reset process-local state for tests and controlled process lifecycle."""
    _last_alert_at.clear()