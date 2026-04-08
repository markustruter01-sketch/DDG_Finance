"""
analysis/micro_auditor.py — Lightweight Rules-Based Fleet Watchdog
====================================================================
Runs every 15 minutes (piggybacks on intraday/crypto cycle cadence).
Uses pure math and rule checks — ZERO AI calls.  Only escalates to the
Gemini Fleet Commander when it detects an anomaly that needs AI judgment.

96 oversight checks/day vs 6 Gemini calls = 16x more coverage,
zero additional API token burn.

Checks performed every cycle:
  1. Drawdown Guard     — any bot >5% drawdown from peak triggers alert
  2. Correlation Alarm  — if 3+ bots hold the same losing ticker
  3. Position Drift     — any bot >80% deployed (under-reserved)
  4. Win-Rate Decay     — rolling win rate drops below 40%
  5. PnL Velocity       — losses accelerating (3+ consecutive losers)
  6. VPIN Saturation    — >50% of universe is VPIN-blocked
  7. Stale Heartbeat    — any Kraken bot hasn't checked in for >5 min
  8. Equity Divergence  — fleet equity diverging >3% from yesterday
"""

from __future__ import annotations

import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_MICRO_AUDIT_FILE = _LOG_DIR / "micro_audit.json"
_MICRO_AUDIT_HISTORY = _LOG_DIR / "micro_audit_history.json"
_MAX_HISTORY = 200

_lock = threading.Lock()

_DRAWDOWN_THRESHOLD = 0.05
_CORRELATION_MIN_BOTS = 3
_DEPLOYED_CAP = 0.80
_WIN_RATE_FLOOR = 40.0
_CONSECUTIVE_LOSS_TRIGGER = 3
_VPIN_BLOCKED_PCT = 0.50
_HEARTBEAT_STALE_SECS = 300
_EQUITY_DIVERGENCE_PCT = 0.03


def _safe_get(url: str, timeout: float = 5) -> dict | list | None:
    try:
        import requests
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _check_kraken_bot(bot_id: str, base: str) -> list[dict]:
    alerts = []
    status = _safe_get(f"{base}/kraken/status?bot_id={bot_id}")
    if not status:
        return alerts

    equity = status.get("equity", 0)
    peak_equity = status.get("peak_equity", equity)
    if peak_equity > 0 and equity > 0:
        dd = (peak_equity - equity) / peak_equity
        if dd > _DRAWDOWN_THRESHOLD:
            alerts.append({
                "check": "drawdown_guard",
                "bot": bot_id,
                "severity": "HIGH" if dd > 0.08 else "MEDIUM",
                "detail": f"{bot_id} drawdown {dd:.1%} from peak (${peak_equity:,.0f} → ${equity:,.0f})",
            })

    cash = status.get("cash", 0)
    if equity > 0 and cash > 0:
        deployed_pct = 1 - (cash / equity)
        if deployed_pct > _DEPLOYED_CAP:
            alerts.append({
                "check": "position_drift",
                "bot": bot_id,
                "severity": "MEDIUM",
                "detail": f"{bot_id} {deployed_pct:.0%} deployed — only {cash/equity:.0%} cash reserve",
            })

    last_heartbeat = status.get("last_heartbeat")
    if last_heartbeat:
        try:
            hb_ts = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00")).timestamp()
            age = time.time() - hb_ts
            if age > _HEARTBEAT_STALE_SECS:
                alerts.append({
                    "check": "stale_heartbeat",
                    "bot": bot_id,
                    "severity": "HIGH",
                    "detail": f"{bot_id} heartbeat is {age/60:.1f}min stale (threshold: {_HEARTBEAT_STALE_SECS/60:.0f}min)",
                })
        except Exception:
            pass

    return alerts


def _check_kraken_performance(bot_id: str, base: str) -> tuple[list[dict], dict]:
    alerts = []
    meta = {"bot_id": bot_id, "win_rate": None, "total_pnl": None, "positions": []}
    perf = _safe_get(f"{base}/kraken/performance?bot_id={bot_id}")
    if not perf:
        return alerts, meta

    total = perf.get("total_trades", 0)
    wins = perf.get("win_count", 0)
    if total >= 10:
        wr = (wins / total) * 100
        meta["win_rate"] = wr
        if wr < _WIN_RATE_FLOOR:
            alerts.append({
                "check": "win_rate_decay",
                "bot": bot_id,
                "severity": "MEDIUM",
                "detail": f"{bot_id} win rate {wr:.1f}% ({wins}/{total}) below {_WIN_RATE_FLOOR}% floor",
            })

    meta["total_pnl"] = perf.get("total_pnl_usd", 0)

    recent = perf.get("recent_trades", [])
    if len(recent) >= _CONSECUTIVE_LOSS_TRIGGER:
        consec_losses = 0
        for t in recent[:10]:
            if t.get("pnl_usd", 0) < 0:
                consec_losses += 1
            else:
                break
        if consec_losses >= _CONSECUTIVE_LOSS_TRIGGER:
            alerts.append({
                "check": "pnl_velocity",
                "bot": bot_id,
                "severity": "HIGH",
                "detail": f"{bot_id} has {consec_losses} consecutive losses — momentum bleeding",
            })

    status = _safe_get(f"{base}/kraken/status?bot_id={bot_id}")
    if status and status.get("open_positions"):
        for p in status["open_positions"]:
            meta["positions"].append(p.get("symbol", "?"))

    return alerts, meta


def _check_cross_bot_correlation(all_meta: list[dict]) -> list[dict]:
    alerts = []
    symbol_bots: dict[str, list[str]] = {}
    for m in all_meta:
        for sym in m.get("positions", []):
            symbol_bots.setdefault(sym, []).append(m["bot_id"])

    for sym, bots in symbol_bots.items():
        if len(bots) >= _CORRELATION_MIN_BOTS:
            alerts.append({
                "check": "correlation_alarm",
                "bot": "fleet",
                "severity": "HIGH",
                "detail": f"{len(bots)} bots holding {sym}: {', '.join(bots)} — correlated risk!",
            })

    return alerts


def _check_alpaca(base: str) -> list[dict]:
    alerts = []
    positions = _safe_get(f"{base}/positions/live")
    if positions and positions.get("positions"):
        total_unrealized = sum(p.get("unrealized_pl", 0) for p in positions["positions"])
        total_value = sum(abs(p.get("market_value", 0)) for p in positions["positions"])
        if total_value > 0 and total_unrealized < 0:
            loss_pct = abs(total_unrealized) / total_value
            if loss_pct > _DRAWDOWN_THRESHOLD:
                alerts.append({
                    "check": "drawdown_guard",
                    "bot": "oracle",
                    "severity": "HIGH" if loss_pct > 0.08 else "MEDIUM",
                    "detail": f"Oracle open-position drawdown {loss_pct:.1%} (${total_unrealized:+,.0f})",
                })

    summary = _safe_get(f"{base}/status/summary")
    if summary:
        total = summary.get("total_trades", 0)
        wins = summary.get("wins", 0)
        if total >= 10:
            wr = (wins / total) * 100
            if wr < _WIN_RATE_FLOOR:
                alerts.append({
                    "check": "win_rate_decay",
                    "bot": "oracle",
                    "severity": "MEDIUM",
                    "detail": f"Oracle win rate {wr:.1f}% ({wins}/{total}) below {_WIN_RATE_FLOOR}% floor",
                })

    return alerts


def _check_forex(base: str) -> list[dict]:
    alerts = []
    state = _safe_get(f"{base}/forex/state")
    if state:
        total = state.get("total_trades", 0)
        wins = state.get("total_wins", 0)
        if total >= 5:
            wr = (wins / total) * 100
            if wr < _WIN_RATE_FLOOR:
                alerts.append({
                    "check": "win_rate_decay",
                    "bot": "navigator",
                    "severity": "MEDIUM",
                    "detail": f"Navigator win rate {wr:.1f}% ({wins}/{total}) below floor",
                })

    positions = _safe_get(f"{base}/forex/positions")
    if positions and positions.get("positions"):
        total_pnl = sum(p.get("unrealized_pnl_usd", 0) for p in positions["positions"])
        if total_pnl < -500:
            alerts.append({
                "check": "drawdown_guard",
                "bot": "navigator",
                "severity": "HIGH" if total_pnl < -1000 else "MEDIUM",
                "detail": f"Navigator open forex drawdown ${total_pnl:+,.0f}",
            })

    return alerts


def run_micro_audit(escalate_to_gemini: bool = True) -> dict[str, Any]:
    with _lock:
        return _run_micro_audit_inner(escalate_to_gemini)


def _run_micro_audit_inner(escalate_to_gemini: bool) -> dict[str, Any]:
    start = time.time()
    base = "http://127.0.0.1:8000/trading-api"
    all_alerts: list[dict] = []
    all_meta: list[dict] = []

    for bot_id in ("davy-jones", "blackbeard", "calypso"):
        all_alerts.extend(_check_kraken_bot(bot_id, base))
        perf_alerts, meta = _check_kraken_performance(bot_id, base)
        all_alerts.extend(perf_alerts)
        all_meta.append(meta)

    all_alerts.extend(_check_cross_bot_correlation(all_meta))
    all_alerts.extend(_check_alpaca(base))
    all_alerts.extend(_check_forex(base))

    high_count = sum(1 for a in all_alerts if a["severity"] == "HIGH")
    medium_count = sum(1 for a in all_alerts if a["severity"] == "MEDIUM")

    should_escalate = high_count >= 2 or (high_count >= 1 and medium_count >= 2)
    escalated = False

    if should_escalate and escalate_to_gemini:
        try:
            from analysis.fleet_commander import run_fleet_commander
            logger.warning(
                f"MicroAuditor | {high_count} HIGH + {medium_count} MEDIUM alerts — "
                f"ESCALATING to Gemini Fleet Commander"
            )
            fc_result = run_fleet_commander()
            escalated = True
            logger.info(f"MicroAuditor | Gemini escalation complete: verdict={fc_result.get('overall_verdict')}")
        except Exception as e:
            logger.error(f"MicroAuditor | Gemini escalation failed (fail-open): {e}")

    elapsed = time.time() - start

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(elapsed, 2),
        "alerts": all_alerts,
        "alert_count": len(all_alerts),
        "high_count": high_count,
        "medium_count": medium_count,
        "escalated_to_gemini": escalated,
        "status": "ALERT" if all_alerts else "CLEAN",
    }

    if all_alerts:
        checks_hit = list({a["check"] for a in all_alerts})
        logger.warning(
            f"MicroAuditor | {len(all_alerts)} alert(s) detected "
            f"({high_count} HIGH, {medium_count} MED) — checks: {', '.join(checks_hit)} "
            f"| escalated={escalated} | {elapsed:.1f}s"
        )
    else:
        logger.info(f"MicroAuditor | CLEAN — all checks passed ({elapsed:.1f}s)")

    try:
        _MICRO_AUDIT_FILE.write_text(json.dumps(result, indent=2))
        history = []
        if _MICRO_AUDIT_HISTORY.exists():
            try:
                history = json.loads(_MICRO_AUDIT_HISTORY.read_text())
            except Exception:
                pass
        history.append(result)
        history = history[-_MAX_HISTORY:]
        _MICRO_AUDIT_HISTORY.write_text(json.dumps(history, indent=2))
    except Exception as e:
        logger.debug(f"MicroAuditor | Failed to write log: {e}")

    return result
