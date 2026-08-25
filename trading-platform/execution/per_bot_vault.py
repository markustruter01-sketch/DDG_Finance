"""Inactive per-bot profit vault accounting.

This module is intentionally separate from the retired global JEPQ/HWM vault in
profit_sweep.py.  It is safe to import from close paths while disabled:
disabled mode performs no database writes and never calls a broker.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from uuid import uuid4
from typing import Any

from loguru import logger

ACTIVE_BOT_IDS = ("oracle", "spy_qqq_trend", "jerome_macro")
SKIM_RATE = 0.20
SEED_RATE = 0.05
MIN_TRADE_NOTIONAL = 1.0
VAULT_BIL_SYMBOL = "BIL"
VAULT_VOO_SYMBOL = "VOO"
CONFIRMATION_TOKEN = "ACTIVATE_PER_BOT_VAULT"
VAULT_ORDER_PREFIX = "PBV-"
ACCOUNT_ENV = {
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}


def vault_enabled() -> bool:
    """Explicit opt-in; absence or any value other than true keeps it off."""
    return os.environ.get("PER_BOT_VAULT_ENABLED", "").strip().lower() == "true"


def calculate_skim(realized_profit: float) -> float:
    """Return 20% of positive realized profit, never a negative contribution."""
    return round(max(0.0, float(realized_profit)) * SKIM_RATE, 2)


def split_contribution(skim_amount: float) -> tuple[float, float]:
    """Split a contribution equally between BIL and VOO."""
    half = round(max(0.0, float(skim_amount)) / 2.0, 2)
    return half, round(max(0.0, float(skim_amount)) - half, 2)


def deployment_plan(
    vault_value: float,
    *,
    market_open: bool,
    minimum_notional: float = MIN_TRADE_NOTIONAL,
) -> dict[str, Any]:
    """Describe a future deployment; this function never calls a broker."""
    if not vault_enabled():
        return {"action": "blocked", "reason": "inactive"}
    if not market_open:
        return {"action": "deferred", "reason": "market_closed"}
    if float(vault_value) < float(minimum_notional):
        return {"action": "deferred", "reason": "below_minimum", "minimum_notional": minimum_notional}
    bil, voo = split_contribution(vault_value)
    return {"action": "planned", "bil_notional": bil, "voo_notional": voo}


def rebalance_due(last_rebalance: date | None, as_of: date | None = None) -> bool:
    """Quarterly cadence check, independent of market/broker state."""
    today = as_of or datetime.now(timezone.utc).date()
    if last_rebalance is None:
        return True
    return (today.year, (today.month - 1) // 3) > (
        last_rebalance.year, (last_rebalance.month - 1) // 3
    )


def activation_plan(
    equities: dict[str, float],
    existing_activated: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Pure activation preview. It never creates rows or contacts a broker."""
    existing = existing_activated or set()
    return [
        {
            "bot_id": bot_id,
            "equity": round(float(equities.get(bot_id, 0)), 2),
            "seed": round(float(equities.get(bot_id, 0)) * SEED_RATE, 2),
            "trading_capital": round(float(equities.get(bot_id, 0)) * (1 - SEED_RATE), 2),
            "action": "skip_already_activated" if bot_id in existing else "would_activate",
        }
        for bot_id in ACTIVE_BOT_IDS
    ]


def trading_return_pct(trading_capital: float, activation_equity: float) -> float:
    """Trading return excludes all vault capital by construction."""
    if not activation_equity:
        return 0.0
    return round((float(trading_capital) / float(activation_equity) - 1.0) * 100.0, 4)


def worked_example() -> dict[str, float]:
    """Deterministic accounting example used by the verification harness."""
    starting = 100.0
    profit = 10.0
    skim = calculate_skim(profit)
    bil, voo = split_contribution(skim)
    return {
        "starting_trading_capital": starting,
        "profit": profit,
        "skim": skim,
        "bil_allocated": bil,
        "voo_allocated": voo,
        "trading_capital_after_skim": starting + profit - skim,
    }


def _row_dict(cur: Any, row: Any) -> dict[str, Any]:
    return dict(zip([desc[0] for desc in cur.description], row))


def ensure_schema() -> None:
    """Create only new tables; never alters or drops an existing table."""
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return
    ddl = """
    CREATE TABLE IF NOT EXISTS per_bot_vault_accounts (
        bot_id TEXT PRIMARY KEY,
        activation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        activation_equity NUMERIC,
        seed_amount NUMERIC NOT NULL DEFAULT 0,
        trading_capital NUMERIC,
        bil_qty NUMERIC NOT NULL DEFAULT 0,
        voo_qty NUMERIC NOT NULL DEFAULT 0,
        cash_usd NUMERIC NOT NULL DEFAULT 0,
        cumulative_contributions NUMERIC NOT NULL DEFAULT 0,
        last_rebalance_date DATE,
        activated_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS per_bot_vault_contributions (
        id BIGSERIAL PRIMARY KEY,
        bot_id TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
        source_trade_id TEXT NOT NULL,
        realized_profit NUMERIC NOT NULL,
        skim_amount NUMERIC NOT NULL,
        bil_allocated NUMERIC NOT NULL DEFAULT 0,
        voo_allocated NUMERIC NOT NULL DEFAULT 0,
        cash_accrued NUMERIC NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (bot_id, source_trade_id)
    );
    CREATE INDEX IF NOT EXISTS idx_per_bot_vault_contrib_bot_ts
        ON per_bot_vault_contributions (bot_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS per_bot_vault_value_history (
        id BIGSERIAL PRIMARY KEY,
        bot_id TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        trading_capital NUMERIC NOT NULL,
        cumulative_contributions NUMERIC NOT NULL,
        vault_value NUMERIC NOT NULL,
        vault_return_pct NUMERIC NOT NULL DEFAULT 0,
        combined_total NUMERIC NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_per_bot_vault_history_bot_ts
        ON per_bot_vault_value_history (bot_id, recorded_at DESC);
    CREATE TABLE IF NOT EXISTS per_bot_vault_deployment_queue (
        bot_id              TEXT PRIMARY KEY REFERENCES per_bot_vault_accounts(bot_id),
        pending_cash_usd    NUMERIC NOT NULL DEFAULT 0,
        pending_bil_usd     NUMERIC NOT NULL DEFAULT 0,
        pending_voo_usd     NUMERIC NOT NULL DEFAULT 0,
        bil_order_id        TEXT,
        voo_order_id        TEXT,
        bil_filled_usd      NUMERIC NOT NULL DEFAULT 0,
        voo_filled_usd      NUMERIC NOT NULL DEFAULT 0,
        status              TEXT NOT NULL DEFAULT 'pending',
        attempts            INTEGER NOT NULL DEFAULT 0,
        last_error          TEXT,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS per_bot_vault_holdings (
        bot_id              TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
        symbol              TEXT NOT NULL CHECK (symbol IN ('BIL', 'VOO')),
        qty                 NUMERIC NOT NULL DEFAULT 0,
        cost_basis_usd      NUMERIC NOT NULL DEFAULT 0,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (bot_id, symbol)
    );
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


def seed_preview() -> list[dict[str, Any]]:
    """Read current canonical bot equity and calculate, but never write, seeds."""
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return [{"bot_id": bot_id, "equity": None, "seed": None, "status": "database_unavailable"}
                for bot_id in ACTIVE_BOT_IDS]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bot_id, equity_usd FROM bot_portfolio WHERE bot_id = ANY(%s) ORDER BY bot_id",
                (list(ACTIVE_BOT_IDS),),
            )
            equities = {row[0]: float(row[1] or 0) for row in cur.fetchall()}
    return [
        {
            "bot_id": bot_id,
            "equity": equities.get(bot_id),
            "seed": round(equities[bot_id] * SEED_RATE, 2) if bot_id in equities else None,
            "status": "preview_only",
        }
        for bot_id in ACTIVE_BOT_IDS
    ]


def activate_vault(*, confirmation: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Explicit activation command; refuses without token and stays disabled by default."""
    if confirmation != CONFIRMATION_TOKEN:
        return {"activated": False, "reason": "explicit_confirmation_required", "required": CONFIRMATION_TOKEN}
    previews = seed_preview()
    if dry_run:
        plan = activation_plan({p["bot_id"]: p["equity"] or 0 for p in previews})
        return {
            "activated": False,
            "dry_run": True,
            "enabled": vault_enabled(),
            "bots": plan,
            "second_run_simulation": [
                {"bot_id": item["bot_id"], "action": "skip_already_activated"}
                for item in plan
            ],
        }
    if not vault_enabled():
        return {"activated": False, "reason": "PER_BOT_VAULT_ENABLED is not true", "dry_run": False}
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"activated": False, "reason": "database_unavailable"}
    result: list[dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in previews:
                bot_id, equity = item["bot_id"], float(item["equity"] or 0)
                seed = round(equity * SEED_RATE, 2)
                cur.execute(
                    """
                    INSERT INTO per_bot_vault_accounts
                        (bot_id, activation_enabled, activation_equity, seed_amount,
                         trading_capital, cash_usd, activated_at)
                    VALUES (%s, TRUE, %s, %s, %s, %s, NOW())
                    ON CONFLICT (bot_id) DO NOTHING
                    RETURNING bot_id
                    """,
                    (bot_id, equity, seed, equity - seed, seed),
                )
                created = cur.fetchone()
                if not created:
                    result.append({"bot_id": bot_id, "action": "skipped_already_activated"})
                    continue
                cur.execute(
                    """
                    INSERT INTO per_bot_vault_deployment_queue (bot_id, pending_cash_usd)
                    VALUES (%s, %s)
                    ON CONFLICT (bot_id) DO NOTHING
                    """,
                    (bot_id, seed),
                )
                cur.executemany(
                    """
                    INSERT INTO per_bot_vault_holdings (bot_id, symbol)
                    VALUES (%s, %s)
                    ON CONFLICT (bot_id, symbol) DO NOTHING
                    """,
             [(bot_id, VAULT_BIL_SYMBOL), (bot_id, VAULT_VOO_SYMBOL)],
                )
                result.append({"bot_id": bot_id, "action": "activated", "seed": seed})
    return {"activated": True, "dry_run": False, "bots": result}


def _submit_vault_buy(bot_id: str, symbol: str, notional: float, queue_id: str) -> dict[str, Any]:
    """Submit one explicitly tagged vault order on the bot's own Alpaca account."""
    if not vault_enabled():
        raise RuntimeError("vault is inactive")
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest
    from core.order_ids import submit_with_unique_client_order_id

    key_name, secret_name = ACCOUNT_ENV[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing account credentials for {bot_id}")
    client = TradingClient(key, secret, paper=True)
    cash = float(client.get_account().cash or 0)
    if cash - float(notional) < 0:
        logger.critical(
            f"PerBotVault | insufficient cash — skipping {bot_id}/{symbol} "
            f"purchase=${float(notional):.2f} cash=${cash:.2f}; "
            "leaving pending cash untouched"
        )
        return {
            "status": "skipped",
            "reason": "insufficient_cash",
            "cash": cash,
            "notional": round(float(notional), 2),
        }
    order, client_id = submit_with_unique_client_order_id(
        lambda generated_id: client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                client_order_id=generated_id,
            )
        ),
        f"{VAULT_ORDER_PREFIX}{bot_id[:5]}-{queue_id}-{symbol.lower()}",
    )
    return {
        "order_id": str(order.id),
        "client_order_id": client_id,
        "status": str(order.status),
        "filled_qty": float(order.filled_qty or 0),
        "filled_avg_price": float(order.filled_avg_price or 0),
    }


def _read_vault_order(bot_id: str, order_id: str) -> dict[str, Any]:
    from alpaca.trading.client import TradingClient
    key_name, secret_name = ACCOUNT_ENV[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing account credentials for {bot_id}")
    order = TradingClient(key, secret, paper=True).get_order_by_id(order_id)
    return {
        "status": str(order.status).lower(),
        "filled_qty": float(order.filled_qty or 0),
        "filled_avg_price": float(order.filled_avg_price or 0),
    }


def reconcile_deployment_orders() -> dict[str, Any]:
    """Apply only newly observed fills; partial/failed orders remain retryable."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "updated": 0}
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"status": "blocked", "reason": "database_unavailable", "updated": 0}
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bot_id, bil_order_id, voo_order_id,
                          bil_filled_usd, voo_filled_usd
                   FROM per_bot_vault_deployment_queue
                   WHERE bil_order_id IS NOT NULL OR voo_order_id IS NOT NULL"""
            )
            rows = cur.fetchall()
    for bot_id, bil_order, voo_order, old_bil, old_voo in rows:
        for symbol, order_id, old_applied in (
            (VAULT_BIL_SYMBOL, bil_order, float(old_bil or 0)),
            (VAULT_VOO_SYMBOL, voo_order, float(old_voo or 0)),
        ):
            if not order_id:
                continue
            try:
                order = _read_vault_order(bot_id, order_id)
                filled_value = round(order["filled_qty"] * order["filled_avg_price"], 2)
                delta = round(max(0.0, filled_value - old_applied), 2)
                if delta <= 0 and order["status"] not in {"canceled", "rejected", "expired"}:
                    continue
                order_col = "bil_order_id" if symbol == VAULT_BIL_SYMBOL else "voo_order_id"
                applied_col = "bil_filled_usd" if symbol == VAULT_BIL_SYMBOL else "voo_filled_usd"
                pending_col = "pending_bil_usd" if symbol == VAULT_BIL_SYMBOL else "pending_voo_usd"
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        if delta > 0:
                            filled_qty_delta = round(delta / order["filled_avg_price"], 8) if order["filled_avg_price"] else 0
                            cur.execute(
                                """
                                UPDATE per_bot_vault_holdings
                                SET qty = qty + %s, cost_basis_usd = cost_basis_usd + %s,
                                    updated_at = NOW()
                                WHERE bot_id = %s AND symbol = %s
                                """,
                                (filled_qty_delta, delta, bot_id, symbol),
                            )
                            cur.execute(
                                """
                                UPDATE per_bot_vault_accounts
                                SET cash_usd = GREATEST(0, cash_usd - %s), updated_at = NOW()
                                WHERE bot_id = %s
                                """,
                                (delta, bot_id),
                            )
                        terminal = order["status"] in {"filled", "canceled", "rejected", "expired"}
                        cur.execute(
                            f"""
                            UPDATE per_bot_vault_deployment_queue
                            SET {applied_col} = %s,
                                {pending_col} = GREATEST(0, {pending_col} - %s),
                                {order_col} = CASE WHEN %s THEN NULL ELSE {order_col} END,
                                status = CASE WHEN %s THEN 'pending' ELSE 'submitted' END,
                                updated_at = NOW()
                            WHERE bot_id = %s
                            """,
                            (
                                filled_value,
                                delta,
                                terminal,
                                terminal and order["status"] != "filled",
                                bot_id,
                            ),
                        )
                updated += 1
            except Exception as exc:
                logger.warning(f"PerBotVault | order reconciliation failed {bot_id}/{symbol}: {exc}")
    return {"status": "complete", "updated": updated}


def run_deployment_cycle(*, market_open: bool, minimum_notional: float = MIN_TRADE_NOTIONAL) -> dict[str, Any]:
    """Deploy queued cash; failures leave the queue untouched for retry."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "orders": []}
    if not market_open:
        return {"status": "deferred", "reason": "market_closed", "orders": []}
    reconcile_deployment_orders()
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"status": "blocked", "reason": "database_unavailable", "orders": []}
    results: list[dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.bot_id, q.pending_cash_usd, q.pending_bil_usd,
                       q.pending_voo_usd, q.bil_order_id, q.voo_order_id,
                       q.attempts
                FROM per_bot_vault_deployment_queue q
                JOIN per_bot_vault_accounts a ON a.bot_id = q.bot_id
                WHERE a.activation_enabled = TRUE
                FOR UPDATE
                """
            )
            rows = cur.fetchall()
    for bot_id, pending_cash, pending_bil, pending_voo, bil_order, voo_order, attempts in rows:
        pending_cash = float(pending_cash or 0)
        if pending_cash and pending_cash < 2 * minimum_notional and not (pending_bil or pending_voo):
            results.append({"bot_id": bot_id, "status": "deferred", "reason": "below_minimum"})
            continue
        if pending_cash and not (pending_bil or pending_voo):
            bil, voo = split_contribution(pending_cash)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE per_bot_vault_deployment_queue
                        SET pending_cash_usd = 0, pending_bil_usd = %s,
                            pending_voo_usd = %s, updated_at = NOW()
                        WHERE bot_id = %s
                        """,
                        (bil, voo, bot_id),
                    )
            pending_bil, pending_voo = bil, voo
        for symbol, amount, existing_order in (
            (VAULT_BIL_SYMBOL, float(pending_bil or 0), bil_order),
            (VAULT_VOO_SYMBOL, float(pending_voo or 0), voo_order),
        ):
            if amount < minimum_notional or existing_order:
                continue
            try:
                order = _submit_vault_buy(bot_id, symbol, amount, f"{attempts + 1}-{symbol.lower()}")
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "submitted", **order})
                if order.get("status") == "skipped":
                    results[-1]["status"] = "skipped"
                    continue
                column = "bil_order_id" if symbol == VAULT_BIL_SYMBOL else "voo_order_id"
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE per_bot_vault_deployment_queue SET {column} = %s, status = 'submitted', attempts = attempts + 1, updated_at = NOW() WHERE bot_id = %s",
                            (order["order_id"], bot_id),
                        )
            except Exception as exc:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE per_bot_vault_deployment_queue SET status='retry', last_error=%s, attempts=attempts+1, updated_at=NOW() WHERE bot_id=%s",
                            (str(exc)[:500], bot_id),
                        )
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "retry", "error": str(exc)})
    return {"status": "complete", "orders": results}


def run_quarterly_rebalance(*, market_open: bool) -> dict[str, Any]:
    """Quarterly 50/50 planner; only explicitly tagged vault holdings qualify."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive"}
    if not market_open:
        return {"status": "deferred", "reason": "market_closed"}
    return {
        "status": "planned",
        "target": {"BIL": 0.50, "VOO": 0.50},
        "scope": "per_bot_vault_holdings_only",
        "order_prefix": VAULT_ORDER_PREFIX,
    }


def record_profitable_close(
    *,
    bot_id: str,
    source_trade_id: str,
    realized_profit: float,
    trading_capital_after_close: float | None = None,
) -> dict[str, Any]:
    """Record one winning close when activated; disabled mode is a true no-op."""
    skim = calculate_skim(realized_profit)
    if skim <= 0:
        return {"recorded": False, "reason": "no_profit", "skim_amount": 0.0}
    if not vault_enabled():
        return {"recorded": False, "reason": "inactive", "skim_amount": skim}
    if bot_id not in ACTIVE_BOT_IDS:
        return {"recorded": False, "reason": "unknown_bot", "skim_amount": skim}
    if not source_trade_id:
        return {"recorded": False, "reason": "missing_source_trade_id", "skim_amount": skim}

    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return {"recorded": False, "reason": "database_unavailable", "skim_amount": skim}
    bil, voo = split_contribution(skim)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT activation_enabled FROM per_bot_vault_accounts WHERE bot_id = %s FOR UPDATE",
                    (bot_id,),
                )
                account = cur.fetchone()
                if not account or not account[0]:
                    return {"recorded": False, "reason": "not_activated", "skim_amount": skim}
                cur.execute(
                    """
                    INSERT INTO per_bot_vault_contributions
                        (bot_id, source_trade_id, realized_profit, skim_amount,
                         bil_allocated, voo_allocated, cash_accrued)
                    VALUES (%s, %s, %s, %s, %s, %s, 0)
                    ON CONFLICT (bot_id, source_trade_id) DO NOTHING
                    RETURNING id
                    """,
                    (bot_id, source_trade_id, realized_profit, skim, bil, voo),
                )
                inserted = cur.fetchone()
                if not inserted:
                    return {"recorded": False, "reason": "duplicate", "skim_amount": skim}
                cur.execute(
                    """
                    UPDATE per_bot_vault_accounts
                    SET cash_usd = cash_usd + %s,
                        trading_capital = trading_capital + %s - %s,
                        cumulative_contributions = cumulative_contributions + %s,
                        updated_at = NOW()
                    WHERE bot_id = %s AND activation_enabled = TRUE
                    """,
                    (skim, realized_profit, skim, skim, bot_id),
                )
                cur.execute(
                    """
                    INSERT INTO per_bot_vault_deployment_queue (bot_id, pending_cash_usd)
                    VALUES (%s, %s)
                    ON CONFLICT (bot_id) DO UPDATE
                    SET pending_cash_usd =
                            per_bot_vault_deployment_queue.pending_cash_usd
                            + EXCLUDED.pending_cash_usd,
                        updated_at = NOW()
                    """,
                    (bot_id, skim),
                )
        return {
            "recorded": True,
            "bot_id": bot_id,
            "source_trade_id": source_trade_id,
            "realized_profit": round(float(realized_profit), 2),
            "skim_amount": skim,
            "bil_allocated": bil,
            "voo_allocated": voo,
            "cash_accrued": skim,
        }
    except Exception as exc:
        logger.error(f"PerBotVault | contribution failed for {bot_id}/{source_trade_id}: {exc}")
        return {"recorded": False, "reason": "error", "detail": str(exc), "skim_amount": skim}


def get_vault_report(bot_id: str | None = None) -> dict[str, Any]:
    """Return separate trading, vault, and combined values."""
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return {"enabled": vault_enabled(), "bots": [], "error": "database_unavailable"}
    ensure_schema()
    params: tuple[Any, ...] = (bot_id,) if bot_id else ()
    where = "WHERE a.bot_id = %s" if bot_id else ""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT a.bot_id, a.activation_enabled, a.activation_equity,
                       a.seed_amount, a.bil_qty, a.voo_qty, a.cash_usd,
                       a.cumulative_contributions, a.last_rebalance_date,
                       a.trading_capital AS trading_capital
                FROM per_bot_vault_accounts a
                LEFT JOIN bot_portfolio p ON p.bot_id = a.bot_id
                {where}
                ORDER BY a.bot_id
                """,
                params,
            )
            rows = [_row_dict(cur, row) for row in cur.fetchall()]
    reports = []
    for row in rows:
        trading = float(row["trading_capital"] or 0)
        activation = float(row["activation_equity"] or 0)
        contributions = float(row["cumulative_contributions"] or 0)
        cash = float(row["cash_usd"] or 0)
        vault_value = cash  # broker holdings are zero until explicit activation/deployment
        reports.append({
            "bot_id": row["bot_id"],
            "activation_enabled": bool(row["activation_enabled"]),
            "trading_capital": round(trading, 2),
            "trading_return_pct": trading_return_pct(trading, activation),
            "cumulative_contributions": round(contributions, 2),
            "vault_value": round(vault_value, 2),
            "vault_return_pct": round((vault_value / contributions - 1) * 100, 4) if contributions else 0.0,
            "combined_total": round(trading + vault_value, 2),
            "bil_qty": float(row["bil_qty"] or 0),
            "voo_qty": float(row["voo_qty"] or 0),
            "cash_usd": round(cash, 2),
            "last_rebalance_date": row["last_rebalance_date"].isoformat() if row["last_rebalance_date"] else None,
        })
    return {"enabled": vault_enabled(), "bots": reports}


def verification_report() -> dict[str, Any]:
    example = worked_example()
    return {
        "example": example,
        "losing_trade": {"profit": -10.0, "skim": calculate_skim(-10.0), "expected": 0.0},
        "trading_return_example": trading_return_pct(108.0, 100.0),
        "deployment_when_inactive": deployment_plan(10.0, market_open=True),
        "seed_preview": seed_preview(),
        "enabled": vault_enabled(),
    }