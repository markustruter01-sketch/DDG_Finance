"""Read-only broker versus database reconciliation."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from core.kill_switch import (
    ACCOUNT_ENV,
    ACTIVE_BOTS,
    DUST_QTY,
    MAX_DEPLOYMENT,
    _vault_symbols,
    forex_trade_mismatches,
    read_oanda_account_snapshot,
)
from config.settings import settings
from core.bot_registry import resolve_bot_id
from core.settling import safe_recent_fill_symbols, split_settling
from core.symbols import canonical_symbol


# The retired buck_futures strategy shared Oracle's Alpaca account. Its durable
# rows still need to be reconciled against that broker account.
_LEDGER_ACCOUNT_ALIASES = {"buck_futures": "oracle"}
_TRADES_DEFAULT_ACCOUNT = "oracle"
_MATERIAL_NOTIONAL = 0.01
_AUTHORITATIVE_POSITION_TABLES = {
    "oracle": "alpaca_etf_positions",
    "spy_qqq_trend": "bot2_momentum_positions",
    "jerome_macro": "bot3_positions",
}
_TERMINAL_ORDER_STATUSES = {"canceled", "filled", "expired", "rejected"}


def _reconciliation_check_failed(
    check: str,
    exc: Exception,
    bot_id: str | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "kind": "reconciliation_check_failed",
        "check": check,
        "error": str(exc),
    }
    if bot_id is not None:
        finding["bot_id"] = bot_id
    return finding


def _client_for(bot_id: str):
    bot_id = resolve_bot_id(bot_id)
    from alpaca.trading.client import TradingClient
    key_name, secret_name = ACCOUNT_ENV[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing credentials for {bot_id}")
    return TradingClient(key, secret, paper=True)


def _forex_ai_ledger_rows() -> list[dict[str, Any]]:
    """Read open OANDA trade ownership rows without mutating the ledger."""
    from db.postgres import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_id, instrument, signed_units::double precision,
                       stop_order_id, entry_price::double precision,
                       leverage_tier, status, opened_at, closed_at
                FROM forex_ai_trades
                WHERE lower(status) = 'open'
                ORDER BY trade_id
                """
            )
            columns = (
                "trade_id",
                "instrument",
                "signed_units",
                "stop_order_id",
                "entry_price",
                "leverage_tier",
                "status",
                "opened_at",
                "closed_at",
            )
            return [
                dict(zip(columns, row, strict=True))
                for row in cur.fetchall()
            ]


def _orders(client) -> list[dict[str, Any]]:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    result = []
    for order in client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True, limit=500)):
        asset_class = getattr(order, "asset_class", None)
        result.append({
            "id": str(order.id), "symbol": str(order.symbol), "side": getattr(order.side, "value", order.side),
            "type": getattr(order.type, "value", order.type), "qty": float(order.qty or 0),
            "status": getattr(order.status, "value", order.status),
            "asset_class": getattr(asset_class, "value", asset_class),
        })
    return result


def _positions(client) -> list[dict[str, Any]]:
    result = []
    for p in client.get_all_positions():
        asset_class = getattr(p, "asset_class", None)
        result.append({
            "symbol": str(p.symbol), "qty": float(p.qty), "side": getattr(p.side, "value", "long"),
            "market_value": float(p.market_value or 0),
            "asset_class": getattr(asset_class, "value", asset_class),
        })
    return result


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
        return [_reconciliation_check_failed("bot_portfolio_read", exc, bot_id)]


def _authoritative_ledger_positions(bot_id: str) -> list[dict[str, Any]]:
    """Read active strategy positions from the bot's authoritative table.

    ``bot_portfolio`` remains a useful aggregate mirror and is checked
    separately.  These rows are the strategy source of truth; durable BIL/VOO
    vault holdings are explicitly excluded so they cannot become strategy
    quantity findings.
    """
    bot_id = resolve_bot_id(bot_id)
    table = _AUTHORITATIVE_POSITION_TABLES.get(bot_id)
    if table is None:
        return []
    quantity_column = (
        "current_qty" if table == "alpaca_etf_positions" else "qty"
    )
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        symbol,
                        {quantity_column}::double precision AS qty
                    FROM {table} AS position
                    WHERE position.bot_id = %s
                      AND lower(position.status) = 'open'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM per_bot_vault_holdings AS vault
                          WHERE vault.bot_id = position.bot_id
                            AND vault.symbol = position.symbol
                      )
                    """,
                    (bot_id,),
                )
                return [
                    {
                        "table": table,
                        "bot_id": bot_id,
                        "symbol": row[0],
                        "qty": row[1],
                    }
                    for row in cur.fetchall()
                ]
    except Exception as exc:
        logger.warning(
            f"Reconciliation | authoritative ledger read failed for {bot_id}: {exc}"
        )
        return [_reconciliation_check_failed("authoritative_position_read", exc, bot_id)]


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
                        current_qty::double precision AS qty,
                        notional_usd::double precision AS notional_usd,
                        status,
                        opened_at
                    FROM alpaca_etf_positions
                    WHERE lower(status) = 'open'
                    UNION ALL
                    SELECT
                        'bot2_momentum_positions',
                        bot_id,
                        symbol,
                        qty::double precision,
                        notional_usd::double precision,
                        status,
                        opened_at
                    FROM bot2_momentum_positions
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
        return [_reconciliation_check_failed("active_ledger_scan", exc)]


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
    ledger_rows = _active_ledger_rows()
    check_failures = [
        row
        for row in ledger_rows
        if row.get("kind") == "reconciliation_check_failed"
    ]
    if check_failures:
        return check_failures
    for row in ledger_rows:
        if (
            row.get("table") == "alpaca_etf_positions"
            and row.get("qty") is None
        ):
            ledger_bot_id = row.get("bot_id")
            handled_by_authoritative_read = (
                ledger_bot_id in _AUTHORITATIVE_POSITION_TABLES
                and ledger_bot_id in broker_positions
                and _AUTHORITATIVE_POSITION_TABLES[ledger_bot_id]
                == row.get("table")
            )
            if not handled_by_authoritative_read:
                findings.append(
                    {
                        "bot_id": _ledger_account_id(row)
                        or ledger_bot_id
                        or "unknown",
                        "ledger_bot_id": ledger_bot_id,
                        "table": row.get("table"),
                        "symbol": canonical_symbol(row.get("symbol")),
                        "ledger_symbol": row.get("symbol"),
                        "qty": None,
                        "notional_usd": row.get("notional_usd"),
                        "status": row.get("status"),
                        "opened_at": row.get("opened_at"),
                        "kind": "quantity_unknown",
                    }
                )
            continue
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


def _mismatches(
    bot_id: str,
    broker: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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
            results.append({
                "bot_id": bot_id,
                "table": "bot_portfolio.positions",
                "symbol": symbol,
                "kind": "quantity_mismatch",
                "broker_qty": b[symbol],
                "ledger_qty": l[symbol],
            })
    return results


# Claude's design value (22 Oct 2026): the vault ledger books each fill in
# whole cents, so it drifts from the broker by a few cents per fill. A gap
# above this plus the amount still waiting to be bought is real (the 15-21 Oct
# re-buy loop reached about $600 per symbol).
VAULT_TOLERANCE_USD = 5.0


def _vault_ledger(bot_id: str) -> tuple[dict[str, float], dict[str, float]]:
    """(vault ledger qty, USD still pending purchase) per symbol."""
    from db.postgres import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol, qty FROM per_bot_vault_holdings WHERE bot_id = %s", (bot_id,))
            qty = {canonical_symbol(s): float(q or 0) for s, q in cur.fetchall()}
            cur.execute("SELECT pending_bil_usd, pending_voo_usd FROM per_bot_vault_deployment_queue "
                        "WHERE bot_id = %s", (bot_id,))
            row = cur.fetchone()
    pending = {"BIL": float(row[0] or 0), "VOO": float(row[1] or 0)} if row else {}
    return qty, pending


def _vault_mismatches(bot_id: str, broker: list[dict[str, Any]],
                      vault_symbols: set[str]) -> list[dict[str, Any]]:
    """Broker vault holdings vs the vault ledger. Only quantities go in the
    finding (no prices), so an unchanged gap repeats identically and the kill
    switch's repeat count can work."""
    bot_id = resolve_bot_id(bot_id)
    try:
        ledger, pending = _vault_ledger(bot_id)
    except Exception as exc:
        logger.warning(f"Reconciliation | vault ledger read failed for {bot_id}: {exc}")
        return [_reconciliation_check_failed("vault_ledger_read", exc, bot_id)]
    held = {canonical_symbol(p.get("symbol")): p for p in broker}
    out = []
    for symbol in sorted(vault_symbols):
        p = held.get(symbol)
        broker_qty = abs(float(p.get("qty") or 0)) if p else 0.0
        vault_qty = ledger.get(symbol, 0.0)
        if broker_qty < DUST_QTY and vault_qty < DUST_QTY:
            continue
        price = abs(float(p.get("market_value") or 0)) / broker_qty if p and broker_qty else None
        if price is None:
            gap_too_big = True                   # ledger says we hold it; broker has none
        else:
            gap_too_big = abs(broker_qty - vault_qty) * price > VAULT_TOLERANCE_USD + pending.get(symbol, 0.0)
        if gap_too_big:
            out.append({"bot_id": bot_id, "symbol": symbol, "kind": "vault_quantity_mismatch",
                        "table": "per_bot_vault_holdings",
                        "broker_qty": round(broker_qty, 6), "vault_qty": round(vault_qty, 6)})
    return out


def _authoritative_quantity_mismatches(
    bot_id: str,
    broker: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare broker quantities with the authoritative strategy ledger.

    This intentionally checks only symbols present in both sources.  Symbol
    presence and orphan detection remain the responsibility of ``_mismatches``
    and ``_ledger_orphan_findings``; vault holdings are not strategy rows.
    """
    resolved_bot_id = resolve_bot_id(bot_id)
    if resolved_bot_id not in _AUTHORITATIVE_POSITION_TABLES:
        return []

    ledger = _authoritative_ledger_positions(resolved_bot_id)
    if ledger and "kind" in ledger[0]:
        return ledger

    broker_by_symbol: dict[str, float] = {}
    for position in broker:
        qty = abs(float(position.get("qty") or 0))
        if qty >= DUST_QTY:
            symbol = canonical_symbol(position.get("symbol"))
            broker_by_symbol[symbol] = broker_by_symbol.get(symbol, 0.0) + qty

    ledger_by_symbol: dict[str, float] = {}
    unknown_quantities: list[dict[str, Any]] = []
    for position in ledger:
        raw_qty = position.get("qty")
        position_table = position.get(
            "table", _AUTHORITATIVE_POSITION_TABLES[resolved_bot_id]
        )
        if (
            raw_qty is None
            and position_table == "alpaca_etf_positions"
        ):
            unknown_quantities.append(
                {
                    "bot_id": resolved_bot_id,
                    "table": position_table,
                    "symbol": canonical_symbol(position.get("symbol")),
                    "ledger_qty": None,
                    "kind": "quantity_unknown",
                }
            )
            continue
        qty = abs(float(raw_qty or 0))
        if qty >= DUST_QTY:
            symbol = canonical_symbol(position.get("symbol"))
            ledger_by_symbol[symbol] = ledger_by_symbol.get(symbol, 0.0) + qty

    table = _AUTHORITATIVE_POSITION_TABLES[resolved_bot_id]
    return unknown_quantities + [
        {
            "bot_id": resolved_bot_id,
            "table": table,
            "symbol": symbol,
            "kind": "quantity_mismatch",
            "broker_qty": broker_by_symbol[symbol],
            "ledger_qty": ledger_by_symbol[symbol],
        }
        for symbol in sorted(set(broker_by_symbol) & set(ledger_by_symbol))
        if abs(broker_by_symbol[symbol] - ledger_by_symbol[symbol]) > DUST_QTY
    ]


def _is_live_protective_order(order: dict[str, Any]) -> bool:
    """Treat pending cancellation as live until a terminal status is confirmed."""
    order_type = str(order.get("type") or "").lower()
    side = str(order.get("side") or "").lower()
    status = str(order.get("status") or "").lower()
    # new, accepted, held, and pending_cancel are LIVE. Only the terminal
    # statuses below count as not-live for the ledger-stop comparison.
    return (
        side in {"buy", "sell"}
        and order_type in {"stop", "stop_limit", "trailing_stop"}
        and status not in _TERMINAL_ORDER_STATUSES
    )


def _stop_ledger_rows(bot_id: str) -> list[dict[str, Any]]:
    """Load owned stop IDs with bot/symbol identity preserved.

    Legacy ratchet rows have no bot column and are retained for Oracle's
    forward broker-order check, but only active authoritative position rows
    participate in the reverse stale-ledger check.
    """
    bot_id = resolve_bot_id(bot_id)
    rows: list[dict[str, Any]] = []
    table = _AUTHORITATIVE_POSITION_TABLES.get(bot_id)
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                if bot_id == "oracle":
                    cur.execute(
                        "SELECT symbol, stop_order_id FROM ratchet_stops "
                        "WHERE stop_order_id IS NOT NULL"
                    )
                    rows.extend(
                        {
                            "bot_id": bot_id,
                            "symbol": row[0],
                            "stop_order_id": str(row[1]),
                            "table": "ratchet_stops",
                            "reverse_check": False,
                        }
                        for row in cur.fetchall()
                    )
                if table is not None:
                    cur.execute(
                        f"SELECT bot_id, symbol, stop_order_id FROM {table} "
                        "WHERE bot_id = %s AND status = 'open' "
                        "AND stop_order_id IS NOT NULL",
                        (bot_id,),
                    )
                    rows.extend(
                        {
                            "bot_id": row[0],
                            "symbol": row[1],
                            "stop_order_id": str(row[2]),
                            "table": table,
                            "reverse_check": True,
                        }
                        for row in cur.fetchall()
                    )
        return rows
    except Exception as exc:
        logger.warning(f"Reconciliation | stop ledger read failed for {bot_id}: {exc}")
        return [_reconciliation_check_failed("stop_ledger_read", exc, bot_id)]


def _order_mismatches(bot_id: str, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare live owned stops in both directions, per bot and per symbol."""
    bot_id = resolve_bot_id(bot_id)
    try:
        ledger_rows = _stop_ledger_rows(bot_id)
    except Exception as exc:
        return [_reconciliation_check_failed("stop_ledger_read", exc, bot_id)]
    check_failures = [
        row
        for row in ledger_rows
        if row.get("kind") == "reconciliation_check_failed"
    ]
    if check_failures:
        return check_failures
    live_orders = [order for order in orders if _is_live_protective_order(order)]
    ledger_keys = {
        (
            row["bot_id"],
            canonical_symbol(row["symbol"]),
            str(row["stop_order_id"]),
        )
        for row in ledger_rows
        if row["symbol"] is not None
    }
    live_keys = {
        (bot_id, canonical_symbol(order["symbol"]), str(order["id"]))
        for order in live_orders
    }
    findings = [
        {
            "bot_id": bot_id,
            "order_id": order["id"],
            "symbol": order["symbol"],
            "kind": "broker_open_order_without_ledger",
        }
        for order in live_orders
        if (
            bot_id,
            canonical_symbol(order["symbol"]),
            str(order["id"]),
        ) not in ledger_keys
    ]
    findings.extend(
        {
            "bot_id": row["bot_id"],
            "table": row["table"],
            "symbol": row["symbol"],
            "stop_order_id": row["stop_order_id"],
            "kind": "ledger_stop_without_broker",
        }
        for row in ledger_rows
        if row["reverse_check"]
        and (
            row["bot_id"],
            canonical_symbol(row["symbol"]),
            str(row["stop_order_id"]),
        ) not in live_keys
    )
    return findings


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
        return [_reconciliation_check_failed("portfolio_freshness_read", exc, bot_id)]
    return []


def _pause_state_disagreements() -> list[dict[str, Any]]:
    """Every active bot must have a readable bots_state pause row.

    bots_state.paused is the only pause switch, so the old static-versus-DB
    disagreement cannot happen; a missing or unreadable row can, and the
    runner treats it as paused, so it is reported here.
    """
    try:
        from db.postgres import get_conn
        result = []
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_id in ACTIVE_BOTS:
                    cur.execute("SELECT paused FROM bots_state WHERE bot_id = %s", (bot_id,))
                    row = cur.fetchone()
                    if row is None or row[0] is None:
                        result.append({
                            "bot_id": bot_id,
                            "kind": "pause_row_missing",
                            "database_paused": None,
                        })
        return result
    except Exception as exc:
        logger.critical(f"Reconciliation | pause-state read failed: {exc}")
        return [{"bot_id": "fleet", "kind": "pause_state_check_failed", "detail": str(exc)}]


def collect_live_snapshot() -> dict[str, Any]:
    accounts = []
    mismatches = []
    account_findings = []
    settling_symbols: dict[str, set[str]] = {}
    for bot_id in ACTIVE_BOTS:
        if bot_id == "forex_ai":
            try:
                account = read_oanda_account_snapshot()
            except Exception as exc:
                logger.critical(f"Reconciliation | OANDA account unavailable: {exc}")
                account_findings.append(
                    {
                        "bot_id": bot_id,
                        "kind": "oanda_read_failed",
                        "status": "UNKNOWN",
                        "detail": str(exc),
                    }
                )
                continue

            accounts.append(account)
            try:
                ledger_trades = _forex_ai_ledger_rows()
            except Exception as exc:
                logger.critical(
                    f"Reconciliation | Forex trade ledger unavailable: {exc}"
                )
                account_findings.append(
                    {
                        "bot_id": bot_id,
                        "kind": "forex_trade_ledger_read_failed",
                        "status": "UNKNOWN",
                        "detail": str(exc),
                    }
                )
                continue
            try:
                mismatches.extend(
                    forex_trade_mismatches(account["open_trades"], ledger_trades)
                )
            except Exception as exc:
                logger.critical(f"Reconciliation | OANDA trade comparison unknown: {exc}")
                account_findings.append(
                    {
                        "bot_id": bot_id,
                        "kind": "forex_trade_comparison_unknown",
                        "status": "UNKNOWN",
                        "detail": str(exc),
                    }
                )
            continue

        vault_symbols: set[str] | None
        try:
            vault_symbols = _vault_symbols(bot_id)
        except Exception as exc:
            logger.critical(
                f"Reconciliation | vault holdings read failed for {bot_id}: {exc}"
            )
            mismatches.append(
                _reconciliation_check_failed("vault_symbols_read", exc, bot_id)
            )
            vault_symbols = None
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
        settling_symbols[resolve_bot_id(bot_id)] = safe_recent_fill_symbols(bot_id, client)
        ledger = _ledger_positions(bot_id)
        ledger_failures = [
            row
            for row in ledger
            if row.get("kind") == "reconciliation_check_failed"
        ]
        if ledger_failures:
            mismatches.extend(ledger_failures)
            ledger = []
        equity = float(acct.equity)
        lmv = sum(float(p["market_value"]) for p in positions if p["side"] == "long")
        accounts.append({
            "bot_id": bot_id, "equity": equity, "cash": float(acct.cash),
            "long_market_value": lmv, "max_deployment": MAX_DEPLOYMENT[bot_id],
            "positions": positions, "orders": orders, "ledger_positions": ledger,
            "vault_symbols": vault_symbols,
            "_client": client,
        })
        if vault_symbols:
            # Vault BIL/VOO are bought by the vault job between bot cycles, so
            # the hourly bot_portfolio mirror lags them. Check them against the
            # vault's own ledger instead.
            def _not_vault(p: dict[str, Any]) -> bool:
                return canonical_symbol(p.get("symbol")) not in vault_symbols
            mismatches.extend(_mismatches(bot_id, [p for p in positions if _not_vault(p)],
                                          [p for p in ledger if _not_vault(p)]))
            mismatches.extend(_vault_mismatches(bot_id, positions, vault_symbols))
        else:
            mismatches.extend(_mismatches(bot_id, positions, ledger))
        mismatches.extend(_authoritative_quantity_mismatches(bot_id, positions))
        mismatches.extend(_order_mismatches(bot_id, orders))
        mismatches.extend(_stale_portfolio(bot_id))
    fleet_equity: float | None
    try:
        from core.fleet_equity import get_fleet_equity

        fleet_equity, _ = get_fleet_equity()
    except Exception as exc:
        logger.critical(f"Reconciliation | fleet equity read failed: {exc}")
        mismatches.append(_reconciliation_check_failed("fleet_equity_read", exc))
        fleet_equity = None

    mismatches.extend(
        _ledger_orphan_findings(
            {
                account["bot_id"]: account["positions"]
                for account in accounts
            }
        )
    )
    # Fills the bots have not booked yet clear by themselves (core/settling.py).
    mismatches, settling = split_settling(mismatches, settling_symbols)
    fleet_hwm = fleet_equity
    if fleet_equity is not None:
        try:
            from db.postgres import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(MAX(total), %s) FROM (SELECT SUM(equity_usd) AS total FROM fleet_equity_snapshots GROUP BY snapshot_ts) s", (fleet_equity,))
                    fleet_hwm = float(cur.fetchone()[0] or fleet_equity)
        except Exception as exc:
            mismatches.append(_reconciliation_check_failed("fleet_hwm_read", exc))
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
        "settling": settling,
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
    dry_run: bool = False,
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
            flag.get("cycle_id") if isinstance(flag, dict) else None
        ) or reconciliation_cycle_id
        grouped_flags.setdefault((flag_bot_id, str(flag_cycle_id)), []).append(flag)
    would_alert = [
        {
            "component": "oanda" if bot_id == "forex_ai" else "alpaca",
            "severity": "critical",
            "error_type": "reconciliation_mismatch",
            "bot_id": bot_id,
            "cycle_id": flag_cycle_id,
            "message": "Broker/ledger reconciliation mismatch",
            "detail": json.dumps(flag_group, default=str),
        }
        for (bot_id, flag_cycle_id), flag_group in grouped_flags.items()
    ]
    result = {
        "mode": "dry_run" if dry_run else ("report_only" if report_only else "scheduled"),
        "clean": clean,
        "flags": flags,
        "snapshot": public_snapshot,
    }
    if dry_run:
        result["would_alert"] = would_alert
        return result
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO reconciliation_log (clean, flags, snapshot) VALUES (%s,%s::jsonb,%s::jsonb)", (clean, json.dumps(flags, default=str), json.dumps(public_snapshot, default=str)))
    except Exception as exc:
        logger.critical(f"Reconciliation | persistence failed: {exc}")
    if not clean:
        from core.degradation_tracker import record_degradation

        for alert in would_alert:
            record_degradation(
                component=alert["component"],
                severity=alert["severity"],
                error_type=alert["error_type"],
                message=alert["message"],
                detail=alert["detail"],
                bot_id=alert["bot_id"],
                cycle_id=alert["cycle_id"],
            )
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