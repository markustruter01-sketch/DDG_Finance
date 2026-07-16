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


def alert_critical(title: str, description: str, fields: list[dict] | None = None) -> None:
    """
    Send a capital-safety CRITICAL alert directly via webhook.

    Called from kill_switch, fleet_halt, drawdown_guard, exit_manager, and any
    path where a safety check fails.  Does NOT route through the degradation
    tracker — the webhook call fires even if the tracker itself is unavailable.
    """
    payload = {"embeds": [_embed(title, description, COLOR_RED, fields=fields)]}
    _send_async(payload)


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

    # ── Prepend market state header ────────────────────────────────────────────
    _state_header = ""
    try:
        import sys as _sys
        import os as _os
        _tp_root = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..")
        if _tp_root not in _sys.path:
            _sys.path.insert(0, _tp_root)
        from core.market_state import get_market_state as _get_ms
        _ms = _get_ms(persist=False)
        _regime   = _ms.get("regime", "UNKNOWN")
        _high_vol = _ms.get("high_vol", False)
        _spy_20d  = _ms.get("spy_20d_ret")
        _emoji    = {"CRISIS": "🚨", "BEAR": "🐻", "BULL": "🟢"}.get(_regime, "❓")
        _state_header = f"{_emoji} **Market: {_regime}**"
        if _high_vol:
            _state_header += "  ⚠ HIGH_VOL"
        if _spy_20d is not None:
            _state_header += f"  (SPY 20d: {_spy_20d:+.1%})"
        _state_header += "\n"
    except Exception as _mse:
        logger.debug(f"Discord | market_state fetch non-fatal: {_mse}")

    # ── Walk-forward status banners (ARC 2) ───────────────────────────────────
    # Prepend RED/AMBER banners before the per-bot P&L lines.
    # DISQUALIFIED bots that are actively trading also surface here.
    _wf_banners: list[str] = []
    try:
        from analysis.arc2_walk_forward import get_current_wf_status
        _wf_rows = get_current_wf_status()
        _STATUS_EMOJI = {"RED": "🔴", "AMBER": "🟡", "GREEN": "✅",
                         "INSUFFICIENT_DATA": "⏳", "DISQUALIFIED": "⚫"}
        for _wf in _wf_rows:
            _st = _wf.get("wf_status", "")
            _bid = _wf.get("bot_id", "?")
            if _st == "RED":
                _sh = _wf.get("wf_sharpe_90d")
                _fl = _wf.get("wf_oos_floor_sharpe")
                _days = _wf.get("wf_consecutive_below_floor") or 0
                _sh_s = f"{_sh:.3f}" if _sh is not None else "N/A"
                _fl_s = f"{_fl:.3f}" if _fl is not None else "N/A"
                _protocol = ""
                if _days >= 120:
                    _protocol = " — ⛔ HALT ENTRIES (human action required)"
                elif _days >= 60:
                    _protocol = " — ⚠ HALVE SIZE (human action required)"
                _wf_banners.append(
                    f"🔴 **{_bid} RED**: trailing Sharpe {_sh_s} "
                    f"below OOS floor {_fl_s} for **{_days}d**{_protocol}"
                )
            elif _st == "AMBER":
                _sh = _wf.get("wf_sharpe_90d")
                _fl = _wf.get("wf_oos_floor_sharpe")
                _days = _wf.get("wf_consecutive_below_floor") or 0
                _sh_s = f"{_sh:.3f}" if _sh is not None else "N/A"
                _fl_s = f"{_fl:.3f}" if _fl is not None else "N/A"
                _wf_banners.append(
                    f"🟡 **{_bid} AMBER**: trailing Sharpe {_sh_s} "
                    f"below OOS floor {_fl_s} ({_days}/60d)"
                )
    except Exception as _wfe:
        logger.debug(f"Discord | walk-forward status fetch non-fatal: {_wfe}")

    _body = "\n".join(lines) if lines else "_No bot data available._"
    _banner_block = "\n".join(_wf_banners)
    if _banner_block:
        _body = _banner_block + "\n\n" + _body
    description = (_state_header + "\n" + _body) if _state_header else _body

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
