"""
Discord Webhook Notifications
-----------------------------
Sends the daily fleet P&L report plus direct capital-safety alerts.

Requires DISCORD_WEBHOOK_URL in environment secrets.
Every delivery attempt is audited without storing webhook URLs or payloads.
If the webhook is absent, the call is skipped and recorded as such.
"""

from __future__ import annotations

import os
import threading
from copy import deepcopy
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


def is_published_environment() -> bool:
    """Return True only for the Replit published deployment."""
    return os.environ.get("REPLIT_DEPLOYMENT") == "1"


def environment_name() -> str:
    """Return a safe, human-readable environment label for Discord messages."""
    if is_published_environment():
        return "published"
    runner_environment = os.environ.get("RUNNER_ENVIRONMENT", "").strip().lower()
    execution_mode = os.environ.get("RUNNER_EXECUTION_MODE", "").strip().lower()
    if runner_environment and execution_mode and runner_environment != execution_mode:
        return f"{runner_environment}/{execution_mode}"
    return runner_environment or execution_mode or "development"


def _environment_prefix() -> str:
    return f"[environment: {environment_name()}]"


def _with_environment_label(payload: dict) -> dict:
    """Copy a Discord payload and label every supported message surface."""
    labelled = deepcopy(payload)
    prefix = _environment_prefix()
    content = labelled.get("content")
    if content:
        labelled["content"] = f"{prefix} {content}"

    embeds = labelled.get("embeds")
    if isinstance(embeds, list):
        for embed in embeds:
            if not isinstance(embed, dict):
                continue
            if embed.get("title"):
                embed["title"] = f"{prefix} {embed['title']}"
            elif embed.get("description"):
                embed["description"] = f"{prefix} {embed['description']}"
            else:
                embed["description"] = prefix

    if not content and not embeds:
        labelled["content"] = prefix
    return labelled


def _audit_start(alert_type: str, title: str) -> int | None:
    try:
        from db.postgres import create_discord_alert_event
        return create_discord_alert_event(alert_type, title)
    except Exception as exc:
        logger.warning(f"Discord | audit start failed: {exc}")
        return None


def _audit_finish(
    event_id: int | None,
    status: str,
    *,
    http_status: int | None = None,
    error: str | None = None,
) -> None:
    try:
        from db.postgres import complete_discord_alert_event
        complete_discord_alert_event(
            event_id,
            status,
            http_status=http_status,
            error=error,
        )
    except Exception as exc:
        logger.warning(f"Discord | audit completion failed: {exc}")


def _safe_error(exc: Exception) -> str:
    """Return a credential-safe error label; request exceptions can contain URLs."""
    return type(exc).__name__


def _send(
    payload: dict,
    *,
    event_id: int | None = None,
    alert_type: str = "general",
    title: str = "Discord alert",
) -> None:
    if event_id is None:
        event_id = _audit_start(alert_type, title)
    payload = _with_environment_label(payload)
    if not is_published_environment():
        error = "Discord delivery blocked outside the published environment"
        _audit_finish(event_id, "skipped_not_published", error=error)
        logger.critical(
            "Discord | delivery blocked outside published environment | "
            f"environment={environment_name()} alert_type={alert_type} title={title}"
        )
        return
    if not _WEBHOOK_URL:
        _audit_finish(event_id, "skipped_not_configured", error="DISCORD_WEBHOOK_URL is not configured")
        logger.warning("Discord | DISCORD_WEBHOOK_URL not set — skipping alert")
        return
    try:
        resp = requests.post(_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code >= 400:
            _audit_finish(
                event_id,
                "failed",
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
            )
            logger.warning(f"Discord | Webhook returned HTTP {resp.status_code}")
        else:
            _audit_finish(event_id, "sent", http_status=resp.status_code)
    except Exception as exc:
        safe_error = _safe_error(exc)
        _audit_finish(event_id, "failed", error=safe_error)
        logger.warning(f"Discord | Failed to send webhook: {safe_error}")


def _send_async(
    payload: dict,
    *,
    alert_type: str = "general",
    title: str = "Discord alert",
) -> None:
    event_id = _audit_start(alert_type, title)
    try:
        t = threading.Thread(
            target=_send,
            args=(payload,),
            kwargs={"event_id": event_id, "alert_type": alert_type, "title": title},
            daemon=True,
        )
        t.start()
    except Exception as exc:
        safe_error = _safe_error(exc)
        _audit_finish(event_id, "failed", error=safe_error)
        logger.warning(f"Discord | Failed to start delivery thread: {safe_error}")


def send_payload(
    payload: dict,
    *,
    alert_type: str = "general",
    title: str = "Discord alert",
) -> None:
    """Send an arbitrary Discord payload through the audited policy boundary."""
    _send_async(payload, alert_type=alert_type, title=title)


def alert_critical(title: str, description: str, fields: list[dict] | None = None) -> None:
    """
    Send a capital-safety CRITICAL alert directly via webhook.

    Called from kill_switch, fleet_halt, drawdown_guard, exit_manager, and any
    path where a safety check fails.  Does NOT route through the degradation
    tracker — the webhook call fires even if the tracker itself is unavailable.
    """
    payload = {"embeds": [_embed(title, description, COLOR_RED, fields=fields)]}
    _send_async(payload, alert_type="critical", title=title)


def notify_capital_risk(msg: str, symbol: str | None = None) -> None:
    """
    Persist a capital-risk finding for the daily digest.

    Rate-limited: the same symbol fires at most once every 30 minutes so a
    stop that keeps failing every 15-min cycle does not spam the channel.
    Never raises — failures are logged and swallowed.
    Capital-risk findings are routine delivery after the published-only policy;
    the real-time naked-position invariant remains the immediate safety path.

    Used by: ratchet_stop (B-1/B-2), executor (B-3/B-5),
             oracle_exit_manager (B-4).
    """
    import time as _time
    key = (symbol or "__global__").upper()
    now = _time.time()
    if now - _CAPITAL_RISK_LAST_FIRED.get(key, 0.0) < _CAPITAL_RISK_COOLDOWN:
        return  # rate-limited: same symbol already alerted within 30 min
    try:
        _CAPITAL_RISK_LAST_FIRED[key] = now
        from core.degradation_tracker import record_degradation

        record_degradation(
            component="execution",
            severity="error",
            error_type="capital_risk",
            message=msg,
            bot_id=None,
        )
    except Exception as _e:
        logger.error(f"notify_capital_risk | persistence failed ({key}): {type(_e).__name__}")


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

# Dashboard/Discord use the canonical display id, while the ETF engine still
# persists US Core positions under its leaf-strategy id.
_ETF_LEDGER_TO_ACTIVE_BOT = {
    "oracle": "oracle",
    "bot2_spy_qqq": "spy_qqq_trend",
    "jerome_macro": "jerome_macro",
}

_WARN_PCT_THRESHOLD  = -1.5   # 24h P&L worse than this triggers a warning line
_WARN_NO_TRADE_HOURS = 48     # hours since last closed trade before warning


def _last_trade_timestamps() -> dict[str, datetime | None]:
    """
    Return {bot_id: last ETF trade activity timestamp} for active bots.

    ETF bots persist their primary execution ledger in alpaca_etf_positions.
    An opening fill is real trading activity even while the position remains
    open, so use the newest opened_at or closed_at timestamp rather than the
    legacy journal's closed-trades-only view.

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
                        bot_id,
                        MAX(
                            CASE
                                WHEN closed_at IS NULL THEN opened_at
                                ELSE GREATEST(opened_at, closed_at)
                            END
                        ) AS last_activity
                    FROM alpaca_etf_positions
                    WHERE bot_id = ANY(%s)
                    GROUP BY bot_id
                """, (list(_ETF_LEDGER_TO_ACTIVE_BOT),))
                for row in cur.fetchall():
                    active_bot_id = _ETF_LEDGER_TO_ACTIVE_BOT.get(row[0])
                    if active_bot_id:
                        result[active_bot_id] = row[1]
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
    audit_id = _audit_start("daily_report", "Daily fleet P&L report")
    if not _WEBHOOK_URL:
        _send(
            {},
            event_id=audit_id,
            alert_type="daily_report",
            title="Daily fleet P&L report",
        )
        return

    # ── Fleet data ─────────────────────────────────────────────────────────
    try:
        from routes.fleet_equity import _fetch_fleet_equity
        fleet = _fetch_fleet_equity()
    except Exception as exc:
        _audit_finish(audit_id, "failed", error="fleet_equity_unavailable")
        logger.warning(f"Discord | fleet equity fetch failed — skipping: {exc}")
        return

    fleet_total = fleet.get("fleet_total", {})
    if not fleet_total:
        _audit_finish(audit_id, "failed", error="fleet_total_missing")
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
    _send(
        {"content": "\n".join(content_lines)},
        event_id=audit_id,
        alert_type="daily_report",
        title="Daily fleet P&L report",
    )
    logger.info(
        f"Discord | {len(content_lines)}-line report sent — "
        f"24h: {sign_pct}{pnl_24h_pct:.2f}% / {sign_usd}${pnl_24h:,.0f} / {regime_label}"
        + (f" / {len(warning_lines)} warning(s)" if warning_lines else "")
    )


def _compact_json(value: Any, limit: int = 360) -> str:
    import json

    text = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _digest_database_state() -> dict[str, Any]:
    """Read durable cycle and reconciliation state for the daily digest."""
    state: dict[str, Any] = {"cycles": [], "reconciliation": None, "readable": True}
    try:
        from db.postgres import get_conn, is_pg_available

        if not is_pg_available():
            state["readable"] = False
            return state
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT bot_id, last_success_at, status, consecutive_failures
                    FROM bot_cycle_health
                    ORDER BY bot_id
                    """
                )
                state["cycles"] = [
                    {
                        "bot_id": row[0],
                        "last_success_at": row[1],
                        "status": row[2],
                        "consecutive_failures": row[3],
                    }
                    for row in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT run_ts, clean, flags
                    FROM reconciliation_log
                    ORDER BY run_ts DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    state["reconciliation"] = {
                        "run_ts": row[0],
                        "clean": row[1],
                        "flags": row[2],
                    }
    except Exception as exc:
        logger.warning(f"Discord | digest database read failed: {type(exc).__name__}")
        state["readable"] = False
    return state


def build_daily_health_digest(now: datetime | None = None) -> str:
    """Build the health digest without sending it."""
    import json
    from collections import Counter

    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        from core.invariants import run_all_invariants

        report = run_all_invariants(now=observed_at)
    except Exception as exc:
        report = {
            "overall": "UNKNOWN",
            "results": [],
            "error": type(exc).__name__,
        }

    try:
        from core.degradation_tracker import get_recent_events

        events = get_recent_events(limit=500, hours=24)
    except Exception as exc:
        logger.warning(f"Discord | digest degradation read failed: {type(exc).__name__}")
        events = []

    database_state = _digest_database_state()
    try:
        from core.runner_heartbeat import get_runner_status

        heartbeat = get_runner_status(now=observed_at)
    except Exception as exc:
        heartbeat = {"verdict": "UNKNOWN", "error": type(exc).__name__}

    failures = [
        result for result in report.get("results", [])
        if result.get("status") == "FAIL"
    ]
    unknowns = [
        result for result in report.get("results", [])
        if result.get("status") == "UNKNOWN"
    ]
    counts = Counter(str(event.get("error_type") or "unknown") for event in events)
    recovered = [event for event in events if event.get("resolved_at")]
    lines = [
        "Daily platform health digest (last 24h)",
        f"Overall: {report.get('overall', 'UNKNOWN')} | "
        f"failures={len(failures)} unknowns={len(unknowns)} "
        f"degradations={len(events)} recovered={len(recovered)}",
    ]

    if failures:
        lines.append("Currently failing invariants:")
        for result in failures:
            lines.append(
                f"- {result.get('name', 'unknown')}: {result.get('message', '')[:180]} "
                f"actual={_compact_json(result.get('actual'))} "
                f"difference={_compact_json(result.get('difference'))}"
            )
    else:
        lines.append("Currently failing invariants: none")
    if unknowns:
        lines.append(
            "Invariant inputs unavailable: "
            + ", ".join(str(result.get("name", "unknown")) for result in unknowns)
        )

    lines.append("Degradations by error_type:")
    if counts:
        lines.extend(f"- {error_type}: {count}" for error_type, count in counts.most_common())
    else:
        lines.append("- none")

    lines.append("Bot cycle ages:")
    if database_state["cycles"]:
        for cycle in database_state["cycles"]:
            last_success = cycle["last_success_at"]
            if last_success is None:
                age = "never"
            else:
                if last_success.tzinfo is None:
                    last_success = last_success.replace(tzinfo=timezone.utc)
                age = f"{max(0.0, (observed_at - last_success).total_seconds()):.0f}s"
            lines.append(
                f"- {cycle['bot_id']}: {age} status={cycle['status']} "
                f"failures={cycle['consecutive_failures']}"
            )
    else:
        lines.append("- unavailable")

    heartbeat_age = heartbeat.get("age_seconds")
    heartbeat_age_text = (
        "unknown" if heartbeat_age is None else f"{float(heartbeat_age):.0f}s"
    )
    lines.append(
        f"Runner heartbeat: {heartbeat.get('verdict', 'UNKNOWN')} "
        f"age={heartbeat_age_text}"
    )
    reconciliation = database_state.get("reconciliation")
    if reconciliation:
        lines.append(
            f"Reconciliation: {'CLEAN' if reconciliation['clean'] else 'DIRTY'} "
            f"at={reconciliation['run_ts']} "
            f"flags={_compact_json(reconciliation.get('flags', []), 240)}"
        )
    else:
        lines.append("Reconciliation: unavailable")

    if recovered:
        lines.append("Recovered conditions:")
        for event in recovered[:10]:
            lines.append(
                f"- {event.get('component', 'unknown')}/{event.get('error_type', 'unknown')}"
                f"{'/' + str(event['bot_id']) if event.get('bot_id') else ''}"
            )
    else:
        lines.append("Recovered conditions: none")

    if not database_state["readable"]:
        lines.append("Database reads: unavailable")
    if report.get("error"):
        lines.append(f"Invariant evaluation error: {report['error']}")

    return "\n".join(lines)[:1900]


def notify_daily_health_digest() -> None:
    """Build and deliver the daily health digest through the shared policy."""
    title = "Daily platform health digest"
    audit_id = _audit_start("daily_health_digest", title)
    try:
        content = build_daily_health_digest()
    except Exception as exc:
        _audit_finish(audit_id, "failed", error=type(exc).__name__)
        logger.warning(f"Discord | daily health digest build failed: {type(exc).__name__}")
        return
    _send(
        {"content": content},
        event_id=audit_id,
        alert_type="daily_health_digest",
        title=title,
    )
    logger.info("Discord | daily health digest prepared")


def is_configured() -> bool:
    return bool(_WEBHOOK_URL)
