"""Push the DDG Finance showcase snapshot to DDG Control (Markus, 19 Nov 2026).

ddg.limited/live/finance shows a display-only copy of this platform's main dashboard. That copy never talks
to this API: it reads one snapshot that Control keeps. This job builds the snapshot by asking this API for
exactly the answers the main dashboard reads (SHOWCASE_PATHS, the same list Control accepts), and posts
them to Control with the existing fleet push key.

Rule (Markus): Finance publishes only when the US market is closed. The job does nothing while it is open,
so the public copy shows the numbers as at the last close.

Control drops account numbers, keys and tokens again on its side, whatever arrives.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger     # loguru like the rest of the API: the stdlib logger's "ok" lines never reached the logs

# Per answer. The league board alone can take over 20 s (24 of its answers timed out at 20 s,
# 23-25 Nov 2026), so the public copy often had no league table. The job runs every 30 minutes
# with the market closed, so a slow answer costs nothing.
READ_TIMEOUT_S = 90.0

SHOWCASE_PATHS = [
    "/fleet/equity", "/market-state", "/status/summary", "/positions/live", "/claude-report",
    "/fleet/entry-windows", "/runner/status", "/bots/pause-state", "/fleet-v1/state", "/fleet-v1/record",
    "/momo-v2/state", "/fleet/comparison", "/vault/per-bot/summary", "/fleet/holdings", "/bot-registry",
    "/fleet/equity-history", "/fleet/bot-history?days=90", "/league/leaderboard", "/league/records",
]
LOCAL_API = os.environ.get("SHOWCASE_LOCAL_API", "http://127.0.0.1:8000") + os.environ.get("API_PREFIX", "/trading-api").rstrip("/")


def _push_url() -> str | None:
    """Control's showcase inbox, next to the fleet push address (…/api/inbound/fleet)."""
    explicit = os.environ.get("DDG_SHOWCASE_PUSH_URL")
    if explicit:
        return explicit
    fleet = os.environ.get("DDG_FLEET_PUSH_URL", "")
    return fleet.replace("/inbound/fleet", "/inbound/finance-showcase") if fleet.endswith("/inbound/fleet") else None


def build_showcase() -> dict[str, Any]:
    secret = os.environ.get("TRADING_API_SECRET", "").strip()
    data: dict[str, Any] = {}
    with httpx.Client(timeout=READ_TIMEOUT_S, headers={"X-Trading-API-Secret": secret}) as client:
        for path in SHOWCASE_PATHS:
            try:
                r = client.get(LOCAL_API + path)
                if r.status_code == 200:
                    data[path] = r.json()
                else:
                    logger.warning(f"ddg-showcase skip {path} {r.status_code}")
            except Exception as exc:  # one slow answer must not stop the rest
                logger.warning(f"ddg-showcase skip {path} {type(exc).__name__}")
    return {"taken_at": datetime.now(timezone.utc).isoformat(), "data": data}


def push_showcase() -> None:
    """Send one showcase snapshot when enabled and the US market is closed; never raise."""
    try:
        if os.environ.get("FLEET_PUSH_ENABLED") != "true":
            return
        from core.market_clock import is_market_open
        if is_market_open():
            return
        url, key = _push_url(), os.environ.get("FLEET_INBOUND_KEY")
        if not url or not key:
            logger.warning("ddg-showcase push not configured")
            return
        body = build_showcase()
        r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30.0)
        if 200 <= r.status_code < 300:
            logger.info(f"ddg-showcase ok {len(body['data'])} paths")
        else:
            logger.error(f"ddg-showcase failed {r.status_code}")
    except Exception as exc:
        logger.error(f"ddg-showcase error {type(exc).__name__}")
