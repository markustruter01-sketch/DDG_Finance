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

# Rate-limit guard for notify_capital_risk: same symbol fires at most once
# every 30 min so a stop failing every 15-min cycle doesn't spam the channel.
_CAPITAL_RISK_LAST_FIRED: dict[str, float] = {}
_CAPITAL_RISK_COOLDOWN = 1800  # seconds (30 min)


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


def notify_capital_risk(msg: str, symbol: str | None = None) -> None:
    """
    Post a capital-risk alert string directly to Discord.

    Rate-limited: the same symbol fires at most once every 30 minutes so a
    stop that keeps failing every 15-min cycle does not spam the channel.
    Never raises — failures are logged and swallowed.
    NOT gated on the degradation tracker.

    Used by: ratchet_stop (B-1/B-2), executor (B-3/B-5),
             oracle_exit_manager (B-4).
    """
    import time as _time
    key = (symbol or "__global__").upper()
    now = _time.time()
    if now - _CAPITAL_RISK_LAST_FIRED.get(key, 0.0) < _CAPITAL_RISK_COOLDOWN:
        return  # rate-limited: same symbol already alerted within 30 min
    _CAPITAL_RISK_LAST_FIRED[key] = now
    try:
        _send_async({"content": msg})
    except Exception as _e:
        logger.error(f"notify_capital_risk | send failed ({key}): {_e}")


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
    "oracle":        "Larry (Oracle)",
    "spy_qqq_trend": "Moe (SPY/QQQ)",
    "jerome_macro":  "Curly (Jerome)",
}

# Active bots in display order — buck_futures retired May 2026
_ACTIVE_BOTS = ["oracle", "spy_qqq_trend", "jerome_macro"]

_WARN_PCT_THRESHOLD  = -1.5   # 24h P&L worse than this triggers a warning line
_WARN_NO_TRADE_HOURS = 48     # hours since last closed trade before warning


def _last_trade_timestamps() -> dict[str, datetime | None]:
    """
    Return {bot_id: last_closed_at} for active bots.
    oracle and spy_qqq_trend from trades table; jerome_macro from jerome_positions.
    Best-effort — returns {} on any failure.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {}
        result: dict[str, datetime | None] = {}
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        CASE asset_class
                            WHEN 'momentum_equity' THEN 'oracle'
                            WHEN 'momentum_etf'    THEN 'spy_qqq_trend'
                        END AS bot_id,
                        MAX(closed_at) AS last_close
                    FROM trades
                    WHERE asset_class IN ('momentum_equity', 'momentum_etf')
                      AND status LIKE 'Closed_%'
                      AND closed_at IS NOT NULL
                    GROUP BY 1
                """)
                for row in cur.fetchall():
                    if row[0]:
                        result[row[0]] = row[1]
                cur.execute("""
                    SELECT bot_id, MAX(closed_at) AS last_close
                    FROM jerome_positions
                    WHERE bot_id = 'jerome_macro'
                      AND status = 'closed'
                      AND closed_at IS NOT NULL
                    GROUP BY bot_id
                """)
                for row in cur.fetchall():
                    result[row[0]] = row[1]
        return result
    except Exception as exc:
        logger.debug(f"Discord | _last_trade_timestamps failed: {exc}")
        return {}


def _pnl_line(label: str, pnl: float, pnl_pct: float | None = None) -> str:
    sign  = "+" if pnl >= 0 else ""
    pct_s = f" ({sign}{pnl_pct:.2f}%)" if pnl_pct is not None else ""
    emoji = "🟢" if pnl >= 0 else "🔴"
    return f"{emoji} **{label}**: {sign}${pnl:,.2f}{pct_s}"


def notify_daily_pnl_report() -> None:
    """
    Send the daily fleet digest as exactly 3 lines:
      Line 1 — 24h % change
      Line 2 — 24h $ change
      Line 3 — market regime (Bull / Bear / Flat / Crisis)

    One `content` POST, no embed, no per-bot breakdown.
    Called by APScheduler every day at 05:00 AEST (Brisbane).
    """
    if not _WEBHOOK_URL:
        logger.info("Discord | DISCORD_WEBHOOK_URL not set — skipping daily report")
        return

    # ── Fleet data ─────────────────────────────────────────────────────────
    try:
        from routes.fleet_equity import _fetch_fleet_equity
        fleet = _fetch_fleet_equity()
    except Exception as exc:
        logger.warning(f"Discord | fleet equity fetch failed — skipping: {exc}")
        return

    fleet_total = fleet.get("fleet_total", {})
    if not fleet_total:
        logger.warning("Discord | fleet_total missing — skipping")
        return

    pnl_24h     = float(fleet_total.get("pnl_24h",     0.0))
    pnl_24h_pct = float(fleet_total.get("pnl_24h_pct", 0.0))
    sign_pct    = "+" if pnl_24h_pct >= 0 else ""
    sign_usd    = "+" if pnl_24h     >= 0 else ""

    # ── Regime ────────────────────────────────────────────────────────────
    regime = "Unknown"
    try:
        from core.market_state import get_market_state as _get_ms
        _ms    = _get_ms(persist=False)
        regime = _ms.get("regime", "Unknown")
    except Exception as _mse:
        logger.debug(f"Discord | market_state fetch non-fatal: {_mse}")

    # Map to clean label
    regime_label = {"BULL": "Bull", "BEAR": "Bear", "CRISIS": "Crisis"}.get(regime, "Flat")

    line1 = f"📊 24h: {sign_pct}{pnl_24h_pct:.2f}%"
    line2 = f"💰 24h: {sign_usd}${pnl_24h:,.0f}"
    line3 = f"📈 Regime: {regime_label}"

    # ── Optional warning lines (4th+ lines, one per qualifying bot) ────────
    warning_lines: list[str] = []
    now_utc = datetime.now(timezone.utc)
    last_trades = _last_trade_timestamps()

    for bot_id in _ACTIVE_BOTS:
        display   = _DISPLAY_NAMES.get(bot_id, bot_id)
        bot_data  = fleet.get(bot_id, {})
        starting  = float(bot_data.get("starting", 100_000.0)) or 100_000.0
        pnl_24h_b = float(bot_data.get("pnl_24h", 0.0))
        pct_24h_b = (pnl_24h_b / starting) * 100

        if pct_24h_b < _WARN_PCT_THRESHOLD:
            sign_b = "+" if pct_24h_b >= 0 else ""
            warning_lines.append(f"⚠️ {display}: {sign_b}{pct_24h_b:.1f}% (24h)")
        else:
            last_close = last_trades.get(bot_id)
            if last_close is None:
                # No timestamped trade ever — treat as no-trade warning
                warning_lines.append(f"⚠️ {display}: no trades {_WARN_NO_TRADE_HOURS}h")
            else:
                if last_close.tzinfo is None:
                    last_close = last_close.replace(tzinfo=timezone.utc)
                hours_since = (now_utc - last_close).total_seconds() / 3600
                if hours_since > _WARN_NO_TRADE_HOURS:
                    warning_lines.append(f"⚠️ {display}: no trades {_WARN_NO_TRADE_HOURS}h")

    content_lines = [line1, line2, line3] + warning_lines
    _send({"content": "\n".join(content_lines)})
    logger.info(
        f"Discord | {len(content_lines)}-line report sent — "
        f"24h: {sign_pct}{pnl_24h_pct:.2f}% / {sign_usd}${pnl_24h:,.0f} / {regime_label}"
        + (f" / {len(warning_lines)} warning(s)" if warning_lines else "")
    )


def is_configured() -> bool:
    return bool(_WEBHOOK_URL)
