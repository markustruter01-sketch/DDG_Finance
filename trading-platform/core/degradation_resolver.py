"""Condition-based lifecycle management for system degradation events.

This module is deliberately read-heavy and trading-blind.  It reads the latest
broker-backed reconciliation snapshot plus canonical database health state, and
only writes ``resolved_at``/``resolved_reason`` when a condition is proven to
have cleared.  It never calls an order, position, stop, or strategy function.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from core.bot_liveness import PORTFOLIO_STALE_THRESHOLDS


RESOLVABLE_ERROR_TYPES = (
    "bot_stale_workflow",
    "broker_stop_rejected",
    "close_position_failed",
    "entry_empty_response_guard",
    "entry_order_failed",
    "protective_stop_failed",
    "reconciliation_mismatch",
    "stop_placement_failed",
    "stop_sweep_placement_failed",
)

STOP_ERROR_TYPES = {
    "broker_stop_rejected",
    "protective_stop_failed",
    "stop_placement_failed",
    "stop_sweep_placement_failed",
}

BOT_ALIASES = {
    "bot2_spy_qqq": "spy_qqq_trend",
    "spy_qqq_trend": "spy_qqq_trend",
    "oracle": "oracle",
    "jerome_macro": "jerome_macro",
    "buck_futures": "jerome_macro",
    "bot/oracle": "oracle",
    "bot/spy_qqq_trend": "spy_qqq_trend",
    "bot/jerome_macro": "jerome_macro",
}


def _canonical_bot(row: dict[str, Any]) -> str | None:
    """Infer a canonical bot only from durable identity fields."""
    raw = row.get("bot_id")
    if raw:
        return BOT_ALIASES.get(str(raw), str(raw))
    component = str(row.get("component") or "")
    if component in BOT_ALIASES:
        return BOT_ALIASES[component]
    for prefix, canonical in (
        ("bot/", None),
        ("oracle_", "oracle"),
        ("oracle", "oracle"),
        ("jerome_macro", "jerome_macro"),
        ("bot2_spy_qqq", "spy_qqq_trend"),
    ):
        if component.startswith(prefix):
            return canonical or BOT_ALIASES.get(component)
    return None


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _latest_reconciliation(conn) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_ts, clean, flags, snapshot
            FROM reconciliation_log
            ORDER BY run_ts DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "run_ts": row[0],
        "clean": row[1],
        "flags": row[2] or [],
        "snapshot": row[3] or {},
    }


def _read_state() -> dict[str, Any]:
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        raise RuntimeError("PostgreSQL is unavailable; resolver fails closed")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ts, component, severity, error_type, message,
                       detail, resolved_at, bot_id, cycle_id
                FROM system_degradations
                WHERE resolved_at IS NULL
                  AND lower(severity) IN ('high', 'critical', 'error')
                ORDER BY ts ASC, id ASC
                """
            )
            events = [
                dict(zip([desc[0] for desc in cur.description], row))
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT bot_id, paused, status
                FROM bots_state
                WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                """
            )
            pauses = {
                row[0]: {"paused": row[1], "status": row[2]}
                for row in cur.fetchall()
            }

            cur.execute(
                """
                SELECT bot_id, last_updated
                FROM bot_portfolio
                WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                """
            )
            portfolios = {
                row[0]: {"last_updated": row[1]}
                for row in cur.fetchall()
            }

            cur.execute(
                """
                SELECT bot_id, last_success_at, status, consecutive_failures
                FROM bot_cycle_health
                WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                """
            )
            cycles = {
                row[0]: {
                    "last_success_at": row[1],
                    "status": row[2],
                    "consecutive_failures": row[3],
                }
                for row in cur.fetchall()
            }

        reconciliation = _latest_reconciliation(conn)

    return {
        "events": events,
        "pauses": pauses,
        "portfolios": portfolios,
        "cycles": cycles,
        "reconciliation": reconciliation,
        "checked_at": datetime.now(timezone.utc),
    }


def _reconciliation_is_clean(state: dict[str, Any]) -> bool:
    row = state.get("reconciliation")
    if not row or row.get("clean") is not True:
        return False
    run_ts = _parse_ts(row.get("run_ts"))
    if run_ts is None:
        return False
    # This is a freshness guard, not a resolution criterion by itself.
    age_seconds = (state["checked_at"] - run_ts).total_seconds()
    return 0 <= age_seconds <= 90 * 60


def _invariant_passed(state: dict[str, Any], name: str) -> bool:
    """Require an explicit current PASS; absent/unknown evidence is not enough."""
    return state.get("invariants", {}).get(name) == "PASS"


def _bot_cycle_recovered(state: dict[str, Any], bot_id: str | None) -> bool:
    if not bot_id:
        return False
    pause = state["pauses"].get(bot_id)
    if pause is None:
        return False
    if bool(pause["paused"]):
        return True
    cycle = state["cycles"].get(bot_id)
    if not cycle or str(cycle.get("status") or "").lower() != "success":
        return False
    return _parse_ts(cycle.get("last_success_at")) is not None


def resolution_for_event(
    event: dict[str, Any],
    state: dict[str, Any],
) -> str | None:
    """Return an auditable reason only when live evidence clears the event."""
    error_type = str(event.get("error_type") or "")
    if error_type not in RESOLVABLE_ERROR_TYPES:
        return None

    bot_id = _canonical_bot(event)
    pause = state["pauses"].get(bot_id) if bot_id else None

    if error_type == "bot_stale_workflow":
        if pause is None:
            return None
        if bool(pause["paused"]):
            return "database pause is active; paused bots are not stale"
        portfolio = state["portfolios"].get(bot_id)
        updated = _parse_ts(portfolio.get("last_updated")) if portfolio else None
        if updated is None:
            return None
        age = (state["checked_at"] - updated).total_seconds()
        threshold = PORTFOLIO_STALE_THRESHOLDS.get(bot_id)
        if threshold is not None and 0 <= age <= threshold:
            return f"portfolio heartbeat recovered within {threshold}s threshold"
        return None

    if error_type in STOP_ERROR_TYPES:
        if (
            _invariant_passed(state, "strategy_positions_have_covering_stops")
            and _reconciliation_is_clean(state)
        ):
            return "stop-coverage invariant PASS and latest reconciliation is clean"
        return None

    if error_type == "reconciliation_mismatch":
        if _reconciliation_is_clean(state):
            return "later broker/ledger reconciliation completed cleanly"
        return None

    if error_type == "entry_empty_response_guard":
        if pause and bool(pause["paused"]):
            return "database pause is active; entry scanning is intentionally off"
        if _bot_cycle_recovered(state, bot_id) and _reconciliation_is_clean(state):
            return "bot cycle recovered and latest broker/ledger reconciliation is clean"
        return None

    if error_type in {"entry_order_failed", "close_position_failed"}:
        if _bot_cycle_recovered(state, bot_id):
            return "bot is paused or has a successful current cycle after the failure"
        return None

    return None


def _dry_run_default() -> bool:
    """Never mutate development rows merely because the scheduler restarted."""
    return os.environ.get(
        "DEGRADATION_RESOLVER_DRY_RUN",
        "0" if os.environ.get("REPLIT_DEPLOYMENT") == "1" else "1",
    ).strip().lower() not in {"0", "false", "no", "off"}


def run_degradation_resolver(*, dry_run: bool | None = None) -> dict[str, Any]:
    """Evaluate all open high-severity rows and optionally resolve recovered ones."""
    from core.degradation_tracker import mark_resolved

    dry_run = _dry_run_default() if dry_run is None else dry_run
    state = _read_state()
    from core.invariants import run_all_invariants

    invariant_report = run_all_invariants(now=state["checked_at"])
    state["invariants"] = {
        str(result["name"]): str(result["status"])
        for result in invariant_report.get("results", [])
    }
    candidates: list[dict[str, Any]] = []
    for event in state["events"]:
        reason = resolution_for_event(event, state)
        if reason:
            candidates.append({"event": event, "reason": reason})

    resolved = 0
    if not dry_run:
        for candidate in candidates:
            event = candidate["event"]
            resolved += mark_resolved(
                str(event["component"]),
                str(event["error_type"]),
                candidate["reason"],
                event_id=int(event["id"]),
                bot_id=str(event["bot_id"]) if event.get("bot_id") else None,
            )

    by_type: dict[str, int] = {}
    reasons: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        error_type = str(candidate["event"]["error_type"])
        by_type[error_type] = by_type.get(error_type, 0) + 1
        reason = candidate["reason"]
        reasons.setdefault(error_type, {})[reason] = reasons.setdefault(error_type, {}).get(reason, 0) + 1

    result = {
        "dry_run": dry_run,
        "checked": len(state["events"]),
        "would_resolve": len(candidates),
        "resolved": resolved,
        "by_error_type": by_type,
        "reasons": reasons,
        "checked_at": state["checked_at"].isoformat(),
    }
    logger.info(f"DegradationResolver | {json.dumps(result, sort_keys=True)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve cleared degradation events.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run_degradation_resolver(dry_run=True if args.dry_run else None)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())