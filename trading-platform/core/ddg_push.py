"""Fail-safe publisher for database-backed fleet-equity snapshots."""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from routes.fleet_equity import ACTIVE_BOT_IDS, _fetch_fleet_equity


class _ModeUnavailable(RuntimeError):
    """The portfolio mode cannot be determined from the database."""


def _as_iso_timestamp(value: Any, field: str, *, default_now: bool = False) -> str | None:
    if value is None:
        if default_now:
            return datetime.now(timezone.utc).isoformat()
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} is not an ISO timestamp") from exc
    else:
        raise ValueError(f"{field} is not an ISO timestamp")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _finite_number(value: Any, field: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} is not numeric")
    number = float(value)
    if not math.isfinite(number) or (non_negative and number < 0):
        raise ValueError(f"{field} is outside its allowed range")
    return number


def _portfolio_mode(bot_ids: list[str]) -> str:
    try:
        from db.postgres import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bot_id, is_live_broker
                    FROM bot_portfolio
                    WHERE bot_id = ANY(%s)
                    """,
                    (bot_ids,),
                )
                rows = cur.fetchall()
    except Exception:
        raise _ModeUnavailable from None

    if not rows:
        raise _ModeUnavailable

    live_by_bot: dict[str, bool] = {}
    for bot_id, is_live_broker in rows:
        if not isinstance(bot_id, str) or type(is_live_broker) is not bool:
            raise _ModeUnavailable
        live_by_bot[bot_id] = is_live_broker

    if set(live_by_bot) != set(bot_ids):
        raise _ModeUnavailable

    live_flags = list(live_by_bot.values())
    if all(live_flags):
        return "live"
    if not any(live_flags):
        return "paper"
    return "mixed"


def build_payload() -> dict[str, Any]:
    """Build the receiver's exact payload from the existing fleet calculation."""
    result = _fetch_fleet_equity()
    bot_ids = sorted(ACTIVE_BOT_IDS)
    if not bot_ids or len(bot_ids) > 20:
        raise ValueError("fleet bot count is outside the receiver limit")

    bots: list[dict[str, Any]] = []
    for bot_id in bot_ids:
        row = result.get(bot_id)
        if not isinstance(row, dict):
            raise ValueError("fleet-equity result is missing a bot")

        required_fields = (
            "equity",
            "starting",
            "cash",
            "pnl",
            "positions",
            "last_updated",
            "stale",
            "paused",
        )
        if any(field not in row for field in required_fields):
            raise ValueError("fleet-equity result is missing a required bot field")

        open_positions = row["positions"]
        if (
            isinstance(open_positions, bool)
            or not isinstance(open_positions, int)
            or open_positions < 0
        ):
            raise ValueError("open_positions is not a non-negative integer")
        if not isinstance(row["stale"], bool) or not isinstance(row["paused"], bool):
            raise ValueError("stale and paused must be booleans")

        cash_usd = (
            None
            if row["cash"] is None
            else _finite_number(row["cash"], "cash_usd", non_negative=True)
        )
        bots.append(
            {
                "bot_id": bot_id,
                "equity_usd": _finite_number(
                    row["equity"], "equity_usd", non_negative=True
                ),
                "starting_usd": _finite_number(
                    row["starting"], "starting_usd", non_negative=True
                ),
                "cash_usd": cash_usd,
                "pnl_usd": _finite_number(row["pnl"], "pnl_usd"),
                "open_positions": open_positions,
                "last_updated": _as_iso_timestamp(
                    row["last_updated"], "last_updated"
                ),
                "stale": row["stale"],
                "paused": row["paused"],
            }
        )

    errors = result.get("errors")
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        raise ValueError("fleet-equity result has invalid errors")

    return {
        "generated_at": _as_iso_timestamp(
            result.get("generated_at"), "generated_at", default_now=True
        ),
        "mode": _portfolio_mode(bot_ids),
        "bots": bots,
        "errors": [error[:300] for error in errors[:20]],
    }


def push_fleet_snapshot() -> None:
    """Send one snapshot when enabled; never let a push failure escape."""
    try:
        if os.environ.get("FLEET_PUSH_ENABLED") != "true":
            return

        url = os.environ.get("DDG_FLEET_PUSH_URL")
        key = os.environ.get("FLEET_INBOUND_KEY")
        if not url or not key:
            raise RuntimeError("push configuration unavailable")

        payload = build_payload()
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        response.raise_for_status()
        logger.info(f"ddg-push ok {response.status_code}")
    except _ModeUnavailable:
        logger.error("ddg-push failed mode-unavailable")
    except Exception as exc:
        logger.error(f"ddg-push failed {type(exc).__name__}")
