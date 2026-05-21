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

FLEET_STARTING_CAPITAL = 800_000.0

_BOT_LABELS = {
    "oracle":          "#1 Oracle (Alpaca Momentum)",
    "davy-jones":      "#2 Davy Jones (Kraken Momentum)",
    "blackbeard":      "#3 Blackbeard (Kraken Momentum)",
    "calypso":         "#4 Calypso (Kraken RSI)",
    "apex-predator":   "#5 Apex Predator (Options)",
    "navigator":       "#6 Navigator (Forex)",
}


def _pnl_line(label: str, pnl: float, starting: float | None = None) -> str:
    sign = "+" if pnl >= 0 else ""
    pct = f" ({sign}{pnl / starting * 100:.2f}%)" if starting else ""
    emoji = "🟢" if pnl >= 0 else "🔴"
    return f"{emoji} **{label}**: {sign}${pnl:,.2f}{pct}"


def notify_daily_pnl_report() -> None:
    """
    Query the last 24 hours of equity data and send a fleet-wide P&L digest
    to Discord. Called by APScheduler every day at 05:00 AEST (Brisbane).

    Per-bot breakdown:
      - Oracle (#1)         → alpaca_equity delta from equity_snapshots
      - Davy Jones (#2)     → kraken_trades closed P&L (24 h) per bot_id
      - Blackbeard (#3)     → kraken_trades closed P&L (24 h) per bot_id
      - Calypso (#4)        → kraken_trades closed P&L (24 h) per bot_id
      - Apex Predator (#5)  → options_equity delta from equity_snapshots
      - Navigator (#6)      → forex_equity delta from equity_snapshots
    """
    if not _WEBHOOK_URL:
        logger.info("Discord | DISCORD_WEBHOOK_URL not set — skipping daily P&L report")
        return

    try:
        from db.postgres import get_conn
    except Exception as exc:
        logger.warning(f"Discord | DB import failed — skipping daily P&L report: {exc}")
        return

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # ── Latest equity snapshot ──────────────────────────────────
                cur.execute("""
                    SELECT alpaca_equity, kraken_equity, options_equity,
                           forex_equity, total_equity, ts
                    FROM equity_snapshots
                    ORDER BY ts DESC
                    LIMIT 1
                """)
                latest_row = cur.fetchone()

                # ── Snapshot closest to 24 h ago ────────────────────────────
                cur.execute("""
                    SELECT alpaca_equity, kraken_equity, options_equity,
                           forex_equity, total_equity, ts
                    FROM equity_snapshots
                    WHERE ts <= NOW() - INTERVAL '23 hours 45 minutes'
                    ORDER BY ts DESC
                    LIMIT 1
                """)
                prev_row = cur.fetchone()

                # ── Kraken per-bot realised P&L in last 24 h ────────────────
                cur.execute("""
                    SELECT bot_id, COALESCE(SUM(pnl_usd), 0)
                    FROM kraken_trades
                    WHERE closed_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY bot_id
                """)
                kraken_bot_pnl: dict[str, float] = {
                    row[0]: float(row[1]) for row in cur.fetchall()
                }

    except Exception as exc:
        logger.warning(f"Discord | DB query failed — skipping daily P&L report: {exc}")
        return

    now_brisbane = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")

    if latest_row is None:
        logger.warning("Discord | No equity snapshots found — skipping daily P&L report")
        return

    (alpaca_now, kraken_now, opts_now, forex_now,
     total_now, ts_now) = latest_row

    if prev_row is not None:
        (alpaca_prev, kraken_prev, opts_prev, forex_prev,
         total_prev, ts_prev) = prev_row
    else:
        # First day — compare to starting capital split equally
        share = FLEET_STARTING_CAPITAL / 6
        alpaca_prev = kraken_prev = opts_prev = forex_prev = share
        total_prev = FLEET_STARTING_CAPITAL

    # ── Compute deltas ──────────────────────────────────────────────────────
    d_oracle   = float(alpaca_now)  - float(alpaca_prev)
    d_kraken   = float(kraken_now)  - float(kraken_prev)   # DJ+BB+Cal aggregate
    d_options  = float(opts_now)    - float(opts_prev)
    d_forex    = float(forex_now)   - float(forex_prev)
    d_total    = float(total_now)   - float(total_prev)

    # ── Kraken per-bot breakdown from realised trades ───────────────────────
    d_dj  = kraken_bot_pnl.get("davy-jones", 0.0)
    d_bb  = kraken_bot_pnl.get("blackbeard",  0.0)
    d_cal = kraken_bot_pnl.get("calypso",     0.0)

    # ── Build the message ───────────────────────────────────────────────────
    lines = [
        _pnl_line(_BOT_LABELS["oracle"],         d_oracle,   alpaca_prev),
        _pnl_line(_BOT_LABELS["davy-jones"],     d_dj),
        _pnl_line(_BOT_LABELS["blackbeard"],     d_bb),
        _pnl_line(_BOT_LABELS["calypso"],        d_cal),
        _pnl_line(_BOT_LABELS["apex-predator"],  d_options,  opts_prev),
        _pnl_line(_BOT_LABELS["navigator"],      d_forex,    forex_prev),
    ]
    description = "\n".join(lines)

    pct_total = d_total / FLEET_STARTING_CAPITAL * 100
    sign_total = "+" if d_total >= 0 else ""
    fleet_color = COLOR_GREEN if d_total >= 0 else COLOR_RED

    fields = [
        {
            "name": "Fleet Total 24h P&L",
            "value": f"{sign_total}${d_total:,.2f}  ({sign_total}{pct_total:.2f}%)",
            "inline": False,
        },
        {
            "name": "Fleet Equity",
            "value": f"${total_now:,.2f}",
            "inline": True,
        },
        {
            "name": "Starting Capital",
            "value": f"${FLEET_STARTING_CAPITAL:,.0f}",
            "inline": True,
        },
        {
            "name": "All-Time P&L",
            "value": f"{sign_total}${float(total_now) - FLEET_STARTING_CAPITAL:,.2f}",
            "inline": True,
        },
    ]

    embed = _embed(
        title="📊 Daily Fleet P&L Report",
        description=description,
        color=fleet_color,
        fields=fields,
        footer=f"AlgoEdge · 8-Bot Fleet · {now_brisbane}",
    )

    _send({"embeds": [embed]})
    logger.info(
        f"Discord | Daily P&L report sent — 24h total: {sign_total}${d_total:,.2f} "
        f"({sign_total}{pct_total:.2f}%)"
    )


def is_configured() -> bool:
    return bool(_WEBHOOK_URL)
