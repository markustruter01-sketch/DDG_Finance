"""Read-only health scoring for the active trading fleet.

The monitor deliberately consumes the canonical operational tables rather
than maintaining a second health-snapshot store.  Empty monitoring data is
never treated as healthy: an active bot is UNKNOWN until its state and
cycle/portfolio data are present, while a paused bot is explicitly PAUSED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from db.postgres import get_conn, is_pg_available

ACTIVE_BOTS = ("oracle", "spy_qqq_trend", "jerome_macro")
_TRADE_ASSET_CLASSES = {
    "oracle": ("momentum_equity",),
    "spy_qqq_trend": ("momentum_etf",),
    "jerome_macro": ("macro_etf", "hard_assets"),
}

_latest_report: dict[str, Any] | None = None


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _one(cur, query: str, params: tuple = ()) -> dict[str, Any] | None:
    cur.execute(query, params)
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip((d[0] for d in cur.description), row))


def _load_bot(bot_id: str) -> dict[str, Any]:
    """Load only current-schema monitoring inputs for one canonical bot."""
    if not is_pg_available():
        return {
            "bot_id": bot_id,
            "status": "UNKNOWN",
            "reason": "PostgreSQL unavailable",
            "metrics": {},
        }

    with get_conn() as conn:
        with conn.cursor() as cur:
            state = _one(cur, """
                SELECT bot_id, paused, pause_reason, status, equity_usd, cash_usd,
                       open_positions, last_heartbeat, error_message
                FROM bots_state WHERE bot_id = %s
            """, (bot_id,))
            portfolio = _one(cur, """
                SELECT bot_id, equity_usd, cash_usd, positions, last_updated
                FROM bot_portfolio WHERE bot_id = %s
            """, (bot_id,))
            cycle = _one(cur, """
                SELECT bot_id, last_cycle_start, last_cycle_end, last_success_at,
                       cycle_count, consecutive_failures, last_error, status
                FROM bot_cycle_health WHERE bot_id = %s
            """, (bot_id,))
            cur.execute("""
                SELECT COUNT(*)::int, MAX(closed_at)
                FROM trades
                WHERE asset_class = ANY(%s)
            """, (list(_TRADE_ASSET_CLASSES[bot_id]),))
            trade_count, last_trade_at = cur.fetchone()
            cur.execute("""
                SELECT COUNT(*)::int, MAX(snapshot_ts)
                FROM fleet_equity_snapshots
                WHERE bot_id = %s
            """, (bot_id,))
            equity_count, last_equity_at = cur.fetchone()
            cur.execute("""
                SELECT COUNT(*)::int, MAX(ts)
                FROM system_degradations
                WHERE (component ILIKE %s OR message ILIKE %s)
                  AND resolved_at IS NULL
            """, (f"%{bot_id}%", f"%{bot_id}%"))
            degradation_count, last_degradation_at = cur.fetchone()

    metrics = {
        "state": "PRESENT" if state else "MISSING",
        "portfolio": "PRESENT" if portfolio else "MISSING",
        "cycle": "PRESENT" if cycle else "MISSING",
        "trades": {
            "count": trade_count or 0,
            "last_at": _iso(last_trade_at),
        },
        "equity_history": {
            "count": equity_count or 0,
            "last_at": _iso(last_equity_at),
        },
        "unresolved_degradations": {
            "count": degradation_count or 0,
            "last_at": _iso(last_degradation_at),
        },
    }

    # Pause is a first-class state.  Do not turn an intentionally empty paused
    # bot into an UNKNOWN/FAIL result.
    if (state and state.get("paused")) or (cycle and cycle.get("status") == "paused"):
        status = "PAUSED"
        reason = (state or {}).get("pause_reason") or "Paused"
    elif not state or not portfolio or not cycle:
        status = "UNKNOWN"
        reason = "Missing canonical state, portfolio, or cycle-health data"
    elif state.get("error_message") or cycle.get("last_error") or (
        (cycle.get("consecutive_failures") or 0) > 0
    ):
        status = "FAIL"
        reason = state.get("error_message") or cycle.get("last_error") or (
            f"{cycle.get('consecutive_failures')} consecutive cycle failures"
        )
    elif (cycle.get("cycle_count") or 0) <= 0 and (equity_count or 0) <= 0:
        status = "UNKNOWN"
        reason = "No completed cycles or equity snapshots"
    else:
        status = "HEALTHY"
        reason = "Canonical state and monitoring data present"

    return {
        "bot_id": bot_id,
        "status": status,
        "reason": reason,
        "score": {"HEALTHY": 100, "PAUSED": None, "UNKNOWN": None, "FAIL": 0}[status],
        "state": {
            key: _iso(value) if key in {"last_heartbeat", "last_trade_at"} else value
            for key, value in (state or {}).items()
        },
        "portfolio": {
            key: (_iso(value) if hasattr(value, "isoformat") else value)
            for key, value in (portfolio or {}).items()
            if key != "positions"
        },
        "cycle": {
            key: _iso(value) if key.endswith("_at") or key.endswith("_start") or key.endswith("_end")
            else value
            for key, value in (cycle or {}).items()
        },
        "metrics": metrics,
    }


def _unknown_metric(name: str, bot_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "bot_id": bot_id,
        "status": "UNKNOWN",
        "score": None,
        "reason": "No current monitoring rows available",
    }


def _check_symbol_concentration(bot_id: str) -> dict[str, Any]:
    """Compatibility metric; empty data is explicitly UNKNOWN."""
    # This legacy helper has no caller-provided sample.  Ambient database rows
    # are not a valid substitute for the metric snapshot under test.
    return _unknown_metric("symbol_concentration", bot_id)


def _check_loss_streak(bot_id: str) -> dict[str, Any]:
    """Compatibility metric; never reports HEALTHY without closed trades."""
    return _unknown_metric("loss_streak", bot_id)


def run_health_check() -> dict[str, Any]:
    """Return a fleet report without mutating database or broker state."""
    global _latest_report
    checked_at = datetime.now(timezone.utc).isoformat()
    bots = [_load_bot(bot_id) for bot_id in ACTIVE_BOTS]
    counts = {status: sum(1 for bot in bots if bot["status"] == status)
              for status in ("HEALTHY", "PAUSED", "UNKNOWN", "FAIL")}
    overall = "FAIL" if counts["FAIL"] else (
        "UNKNOWN" if counts["UNKNOWN"] else
        "HEALTHY" if all(bot["status"] in {"HEALTHY", "PAUSED"} for bot in bots)
        else "PAUSED"
    )
    _latest_report = {
        "checked_at": checked_at,
        "status": overall,
        "counts": counts,
        "bots": bots,
    }
    logger.info(f"HealthMonitor | {overall} | {counts}")
    return _latest_report


def get_health_report() -> dict[str, Any]:
    """Compatibility accessor used by API/report callers."""
    return dict(_latest_report or run_health_check())


def get_last_snapshot() -> dict[str, Any] | None:
    """Compatibility accessor; snapshots are intentionally not persisted."""
    return dict(_latest_report) if _latest_report else None


def health_check() -> dict[str, Any]:
    """Legacy entry point retained for scheduled callers."""
    return run_health_check()
