"""
Discord Webhook Notifications
-------------------------------
Sends real-time alerts to a Discord channel for key trading events:
  - New trades placed
  - Positions closed
  - Kill switch triggered
  - Profit sweep fired
  - Audit warnings/alerts

Requires DISCORD_WEBHOOK_URL in environment secrets.
If not set, all calls are silent no-ops.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

import requests
from loguru import logger

_WEBHOOK_URL: str | None = os.environ.get("DISCORD_WEBHOOK_URL")
_lock = threading.Lock()


def _send(payload: dict) -> None:
    if not _WEBHOOK_URL:
        return
    try:
        resp = requests.post(_WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code >= 400:
            logger.warning(f"Discord | Webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.warning(f"Discord | Failed to send webhook: {exc}")


def _send_async(payload: dict) -> None:
    t = threading.Thread(target=_send, args=(payload,), daemon=True)
    t.start()


def _embed(
    title: str,
    description: str,
    color: int,
    fields: list[dict] | None = None,
    footer: str | None = None,
) -> dict:
    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = fields
    if footer:
        embed["footer"] = {"text": footer}
    return embed


COLOR_GREEN  = 0x22C55E
COLOR_RED    = 0xEF4444
COLOR_AMBER  = 0xF59E0B
COLOR_BLUE   = 0x3B82F6
COLOR_PURPLE = 0xA855F7
COLOR_ORANGE = 0xF97316


def notify_trade_placed(
    ticker: str,
    side: str,
    notional: float,
    conviction: float | None = None,
    thesis: str | None = None,
    overheated: bool = False,
) -> None:
    color = COLOR_GREEN if side.lower() == "buy" else COLOR_RED
    emoji = "\U0001f4c8" if side.lower() == "buy" else "\U0001f4c9"
    fields = [
        {"name": "Ticker", "value": ticker, "inline": True},
        {"name": "Side", "value": side.upper(), "inline": True},
        {"name": "Notional", "value": f"${notional:,.2f}", "inline": True},
    ]
    if conviction is not None:
        fields.append({"name": "Conviction", "value": f"{conviction:.0%}", "inline": True})
    if overheated:
        fields.append({"name": "Risk Override", "value": "OVERHEATED (50% cut)", "inline": True})
    desc = thesis[:200] if thesis else "No thesis provided"
    _send_async({"embeds": [_embed(f"{emoji} Trade Placed: {ticker}", desc, color, fields)]})


def notify_position_closed(
    symbol: str,
    reason: str,
    pnl_pct: float | None = None,
    pnl_usd: float | None = None,
    bot_name: str = "Alpaca Bot",
) -> None:
    color = COLOR_GREEN if pnl_pct and pnl_pct > 0 else COLOR_RED
    emoji = "\u2705" if pnl_pct and pnl_pct > 0 else "\u274c"
    fields = [
        {"name": "Symbol", "value": symbol, "inline": True},
        {"name": "Reason", "value": reason, "inline": True},
    ]
    if pnl_pct is not None:
        fields.append({"name": "P&L", "value": f"{pnl_pct:+.2f}%", "inline": True})
    _send_async({"embeds": [_embed(f"{emoji} Position Closed: {symbol}", reason, color, fields)]})

    if pnl_pct is not None and pnl_pct > 0:
        try:
            from notifications.alert_manager import enqueue_profitable_trade
            enqueue_profitable_trade(
                bot_name=bot_name,
                symbol=symbol,
                pnl_pct=pnl_pct,
                pnl_usd=pnl_usd or 0.0,
                reason=reason,
            )
        except Exception:
            pass


def notify_kill_switch(drawdown_pct: float, equity: float) -> None:
    _send_async({"embeds": [_embed(
        "\U0001f6a8 KILL SWITCH TRIGGERED",
        f"Daily drawdown of {drawdown_pct:.2%} exceeded threshold. All positions liquidated.",
        COLOR_RED,
        [
            {"name": "Drawdown", "value": f"{drawdown_pct:.2%}", "inline": True},
            {"name": "Equity", "value": f"${equity:,.2f}", "inline": True},
        ],
        footer="Trading halted for the day",
    )]})


def notify_profit_sweep(sweep_amount: float, vault_symbol: str, new_hwm: float) -> None:
    _send_async({"embeds": [_embed(
        "\U0001f4b0 Profit Sweep Fired",
        f"${sweep_amount:,.2f} swept into {vault_symbol}",
        COLOR_PURPLE,
        [
            {"name": "Sweep Amount", "value": f"${sweep_amount:,.2f}", "inline": True},
            {"name": "Vault Symbol", "value": vault_symbol, "inline": True},
            {"name": "New HWM", "value": f"${new_hwm:,.2f}", "inline": True},
        ],
    )]})


def notify_audit_complete(
    overall: str,
    failed_checks: int,
    alert_count: int,
    recommendations: list[str] | None = None,
) -> None:
    color_map = {"ALL_CLEAR": COLOR_GREEN, "REVIEW_RECOMMENDED": COLOR_AMBER, "ACTION_REQUIRED": COLOR_RED}
    color = color_map.get(overall, COLOR_BLUE)
    emoji_map = {"ALL_CLEAR": "\u2705", "REVIEW_RECOMMENDED": "\u26a0\ufe0f", "ACTION_REQUIRED": "\U0001f6a8"}
    emoji = emoji_map.get(overall, "\U0001f50d")
    fields = [
        {"name": "Result", "value": overall, "inline": True},
        {"name": "Failed Checks", "value": str(failed_checks), "inline": True},
        {"name": "Alerts", "value": str(alert_count), "inline": True},
    ]
    desc = "\n".join(f"- {r}" for r in (recommendations or [])[:5]) or "No recommendations"
    _send_async({"embeds": [_embed(f"{emoji} Audit Report: {overall}", desc, color, fields)]})


def notify_blackout_active(event_name: str, window_minutes: int) -> None:
    _send_async({"embeds": [_embed(
        "\u23f8\ufe0f Economic Blackout Active",
        f"Trading paused for {event_name}",
        COLOR_ORANGE,
        [{"name": "Window", "value": f"{window_minutes} min before/after release", "inline": True}],
    )]})


def is_configured() -> bool:
    return bool(_WEBHOOK_URL)
