"""Read-only broker versus database reconciliation."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from core.kill_switch import ACCOUNT_ENV, ACTIVE_BOTS, DUST_QTY, MAX_DEPLOYMENT
from config.settings import settings


def _client_for(bot_id: str):
    from alpaca.trading.client import TradingClient
    key_name, secret_name = ACCOUNT_ENV[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing credentials for {bot_id}")
    return TradingClient(key, secret, paper=True)


def _orders(client) -> list[dict[str, Any]]:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    result = []
    for order in client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True, limit=500)):
        result.append({
            "id": str(order.id), "symbol": str(order.symbol), "side": getattr(order.side, "value", order.side),
            "type": getattr(order.type, "value", order.type), "qty": float(order.qty or 0),
        })
    return result


def _positions(client) -> list[dict[str, Any]]:
    return [{
        "symbol": str(p.symbol), "qty": float(p.qty), "side": getattr(p.side, "value", "long"),
        "market_value": float(p.market_value or 0),
    } for p in client.get_all_positions()]


def _ledger_positions(bot_id: str) -> list[dict[str, Any]]:
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT positions FROM bot_portfolio WHERE bot_id=%s", (bot_id,))
                row = cur.fetchone()
                if row and row[0]:
                    return row[0] if isinstance(row[0], list) else json.loads(row[0])
    except Exception as exc:
        logger.warning(f"Reconciliation | ledger read failed for {bot_id}: {exc}")
    return []


def _mismatches(bot_id: str, broker: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    b = {str(p.get("symbol", "")).replace("/", ""): abs(float(p.get("qty") or 0)) for p in broker if abs(float(p.get("qty") or 0)) >= DUST_QTY}
    l = {str(p.get("symbol", "")).replace("/", ""): abs(float(p.get("qty") or 0)) for p in ledger if abs(float(p.get("qty") or 0)) >= DUST_QTY}
    results = []
    for symbol in sorted(set(b) | set(l)):
        if symbol not in b:
            results.append({"bot_id": bot_id, "symbol": symbol, "kind": "ledger_without_broker"})
        elif symbol not in l:
            results.append({"bot_id": bot_id, "symbol": symbol, "kind": "broker_without_ledger"})
        elif abs(b[symbol] - l[symbol]) > DUST_QTY:
            results.append({"bot_id": bot_id, "symbol": symbol, "kind": "quantity_mismatch", "broker_qty": b[symbol], "ledger_qty": l[symbol]})
    return results


def _order_mismatches(bot_id: str, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare live order IDs with the durable stop/order ledger."""
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stop_order_id FROM ratchet_stops WHERE stop_order_id IS NOT NULL")
                ledger_ids = {str(row[0]) for row in cur.fetchall()}
                if bot_id == "oracle":
                    cur.execute(
                        "SELECT stop_order_id FROM alpaca_etf_positions "
                        "WHERE stop_order_id IS NOT NULL"
                    )
                    ledger_ids.update(str(row[0]) for row in cur.fetchall())
                if bot_id == "jerome_macro":
                    # Bot 3's crypto/ETF stop ownership is recorded in its
                    # dedicated ledger, not in the legacy ratchet table.
                    cur.execute(
                        "SELECT stop_order_id FROM bot3_positions "
                        "WHERE stop_order_id IS NOT NULL"
                    )
                    ledger_ids.update(str(row[0]) for row in cur.fetchall())
        return [
            {
                "bot_id": bot_id,
                "order_id": order["id"],
                "symbol": order["symbol"],
                "kind": "broker_open_order_without_ledger",
            }
            for order in orders
            if str(order["id"]) not in ledger_ids
        ]
    except Exception as exc:
        logger.warning(f"Reconciliation | order ledger read failed for {bot_id}: {exc}")
        return []


def _stale_portfolio(bot_id: str) -> list[dict[str, Any]]:
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT last_updated FROM bot_portfolio WHERE bot_id=%s", (bot_id,))
                row = cur.fetchone()
        if not row or row[0] is None:
            return [{"bot_id": bot_id, "kind": "stale_bot_portfolio", "detail": "missing ledger row"}]
        age_hours = (datetime.now(timezone.utc) - row[0].astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours > float(settings.kill_switch_portfolio_stale_hours):
            return [{"bot_id": bot_id, "kind": "stale_bot_portfolio", "detail": f"age_hours={age_hours:.2f}"}]
    except Exception as exc:
        logger.warning(f"Reconciliation | portfolio freshness read failed for {bot_id}: {exc}")
    return []


def collect_live_snapshot() -> dict[str, Any]:
    accounts = []
    mismatches = []
    fleet_equity = 0.0
    for bot_id in ACTIVE_BOTS:
        client = _client_for(bot_id)
        acct = client.get_account()
        positions = _positions(client)
        orders = _orders(client)
        ledger = _ledger_positions(bot_id)
        equity = float(acct.equity)
        lmv = sum(float(p["market_value"]) for p in positions if p["side"] == "long")
        accounts.append({
            "bot_id": bot_id, "equity": equity, "cash": float(acct.cash),
            "long_market_value": lmv, "max_deployment": MAX_DEPLOYMENT[bot_id],
            "positions": positions, "orders": orders, "ledger_positions": ledger,
            "_client": client,
        })
        mismatches.extend(_mismatches(bot_id, positions, ledger))
        mismatches.extend(_order_mismatches(bot_id, orders))
        mismatches.extend(_stale_portfolio(bot_id))
        fleet_equity += equity
    fleet_hwm = fleet_equity
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(total), %s) FROM (SELECT SUM(equity_usd) AS total FROM fleet_equity_snapshots GROUP BY snapshot_ts) s", (fleet_equity,))
                fleet_hwm = float(cur.fetchone()[0] or fleet_equity)
    except Exception:
        pass
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts,
        "mismatches": mismatches,
        "fleet_equity": fleet_equity,
        "fleet_hwm": fleet_hwm,
    }


def reconcile(report_only: bool = False) -> dict[str, Any]:
    from core.kill_switch import evaluate_snapshot, report, trip, _load_acknowledgements
    snapshot = collect_live_snapshot()
    acknowledgements = _load_acknowledgements()
    for account in snapshot["accounts"]:
        account["deployment_acknowledged"] = (
            f"deployment:{account['bot_id']}" in acknowledgements
        )
    flags = evaluate_snapshot(snapshot)
    clean = not snapshot["mismatches"] and not flags
    public_snapshot = {
        key: [
            {k: v for k, v in item.items() if k != "_client"}
            for item in value
        ] if key == "accounts" else value
        for key, value in snapshot.items()
    }
    result = {
        "mode": "report_only" if report_only else "scheduled",
        "clean": clean,
        "flags": flags,
        "snapshot": public_snapshot,
    }
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO reconciliation_log (clean, flags, snapshot) VALUES (%s,%s::jsonb,%s::jsonb)", (clean, json.dumps(flags, default=str), json.dumps(public_snapshot, default=str)))
                if not clean:
                    cur.execute("INSERT INTO system_degradations (component,severity,error_type,message,detail) VALUES (%s,%s,%s,%s,%s)", ("alpaca", "critical", "reconciliation_mismatch", "Broker/ledger reconciliation mismatch", json.dumps(flags, default=str)))
    except Exception as exc:
        logger.critical(f"Reconciliation | persistence failed: {exc}")
    if not report_only and flags:
        trip(flags, snapshot)
    return result


def run_kill_switch_check(report_only: bool = True) -> dict[str, Any]:
    """Run the five-minute safety check; DEV and unarmed production are report-only."""
    from core.kill_switch import evaluate_snapshot, report, trip, _load_acknowledgements
    snapshot = collect_live_snapshot()
    acknowledgements = _load_acknowledgements()
    for account in snapshot["accounts"]:
        account["deployment_acknowledged"] = (
            f"deployment:{account['bot_id']}" in acknowledgements
        )
    flags = evaluate_snapshot(snapshot)
    if report_only or not flags:
        return report(snapshot)
    return trip(flags, snapshot)