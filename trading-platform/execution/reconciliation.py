"""Read-only broker versus database reconciliation."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from core.kill_switch import ACCOUNT_ENV, ACTIVE_BOTS, DUST_QTY, MAX_DEPLOYMENT
from config.settings import settings
from core.bot_registry import resolve_bot_id
from core.symbols import canonical_symbol


# The retired buck_futures strategy shared Oracle's Alpaca account. Its durable
# rows still need to be reconciled against that broker account.
_LEDGER_ACCOUNT_ALIASES = {"buck_futures": "oracle"}
_TRADES_DEFAULT_ACCOUNT = "oracle"
_MATERIAL_NOTIONAL = 0.01


def _client_for(bot_id: str):
    bot_id = resolve_bot_id(bot_id)
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
    bot_id = resolve_bot_id(bot_id)
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


def _ledger_account_id(row: dict[str, Any]) -> str | None:
    """Resolve a ledger row to the Alpaca account that owns its symbols."""
    raw_bot_id = str(row.get("bot_id") or "").strip()
    if not raw_bot_id and row.get("table") == "trades":
        return _TRADES_DEFAULT_ACCOUNT
    if raw_bot_id in _LEDGER_ACCOUNT_ALIASES:
        return _LEDGER_ACCOUNT_ALIASES[raw_bot_id]
    if not raw_bot_id:
        return None
    try:
        return resolve_bot_id(raw_bot_id)
    except ValueError:
        return None


def _active_ledger_rows() -> list[dict[str, Any]]:
    """Read every material active/open position row without mutating state."""
    try:
        from db.postgres import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        'alpaca_etf_positions' AS table_name,
                        bot_id,
                        symbol,
                        qty::double precision AS qty,
                        notional_usd::double precision AS notional_usd,
                        status,
                        opened_at
                    FROM alpaca_etf_positions
                    WHERE lower(status) = 'open'
                    UNION ALL
                    SELECT
                        'bot3_positions',
                        bot_id,
                        symbol,
                        qty::double precision,
                        notional_usd::double precision,
                        status,
                        opened_at
                    FROM bot3_positions
                    WHERE lower(status) = 'open'
                    UNION ALL
                    SELECT
                        'jerome_positions',
                        bot_id,
                        symbol,
                        NULL::double precision,
                        notional_usd::double precision,
                        status,
                        opened_at
                    FROM jerome_positions
                    WHERE lower(status) = 'open'
                    UNION ALL
                    SELECT
                        'trades',
                        NULL,
                        ticker,
                        qty::double precision,
                        NULL::double precision,
                        status,
                        date::timestamptz
                    FROM trades
                    WHERE lower(status) = 'active'
                    UNION ALL
                    SELECT
                        'bot_portfolio.positions',
                        portfolio.bot_id,
                        item->>'symbol',
                        NULLIF(item->>'qty', '')::double precision,
                        NULLIF(item->>'notional_usd', '')::double precision,
                        COALESCE(NULLIF(item->>'status', ''), 'Active'),
                        NULLIF(item->>'opened_at', '')::timestamptz
                    FROM bot_portfolio AS portfolio
                    CROSS JOIN LATERAL jsonb_array_elements(
                        COALESCE(portfolio.positions, '[]'::jsonb)
                    ) AS item
                    WHERE lower(COALESCE(item->>'status', 'active'))
                        IN ('active', 'open')
                    """
                )
                columns = (
                    "table",
                    "bot_id",
                    "symbol",
                    "qty",
                    "notional_usd",
                    "status",
                    "opened_at",
                )
                return [
                    dict(zip(columns, row, strict=True))
                    for row in cur.fetchall()
                ]
    except Exception as exc:
        logger.warning(f"Reconciliation | active ledger scan failed: {exc}")
        return []


def _is_material_ledger_row(row: dict[str, Any]) -> bool:
    qty = abs(float(row.get("qty") or 0))
    notional = abs(float(row.get("notional_usd") or 0))
    return qty >= DUST_QTY or notional >= _MATERIAL_NOTIONAL


def _ledger_orphan_findings(
    broker_positions: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Find material active/open ledger rows absent from their broker account."""
    findings: list[dict[str, Any]] = []
    broker_symbols = {
        bot_id: {
            canonical_symbol(position.get("symbol"))
            for position in positions
            if abs(float(position.get("qty") or 0)) >= DUST_QTY
        }
        for bot_id, positions in broker_positions.items()
    }
    for row in _active_ledger_rows():
        if not _is_material_ledger_row(row):
            continue
        account_bot_id = _ledger_account_id(row)
        symbol = canonical_symbol(row.get("symbol"))
        if account_bot_id is not None and symbol in broker_symbols.get(account_bot_id, set()):
            continue
        findings.append(
            {
                "bot_id": account_bot_id or row.get("bot_id") or "unknown",
                "ledger_bot_id": row.get("bot_id"),
                "table": row.get("table"),
                "symbol": symbol,
                "ledger_symbol": row.get("symbol"),
                "qty": row.get("qty"),
                "notional_usd": row.get("notional_usd"),
                "status": row.get("status"),
                "opened_at": row.get("opened_at"),
                "kind": "ledger_orphan",
            }
        )
    return findings


def _account_summaries(
    accounts: list[dict[str, Any]],
    mismatches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Provide per-account counts for raw reconciliation reports."""
    summaries = []
    for account in accounts:
        bot_id = account["bot_id"]
        account_findings = [
            finding
            for finding in mismatches
            if finding.get("bot_id") == bot_id
        ]
        broker_findings = [
            finding
            for finding in account_findings
            if finding.get("kind") != "ledger_orphan"
        ]
        orphan_findings = [
            finding
            for finding in account_findings
            if finding.get("kind") == "ledger_orphan"
        ]
        summaries.append(
            {
                "bot_id": bot_id,
                "broker_finding_count": len(broker_findings),
                "orphan_finding_count": len(orphan_findings),
                "status": "MISMATCH" if account_findings else "CLEAN",
            }
        )
    return summaries


def _mismatches(bot_id: str, broker: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bot_id = resolve_bot_id(bot_id)
    b = {canonical_symbol(p.get("symbol")): abs(float(p.get("qty") or 0)) for p in broker if abs(float(p.get("qty") or 0)) >= DUST_QTY}
    l = {canonical_symbol(p.get("symbol")): abs(float(p.get("qty") or 0)) for p in ledger if abs(float(p.get("qty") or 0)) >= DUST_QTY}
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
    bot_id = resolve_bot_id(bot_id)
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
    bot_id = resolve_bot_id(bot_id)
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT paused FROM bots_state WHERE bot_id=%s", (bot_id,))
                pause_row = cur.fetchone()
                if pause_row and bool(pause_row[0]):
                    return []
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


def _pause_state_disagreements() -> list[dict[str, Any]]:
    """Compare runner static profiles with canonical DB pause rows."""
    try:
        import importlib.util
        from pathlib import Path

        config_path = Path(__file__).resolve().parents[2] / "kraken-bot" / "config.py"
        spec = importlib.util.spec_from_file_location("_kraken_pause_config", config_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load runner config")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        profiles = module.BOT_PROFILES

        from db.postgres import get_conn
        result = []
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_id in ACTIVE_BOTS:
                    profile_id = bot_id
                    if bot_id == "spy_qqq_trend":
                        profile_id = "bot2_spy_qqq"
                    static_paused = bool(profiles.get(profile_id, {}).get("BOT_PAUSED", False))
                    cur.execute("SELECT paused FROM bots_state WHERE bot_id = %s", (bot_id,))
                    row = cur.fetchone()
                    database_paused = row[0] if row else None
                    if database_paused is None or static_paused != bool(database_paused):
                        result.append({
                            "bot_id": bot_id,
                            "static_paused": static_paused,
                            "database_paused": database_paused,
                        })
        return result
    except Exception as exc:
        logger.critical(f"Reconciliation | pause-state alignment check failed: {exc}")
        return [{"bot_id": "fleet", "kind": "pause_state_check_failed", "detail": str(exc)}]


def collect_live_snapshot() -> dict[str, Any]:
    accounts = []
    mismatches = []
    account_findings = []
    fleet_equity = 0.0
    for bot_id in ACTIVE_BOTS:
        try:
            client = _client_for(bot_id)
        except Exception as exc:
            logger.critical(f"Reconciliation | account unavailable for {bot_id}: {exc}")
            account_findings.append({
                "bot_id": bot_id,
                "kind": "account_unavailable",
                "detail": str(exc),
            })
            continue
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
    mismatches.extend(
        _ledger_orphan_findings(
            {
                account["bot_id"]: account["positions"]
                for account in accounts
            }
        )
    )
    fleet_hwm = fleet_equity
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(total), %s) FROM (SELECT SUM(equity_usd) AS total FROM fleet_equity_snapshots GROUP BY snapshot_ts) s", (fleet_equity,))
                fleet_hwm = float(cur.fetchone()[0] or fleet_equity)
    except Exception:
        pass
    try:
        from core.bot_liveness import evaluate_liveness
        liveness_findings = evaluate_liveness()
    except Exception as exc:
        liveness_findings = [{
            "trigger": "bot_cycle_health_unavailable",
            "detail": str(exc),
            "severity": "critical",
        }]
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts,
        "mismatches": mismatches,
        "account_summaries": _account_summaries(accounts, mismatches),
        "account_findings": account_findings,
        "pause_state_disagreements": _pause_state_disagreements(),
        "liveness_findings": liveness_findings,
        "fleet_equity": fleet_equity,
        "fleet_hwm": fleet_hwm,
    }


def reconcile(
    report_only: bool = False,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    from core.kill_switch import evaluate_snapshot, report, trip, _load_acknowledgements
    snapshot = collect_live_snapshot()
    reconciliation_cycle_id = cycle_id or (
        f"reconciliation:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    acknowledgements = _load_acknowledgements()
    for account in snapshot["accounts"]:
        account["deployment_acknowledged"] = (
            f"deployment:{account['bot_id']}" in acknowledgements
        )
    flags = evaluate_snapshot(snapshot)
    # Preserve the liveness findings in the reconciliation payload even when
    # another evaluator is replaced or mocked by a caller.
    for finding in snapshot.get("liveness_findings", []):
        if finding not in flags:
            flags.append(finding)
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
                    grouped_flags: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
                    for flag in flags:
                        raw_bot_id = flag.get("bot_id") if isinstance(flag, dict) else None
                        if raw_bot_id:
                            try:
                                flag_bot_id = resolve_bot_id(str(raw_bot_id))
                            except Exception:
                                flag_bot_id = str(raw_bot_id)
                        else:
                            flag_bot_id = None
                        flag_cycle_id = (
                            flag.get("cycle_id")
                            if isinstance(flag, dict) else None
                        ) or reconciliation_cycle_id
                        grouped_flags.setdefault(
                            (flag_bot_id, str(flag_cycle_id)),
                            [],
                        ).append(flag)
                    for (flag_bot_id, flag_cycle_id), flag_group in grouped_flags.items():
                        cur.execute(
                            """
                            INSERT INTO system_degradations
                                (component, severity, error_type, message, detail,
                                 bot_id, cycle_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                "alpaca",
                                "critical",
                                "reconciliation_mismatch",
                                "Broker/ledger reconciliation mismatch",
                                json.dumps(flag_group, default=str),
                                flag_bot_id,
                                flag_cycle_id,
                            ),
                        )
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