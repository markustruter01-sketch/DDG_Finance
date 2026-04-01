"""
Alert Manager — Batched Profitable Trade Notifications
-------------------------------------------------------
Aggregates profitable trade closures and sends batched alerts
via Telegram (and Discord if configured) at a configurable interval.

Default: 1 alert batch per hour, adjustable 5min–24h from the dashboard.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_CONFIG_FILE = Path("data/alert_config.json")
_QUEUE_FILE = Path("data/alert_queue.json")
_lock = threading.Lock()
_timer: threading.Timer | None = None

DEFAULT_CONFIG = {
    "enabled": True,
    "interval_minutes": 60,
    "telegram_enabled": True,
    "discord_enabled": True,
    "min_pnl_pct": 0.0,
    "min_pnl_usd": 0.0,
}


def _ensure_data_dir() -> None:
    Path("data").mkdir(exist_ok=True)


def get_config() -> dict[str, Any]:
    _ensure_data_dir()
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE) as f:
                stored = json.load(f)
            merged = {**DEFAULT_CONFIG, **stored}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    _ensure_data_dir()
    merged = {**DEFAULT_CONFIG, **cfg}
    if "interval_minutes" in merged:
        merged["interval_minutes"] = max(5, min(1440, int(merged["interval_minutes"])))
    with open(_CONFIG_FILE, "w") as f:
        json.dump(merged, f, indent=2)
    _restart_flush_timer()
    return merged


def _load_queue() -> list[dict[str, Any]]:
    if _QUEUE_FILE.exists():
        try:
            with open(_QUEUE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_queue(queue: list[dict[str, Any]]) -> None:
    _ensure_data_dir()
    with open(_QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def enqueue_profitable_trade(
    bot_name: str,
    symbol: str,
    pnl_pct: float,
    pnl_usd: float,
    side: str = "SELL",
    reason: str = "",
) -> None:
    cfg = get_config()
    if not cfg.get("enabled", True):
        return
    if pnl_pct < cfg.get("min_pnl_pct", 0):
        return
    if pnl_usd < cfg.get("min_pnl_usd", 0):
        return

    entry = {
        "bot_name": bot_name,
        "symbol": symbol,
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "side": side,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        queue = _load_queue()
        queue.append(entry)
        _save_queue(queue)

    logger.info(f"Alert queued: {bot_name} {symbol} +{pnl_pct:.2f}% (${pnl_usd:,.2f})")


def flush_alerts() -> int:
    with _lock:
        queue = _load_queue()
        if not queue:
            return 0

    cfg = get_config()
    count = len(queue)
    tg_ok = False
    dc_ok = False

    if cfg.get("telegram_enabled", True):
        try:
            from notifications.telegram import send_batch_summary, is_configured as tg_configured
            if tg_configured():
                send_batch_summary(queue)
                tg_ok = True
                logger.info(f"Telegram alert sent: {count} trades")
        except Exception as exc:
            logger.warning(f"Telegram flush failed: {exc}")

    if cfg.get("discord_enabled", True):
        try:
            from notifications.discord import is_configured as dc_configured, _send_async, _embed, COLOR_GREEN, COLOR_PURPLE
            if dc_configured():
                total_pnl = sum(a.get("pnl_usd", 0) for a in queue)
                fields = [
                    {"name": "Trades", "value": str(count), "inline": True},
                    {"name": "Total P&L", "value": f"${total_pnl:,.2f}", "inline": True},
                ]
                lines = []
                for a in queue[:8]:
                    lines.append(f"**{a['symbol']}** ({a['bot_name']}): +{a['pnl_pct']:.2f}%")
                desc = "\n".join(lines) or "Profitable trades summary"
                _send_async({"embeds": [_embed("\U0001f4b0 Profitable Trades Summary", desc, COLOR_GREEN, fields)]})
                dc_ok = True
                logger.info(f"Discord alert sent: {count} trades")
        except Exception as exc:
            logger.warning(f"Discord flush failed: {exc}")

    if tg_ok or dc_ok:
        with _lock:
            _save_queue([])
    else:
        logger.warning(f"Alert flush: no channels succeeded — {count} alerts retained in queue")

    return count


def _flush_timer_callback() -> None:
    try:
        flushed = flush_alerts()
        if flushed > 0:
            logger.info(f"Scheduled alert flush: {flushed} alerts sent")
    except Exception as exc:
        logger.warning(f"Alert flush timer error: {exc}")
    finally:
        _restart_flush_timer()


def _restart_flush_timer() -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
    cfg = get_config()
    if not cfg.get("enabled", True):
        return
    interval_sec = cfg.get("interval_minutes", 60) * 60
    _timer = threading.Timer(interval_sec, _flush_timer_callback)
    _timer.daemon = True
    _timer.start()


def start_alert_scheduler() -> None:
    logger.info("Alert manager scheduler started")
    _restart_flush_timer()


def get_queue_status() -> dict[str, Any]:
    with _lock:
        queue = _load_queue()
    cfg = get_config()
    from notifications.telegram import is_configured as tg_ok
    from notifications.discord import is_configured as dc_ok
    return {
        "queue_size": len(queue),
        "config": cfg,
        "telegram_configured": tg_ok(),
        "discord_configured": dc_ok(),
        "pending_alerts": queue[-5:] if queue else [],
    }
