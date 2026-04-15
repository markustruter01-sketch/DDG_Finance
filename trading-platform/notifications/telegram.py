"""
Telegram Bot Notifications
----------------------------
Sends trade alerts to a Telegram chat via the Bot API.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment secrets.
If not set, all calls are silent no-ops.

Setup:
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Add the bot to your group or DM it, then get your chat_id
  3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Replit Secrets
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

import requests
from loguru import logger

_BOT_TOKEN: str | None = os.environ.get("TELEGRAM_BOT_TOKEN")
_CHAT_ID: str | None = os.environ.get("TELEGRAM_CHAT_ID")
_API_BASE = f"https://api.telegram.org/bot{_BOT_TOKEN}" if _BOT_TOKEN else ""


def _send(text: str, parse_mode: str = "HTML") -> None:
    if not _BOT_TOKEN or not _CHAT_ID:
        return
    try:
        resp = requests.post(
            f"{_API_BASE}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning(f"Telegram | API returned {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.warning(f"Telegram | Failed to send message: {exc}")


def _send_async(text: str) -> None:
    t = threading.Thread(target=_send, args=(text,), daemon=True)
    t.start()


def send_batch_summary(alerts: list[dict[str, Any]]) -> None:
    if not alerts:
        return
    total_pnl = sum(a.get("pnl_usd", 0) for a in alerts)
    total_emoji = "\U0001f525" if total_pnl > 50 else "\U0001f4b0"
    lines = [
        f"{total_emoji} <b>Trade Alert Summary</b> — {len(alerts)} profitable trade{'s' if len(alerts) != 1 else ''}",
        f"\U0001f4b5 Combined P&L: <b>${total_pnl:,.2f}</b>",
        "",
    ]
    for a in alerts[:10]:
        pnl_pct = a.get("pnl_pct", 0)
        pnl_usd = a.get("pnl_usd", 0)
        symbol = a.get("symbol", "???")
        bot = a.get("bot_name", "Unknown")
        lines.append(f"  \u2022 <b>{symbol}</b> ({bot}): +{pnl_pct:.2f}% (${pnl_usd:,.2f})")
    if len(alerts) > 10:
        lines.append(f"  ... and {len(alerts) - 10} more")
    lines.append(f"\n\u23f0 {datetime.now(timezone.utc).strftime('%H:%M UTC · %b %d, %Y')}")
    _send_async("\n".join(lines))


def send_test_message() -> bool:
    if not _BOT_TOKEN or not _CHAT_ID:
        return False
    text = (
        "\U0001f916 <b>AlgoEdge Alert System — Test</b>\n"
        "\n"
        "\u2705 Connection successful!\n"
        "You will receive profitable trade alerts here.\n"
        f"\n\u23f0 {datetime.now(timezone.utc).strftime('%H:%M UTC · %b %d, %Y')}"
    )
    try:
        resp = requests.post(
            f"{_API_BASE}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code < 400
    except Exception:
        return False


def is_configured() -> bool:
    return bool(_BOT_TOKEN and _CHAT_ID)
