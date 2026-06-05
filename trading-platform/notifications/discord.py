"""
Discord Webhook Notifications
-------------------------------
Single automated notification: Daily fleet P&L report at 05:00 AEST (Brisbane).

All other event-driven Discord notifications (trade placed, kill switch, audit,
profit sweep, blackout) have been removed — Discord is now a daily digest only.

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
        resp = requests.post(_WEBHOOK_URL, json=payload, timeout=10)
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

_DISPLAY_NAMES = {
    "oracle":        "Oracle (Momentum Equities)",
    "spy_qqq_trend": "SPY/QQQ Trend",
    "jerome_macro":  "Jerome v2 (Commodity Trend)",
    "buck_futures":  "Buck Futures (Commodity Trend)",
}

_BOT_ORDER = ["oracle", "spy_qqq_trend", "jerome_macro", "buck_futures"]


def _pnl_line(label: str, pnl: float, pnl_pct: float | None = None) -> str:
    sign  = "+" if pnl >= 0 else ""
    pct_s = f" ({sign}{pnl_pct:.2f}%)" if pnl_pct is not None else ""
    emoji = "🟢" if pnl >= 0 else "🔴"
    return f"{emoji} **{label}**: {sign}${pnl:,.2f}{pct_s}"


def notify_daily_pnl_report() -> None:
    """
    Build and send the daily fleet P&L digest to Discord.
    Called by APScheduler every day at 05:00 AEST (Brisbane).

    Data source: _fetch_fleet_equity() — the same function that backs
    GET /fleet/equity — reads bot_portfolio for all 4 live bots.
    No duplicate queries, no stale tables.
    """
    if not _WEBHOOK_URL:
        logger.info("Discord | DISCORD_WEBHOOK_URL not set — skipping daily P&L report")
        return

    # ── Pull canonical fleet data ──────────────────────────────────────────
    try:
        from routes.fleet_equity import _fetch_fleet_equity
        fleet = _fetch_fleet_equity()
    except Exception as exc:
        logger.warning(f"Discord | fleet equity fetch failed — skipping daily P&L report: {exc}")
        return

    fleet_total = fleet.get("fleet_total", {})
    if not fleet_total:
        logger.warning("Discord | fleet_total missing from fleet equity response — skipping")
        return

    # ── Per-bot lines (canonical order, known bots only) ──────────────────
    lines: list[str] = []
    for bot_id in _BOT_ORDER:
        bot = fleet.get(bot_id)
        if not bot:
            continue
        label = _DISPLAY_NAMES.get(bot_id, bot_id)
        pnl     = float(bot.get("pnl", 0.0))
        pnl_pct = float(bot.get("pnl_pct", 0.0))
        lines.append(_pnl_line(label, pnl, pnl_pct))

    description = "\n".join(lines) if lines else "_No bot data available._"

    # ── Fleet-level fields ─────────────────────────────────────────────────
    fleet_eq     = float(fleet_total.get("equity",   0.0))
    fleet_start  = float(fleet_total.get("starting", 0.0))
    fleet_pnl    = float(fleet_total.get("pnl",      0.0))
    fleet_pnl_pct = float(fleet_total.get("pnl_pct", 0.0))
    fleet_wr     = fleet_total.get("win_rate")
    bot_count    = len([b for b in _BOT_ORDER if b in fleet])

    sign_fleet = "+" if fleet_pnl >= 0 else ""
    fleet_color = COLOR_GREEN if fleet_pnl >= 0 else COLOR_RED

    wr_val = f"{fleet_wr * 100:.1f}%" if fleet_wr is not None else "—"

    fields: list[dict] = [
        {
            "name":   "Total P&L (all-time)",
            "value":  f"{sign_fleet}${fleet_pnl:,.2f}  ({sign_fleet}{fleet_pnl_pct:.2f}%)",
            "inline": False,
        },
        {
            "name":   "Fleet Equity",
            "value":  f"${fleet_eq:,.2f}",
            "inline": True,
        },
        {
            "name":   "Starting Capital",
            "value":  f"${fleet_start:,.0f}",
            "inline": True,
        },
        {
            "name":   "30d Win Rate",
            "value":  wr_val,
            "inline": True,
        },
    ]

    now_brisbane = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

    embed = _embed(
        title="📊 Daily Fleet P&L Report",
        description=description,
        color=fleet_color,
        fields=fields,
        footer=f"Quant Terminal · {bot_count}-Bot Fleet · {now_brisbane}",
    )

    _send({"embeds": [embed]})
    logger.info(
        f"Discord | Daily P&L report sent — fleet equity: ${fleet_eq:,.2f}  "
        f"total P&L: {sign_fleet}${fleet_pnl:,.2f} ({sign_fleet}{fleet_pnl_pct:.2f}%)"
    )


def is_configured() -> bool:
    return bool(_WEBHOOK_URL)
