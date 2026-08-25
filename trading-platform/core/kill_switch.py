"""Fail-closed fleet safety checks and broker/ledger reconciliation.

This module is deliberately separate from strategy and order placement code.
It reads broker state, pauses bots on a confirmed trip, and cancels only
non-protective pending orders.  It never liquidates positions.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from config.settings import settings
from core.symbols import canonical_symbol, same_symbol
from core.bot_config import load_bot_profiles

DUST_QTY = 1e-6
MISSING_STOP_SECONDS = 60.0
MISMATCH_REQUIRED_CHECKS = 2
RESET_CONFIRMATION = "RESET-KILL-SWITCH"
ACTIVE_BOTS = ("oracle", "spy_qqq_trend", "jerome_macro")
ACCOUNT_ENV = {
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}
_BOT_PROFILE_KEYS = {
    "oracle": "oracle",
    "spy_qqq_trend": "bot2_spy_qqq",
    "jerome_macro": "jerome_macro",
}
_BOT_PROFILES = load_bot_profiles()
MAX_DEPLOYMENT = {
    bot_id: float(_BOT_PROFILES[_BOT_PROFILE_KEYS[bot_id]]["MAX_DEPLOYMENT"])
    for bot_id in ACTIVE_BOTS
}

_state: dict[str, Any] = {
    "tripped": False,
    "last_snapshot": {},
    "missing_stop_since": {},
    "mismatch_counts": {},
}


def _now() -> float:
    return time.time()


def _is_protective(order: dict[str, Any]) -> bool:
    side = str(order.get("side", "")).lower()
    order_type = str(order.get("type", "")).lower()
    return order_type in {"stop", "stop_limit", "trailing_stop"} and side in {"sell", "buy"}


def _covers(position: dict[str, Any], order: dict[str, Any]) -> bool:
    if not _is_protective(order) or not same_symbol(position.get("symbol"), order.get("symbol")):
        return False
    position_side = str(position.get("side", "long")).lower()
    order_side = str(order.get("side", "")).lower()
    expected = "sell" if position_side != "short" else "buy"
    return order_side == expected and float(order.get("qty") or 0) + DUST_QTY >= abs(float(position.get("qty") or 0))


def _vault_symbols(bot_id: str) -> set[str]:
    """Return vault-owned symbols from the durable vault holdings table."""
    try:
        # Vault activation/holdings are maintained in the authoritative Neon
        # database, while the legacy platform DB may contain an empty table.
        # Read the same durable source regardless of which DB backs the
        # surrounding platform connection.
        import os
        import psycopg2
        dsn = os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("no database URL configured")
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol FROM per_bot_vault_holdings WHERE bot_id = %s",
                    (bot_id,),
                )
                return {canonical_symbol(row[0]) for row in cur.fetchall()}
    except Exception as exc:
        logger.warning(f"Kill switch | vault holdings lookup failed for {bot_id}: {exc}")
        return set()


def evaluate_account(account: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """Return trigger records for one normalized account snapshot."""
    now = _now() if now is None else now
    bot_id = account["bot_id"]
    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    lmv = float(account.get("long_market_value") or 0)
    triggers: list[dict[str, Any]] = []

    if cash < 0:
        triggers.append({"trigger": "negative_cash", "detail": f"cash={cash:.2f}"})
    if equity > 0 and lmv > equity + 1e-6:
        triggers.append({"trigger": "leverage", "detail": f"lmv={lmv:.2f} equity={equity:.2f}"})

    deployed_pct = lmv / equity if equity > 0 else 1.0
    max_deployment = float(account.get("max_deployment", MAX_DEPLOYMENT.get(bot_id, 0.80)))
    if deployed_pct > max_deployment + 0.05 and not account.get("deployment_acknowledged", False):
        triggers.append({
            "trigger": "deployment",
            "detail": f"deployed={deployed_pct:.4f} max={max_deployment:.4f} tolerance=0.05",
        })

    vault_symbols = _vault_symbols(bot_id)
    for position in account.get("positions", []):
        qty = abs(float(position.get("qty") or 0))
        if qty < DUST_QTY:
            _state["missing_stop_since"].pop(f"{bot_id}:{position.get('symbol')}", None)
            continue
        if canonical_symbol(position.get("symbol")) in vault_symbols:
            _state["missing_stop_since"].pop(f"{bot_id}:{position.get('symbol')}", None)
            continue
        covered = any(_covers(position, order) for order in account.get("orders", []))
        key = f"{bot_id}:{position.get('symbol')}"
        if covered:
            _state["missing_stop_since"].pop(key, None)
        else:
            first_seen = _state["missing_stop_since"].setdefault(key, now)
            if now - first_seen > MISSING_STOP_SECONDS:
                triggers.append({
                    "trigger": "missing_protective_stop",
                    "detail": f"{position.get('symbol')} unprotected for {now - first_seen:.1f}s",
                })

    return triggers


def evaluate_snapshot(snapshot: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    """Evaluate all pure safety rules without side effects."""
    triggers: list[dict[str, Any]] = []
    for account in snapshot.get("accounts", []):
        triggers.extend(evaluate_account(account, now=now))

    current = float(snapshot.get("fleet_equity") or 0)
    hwm = float(snapshot.get("fleet_hwm") or current)
    threshold = float(getattr(settings, "kill_switch_drawdown_pct", 0.15))
    if hwm > 0 and (hwm - current) / hwm > threshold:
        triggers.append({
            "trigger": "fleet_drawdown",
            "detail": f"fleet={current:.2f} hwm={hwm:.2f} threshold={threshold:.4f}",
        })

    for mismatch in snapshot.get("mismatches", []):
        key = json.dumps(mismatch, sort_keys=True, default=str)
        count = _state["mismatch_counts"].get(key, 0) + 1
        _state["mismatch_counts"][key] = count
        if count >= MISMATCH_REQUIRED_CHECKS:
            triggers.append({"trigger": "broker_ledger_mismatch", **mismatch})

    for disagreement in snapshot.get("pause_state_disagreements", []):
        triggers.append({"trigger": "pause_state_disagreement", **disagreement})

    for finding in snapshot.get("account_findings", []):
        triggers.append({"trigger": "missing_account", **finding})

    # Liveness is collected with the live broker snapshot. Keeping it in the
    # snapshot makes this evaluator pure and prevents synthetic/unit snapshots
    # from silently querying a real database.
    triggers.extend(snapshot.get("liveness_findings", []))

    return triggers


def _db_call(fn: Callable, default: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        logger.warning(f"Kill switch | database read failed: {exc}")
        return default


def _load_acknowledgements() -> dict[str, bool]:
    def query() -> dict[str, bool]:
        from db.postgres import get_conn
        result: dict[str, bool] = {}
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT condition_key FROM kill_switch_acknowledgements "
                    "WHERE acknowledged_until > NOW()"
                )
                result.update({str(row[0]): True for row in cur.fetchall()})
        return result
    return _db_call(query, {})


def _write_event(trigger: str, snapshot: dict[str, Any], action: str) -> None:
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kill_switch_events "
                    "(trigger, account, snapshot, action_taken) VALUES (%s,%s,%s::jsonb,%s)",
                    (trigger, snapshot.get("account"), json.dumps(snapshot, default=str), action),
                )
    except Exception as exc:
        logger.critical(f"Kill switch | event persistence failed: {exc}")


def _set_all_paused(reason: str) -> None:
    from core.bot_state import set_paused
    for bot_id in ACTIVE_BOTS:
        set_paused(bot_id, True, reason=reason)


def _cancel_non_protective(snapshot: dict[str, Any]) -> int:
    cancelled = 0
    for account in snapshot.get("accounts", []):
        client = account.get("_client")
        if client is None:
            continue
        for order in account.get("orders", []):
            if _is_protective(order):
                continue
            try:
                client.cancel_order_by_id(str(order["id"]))
                cancelled += 1
            except Exception as exc:
                logger.critical(f"Kill switch | failed cancelling pending order {order.get('id')}: {exc}")
    return cancelled


def trip(triggers: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Latch the switch, pause all bots, and cancel only non-stop orders."""
    _state["tripped"] = True
    reason = "; ".join(str(t.get("trigger")) for t in triggers)
    _set_all_paused(reason)
    cancelled = _cancel_non_protective(snapshot)
    action = f"paused_all_bots;cancelled_non_protective={cancelled};protective_stops_preserved"
    for trigger in triggers:
        logger.critical(f"KILL SWITCH TRIGGERED | {trigger}")
        _write_event(str(trigger.get("trigger")), snapshot, action)
    return {"tripped": True, "triggers": triggers, "cancelled": cancelled, "action": action}


def reset(opening_equity: float | None = None, confirmation_token: str | None = None) -> None:
    if _state["tripped"] and confirmation_token != RESET_CONFIRMATION:
        raise ValueError(f"Explicit confirmation token required: {RESET_CONFIRMATION}")
    _state["tripped"] = False
    _state["last_snapshot"] = {}
    _state["missing_stop_since"] = {}
    _state["mismatch_counts"] = {}
    logger.warning("Kill switch manually reset after explicit confirmation")


def is_tripped() -> bool:
    return bool(_state["tripped"])


def manual_trip(reason: str = "manual_emergency") -> dict[str, Any]:
    """Trip without a broker snapshot; retained for the manual control route."""
    return trip([{"trigger": "manual", "detail": reason}], {"reason": reason})


def get_state() -> dict[str, Any]:
    return {
        "tripped": bool(_state["tripped"]),
        "reset_confirmation": RESET_CONFIRMATION,
        "missing_stop_seconds": MISSING_STOP_SECONDS,
        "last_snapshot": _state.get("last_snapshot", {}),
    }


def acknowledge(
    condition_key: str,
    until: str,
    acknowledged_by: str = "manual",
    reason: str | None = None,
) -> dict[str, Any]:
    """Record an explicit, expiring acknowledgement for a known condition."""
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kill_switch_acknowledgements "
                    "(condition_key, acknowledged_until, acknowledged_by, reason) "
                    "VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (condition_key) DO UPDATE SET "
                    "acknowledged_until=EXCLUDED.acknowledged_until, "
                    "acknowledged_by=EXCLUDED.acknowledged_by, "
                    "reason=EXCLUDED.reason, acknowledged_at=NOW()",
                    (condition_key, until, acknowledged_by, reason),
                )
        return {
            "condition_key": condition_key,
            "acknowledged_until": until,
            "acknowledged_by": acknowledged_by,
            "reason": reason,
        }
    except Exception as exc:
        raise RuntimeError(f"Could not save acknowledgement: {exc}") from exc


def report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Evaluate without pausing, cancelling, or persisting a trip."""
    triggers = evaluate_snapshot(snapshot)
    public_snapshot = {
        key: [
            {k: v for k, v in item.items() if k != "_client"}
            for item in value
        ] if key == "accounts" else value
        for key, value in snapshot.items()
    }
    result = {"mode": "report_only", "would_trip": bool(triggers), "triggers": triggers, "snapshot": public_snapshot}
    _state["last_snapshot"] = result
    logger.warning(f"Kill switch report-only | would_trip={bool(triggers)} triggers={len(triggers)}")
    return result


def check(current_equity: float | None = None) -> bool:
    """Compatibility check used by existing pipeline guards; never liquidates."""
    if _state["tripped"]:
        return True
    return False


def run_report_only() -> dict[str, Any]:
    """Run a safe live-state report using broker reads only."""
    from execution.reconciliation import collect_live_snapshot
    return report(collect_live_snapshot())