"""Lightweight read-only watchdog for the canonical active fleet."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from db.postgres import get_conn, is_pg_available

ACTIVE_BOTS = ("oracle", "spy_qqq_trend", "jerome_macro")
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_MICRO_AUDIT_FILE = _LOG_DIR / "micro_audit.json"
_MICRO_AUDIT_HISTORY = _LOG_DIR / "micro_audit_history.json"
_MAX_HISTORY = 200
_lock = threading.Lock()


def _run_micro_audit_inner(escalate_to_gemini: bool = False) -> dict[str, Any]:
    start = time.time()
    alerts: list[dict[str, Any]] = []
    bots: list[dict[str, Any]] = []

    if not is_pg_available():
        alerts.append({"check": "database", "severity": "HIGH",
                       "detail": "Canonical database is unavailable"})
    else:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_id in ACTIVE_BOTS:
                    cur.execute("""
                        SELECT bs.paused, bs.status, bs.error_message,
                               bch.cycle_count, bch.consecutive_failures,
                               bch.last_success_at, bp.equity_usd
                        FROM bots_state bs
                        LEFT JOIN bot_cycle_health bch ON bch.bot_id = bs.bot_id
                        LEFT JOIN bot_portfolio bp ON bp.bot_id = bs.bot_id
                        WHERE bs.bot_id = %s
                    """, (bot_id,))
                    row = cur.fetchone()
                    if not row:
                        alerts.append({"check": "state", "bot": bot_id,
                                       "severity": "HIGH",
                                       "detail": "Missing canonical bot state"})
                        continue
                    paused, status, error, cycles, failures, last_success, equity = row
                    bot_status = "PAUSED" if paused else (
                        "FAIL" if error or (failures or 0) > 0 else
                        "UNKNOWN" if (cycles or 0) <= 0 or equity is None else "HEALTHY"
                    )
                    bots.append({
                        "bot_id": bot_id,
                        "status": bot_status,
                        "cycle_count": cycles or 0,
                        "consecutive_failures": failures or 0,
                        "last_success_at": last_success.isoformat() if last_success else None,
                        "equity_usd": float(equity) if equity is not None else None,
                    })
                    if bot_status == "FAIL":
                        alerts.append({"check": "cycle_failure", "bot": bot_id,
                                       "severity": "HIGH",
                                       "detail": error or f"{failures} consecutive cycle failures"})
                    elif bot_status == "UNKNOWN":
                        alerts.append({"check": "missing_monitoring_data", "bot": bot_id,
                                       "severity": "MEDIUM",
                                       "detail": "No completed cycle or equity value"})

    high_count = sum(a["severity"] == "HIGH" for a in alerts)
    medium_count = sum(a["severity"] == "MEDIUM" for a in alerts)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - start, 2),
        "bots": bots,
        "alerts": alerts,
        "alert_count": len(alerts),
        "high_count": high_count,
        "medium_count": medium_count,
        "escalated_to_gemini": False,
        "status": "ALERT" if alerts else "CLEAN",
    }
    try:
        _MICRO_AUDIT_FILE.write_text(json.dumps(result, indent=2))
        history = json.loads(_MICRO_AUDIT_HISTORY.read_text()) if _MICRO_AUDIT_HISTORY.exists() else []
        history = (history if isinstance(history, list) else []) + [result]
        _MICRO_AUDIT_HISTORY.write_text(json.dumps(history[-_MAX_HISTORY:], indent=2))
    except Exception as exc:
        logger.debug("MicroAuditor | log write failed: %s", exc)
    logger.info(f"MicroAuditor | {result['status']} | {len(alerts)} alert(s)")
    return result


def run_micro_audit(escalate_to_gemini: bool = True) -> dict[str, Any]:
    """Public scheduler/API entry point; escalation is intentionally inert in DEV."""
    with _lock:
        return _run_micro_audit_inner(escalate_to_gemini)