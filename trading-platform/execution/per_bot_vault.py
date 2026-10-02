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
TERMINAL_ORDER_STATUSES = {
    "filled",
    "canceled",
    "rejected",
    "expired",
    "done_for_day",
    "replaced",
}
ACCOUNT_ENV = {
    "oracle": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "spy_qqq_trend": ("ALPACA_BB_API_KEY", "ALPACA_BB_SECRET_KEY"),
    "jerome_macro": ("ALPACA_JEROME_API_KEY", "ALPACA_JEROME_SECRET_KEY"),
}


def vault_enabled() -> bool:
    """Explicit opt-in; absence or any value other than true keeps it off."""
    return os.environ.get("PER_BOT_VAULT_ENABLED", "").strip().lower() == "true"


def _order_status_value(order: Any) -> str:
    """Normalize Alpaca's enum status without serializing the enum class name."""
    status = getattr(order, "status", "")
    return str(getattr(status, "value", status)).strip().lower()


def _vault_client_order_id(bot_id: str, queue_id: str) -> str:
    """Build a stable, bounded ID from the queue's bot_id primary key and attempt."""
    from core.order_ids import client_order_id_environment_tag

    # The deployment queue has one row per bot, with bot_id as its primary key.
    # Including the attempt and symbol in queue_id distinguishes legitimate retries.
    prefix = (
        f"{VAULT_ORDER_PREFIX.lower()}{client_order_id_environment_tag()}-"
        f"{bot_id}-{queue_id}"
    ).lower()
    return prefix[:48]


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
    from core.order_ids import is_duplicate_client_order_id_error

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
    client_id = _vault_client_order_id(bot_id, queue_id)
    request = MarketOrderRequest(
        symbol=symbol,
        notional=round(notional, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_id,
    )
    try:
        order = client.submit_order(request)
    except Exception as exc:
        if not is_duplicate_client_order_id_error(exc):
            raise
        try:
            order = client.get_order_by_client_id(client_id)
        except Exception as lookup_exc:
            raise RuntimeError(
                f"duplicate vault client_order_id could not be adopted for {bot_id}/{symbol}"
            ) from lookup_exc
        logger.warning(
            f"PerBotVault | adopting existing broker order for {bot_id}/{symbol} "
            f"client_order_id={client_id}"
        )
    return {
        "order_id": str(order.id),
        "client_order_id": client_id,
        "status": _order_status_value(order),
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
        "status": _order_status_value(order),
        "filled_qty": float(order.filled_qty or 0),
        "filled_avg_price": float(order.filled_avg_price or 0),
        "replaced_by": str(order.replaced_by) if getattr(order, "replaced_by", None) else None,
    }


def reconcile_deployment_orders() -> dict[str, Any]:
    """Apply new fills and clear terminal broker orders from the queue."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "updated": 0, "orders": []}
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {
            "status": "blocked",
            "reason": "database_unavailable",
            "updated": 0,
            "orders": [],
        }
    updated = 0
    outcomes: list[dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT bot_id, bil_order_id, voo_order_id,
                          bil_filled_usd, voo_filled_usd,
                          pending_cash_usd, pending_bil_usd, pending_voo_usd
                   FROM per_bot_vault_deployment_queue
                   WHERE status = 'submitted'
                     AND (bil_order_id IS NOT NULL OR voo_order_id IS NOT NULL)"""
            )
            rows = cur.fetchall()
    for (
        bot_id,
        bil_order,
        voo_order,
        old_bil,
        old_voo,
        pending_cash,
        pending_bil,
        pending_voo,
    ) in rows:
        pending_cash = float(pending_cash or 0)
        pending_bil = float(pending_bil or 0)
        pending_voo = float(pending_voo or 0)
        active_orders = {
            VAULT_BIL_SYMBOL: bil_order,
            VAULT_VOO_SYMBOL: voo_order,
        }
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
                terminal = order["status"] in TERMINAL_ORDER_STATUSES
                replacement_order_id = order.get("replaced_by")
                clear_order = terminal and not replacement_order_id
                if delta <= 0 and not terminal:
                    continue
                order_col = "bil_order_id" if symbol == VAULT_BIL_SYMBOL else "voo_order_id"
                applied_col = "bil_filled_usd" if symbol == VAULT_BIL_SYMBOL else "voo_filled_usd"
                pending_col = "pending_bil_usd" if symbol == VAULT_BIL_SYMBOL else "pending_voo_usd"
                other_symbol = (
                    VAULT_VOO_SYMBOL if symbol == VAULT_BIL_SYMBOL else VAULT_BIL_SYMBOL
                )
                other_order_id = active_orders[other_symbol]
                next_pending_bil = max(
                    0.0,
                    pending_bil - (delta if symbol == VAULT_BIL_SYMBOL else 0.0),
                )
                next_pending_voo = max(
                    0.0,
                    pending_voo - (delta if symbol == VAULT_VOO_SYMBOL else 0.0),
                )
                active_order_remains = (
                    bool(other_order_id) or (not terminal) or bool(replacement_order_id)
                )
                queue_order_id = (
                    replacement_order_id
                    if replacement_order_id
                    else None
                    if clear_order
                    else order_id
                )
                retryable_cash_remains = (
                    pending_cash >= 2 * MIN_TRADE_NOTIONAL
                    or next_pending_bil >= MIN_TRADE_NOTIONAL
                    or next_pending_voo >= MIN_TRADE_NOTIONAL
                )
                next_status = (
                    "submitted"
                    if active_order_remains
                    else "pending"
                    if retryable_cash_remains
                    else "complete"
                )
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
                        cur.execute(
                            f"""
                            UPDATE per_bot_vault_deployment_queue
                            SET {applied_col} = %s,
                                {pending_col} = GREATEST(0, {pending_col} - %s),
                                {order_col} = %s,
                                status = %s,
                                updated_at = NOW()
                            WHERE bot_id = %s
                            """,
                            (
                                filled_value,
                                delta,
                                queue_order_id,
                                next_status,
                                bot_id,
                            ),
                        )
                active_orders[symbol] = queue_order_id
                pending_bil = next_pending_bil
                pending_voo = next_pending_voo
                updated += 1
                outcomes.append(
                    {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "order_id": order_id,
                        "broker_status": order["status"],
                        "filled_value_usd": filled_value,
                        "new_fill_usd": delta,
                        "terminal": terminal,
                        "replacement_order_id": replacement_order_id,
                        "queue_status": next_status,
                    }
                )
            except Exception as exc:
                logger.warning(f"PerBotVault | order reconciliation failed {bot_id}/{symbol}: {exc}")
                outcomes.append(
                    {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "order_id": order_id,
                        "error": str(exc),
                    }
                )
    return {"status": "complete", "updated": updated, "orders": outcomes}


def run_deployment_cycle(*, market_open: bool, minimum_notional: float = MIN_TRADE_NOTIONAL) -> dict[str, Any]:
    """Deploy queued cash; failures leave the queue untouched for retry."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "orders": []}
    reconciliation = reconcile_deployment_orders()
    if not market_open:
        return {
            "status": "deferred",
            "reason": "market_closed",
            "orders": [],
            "reconciliation": reconciliation,
        }
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
        attempts = int(attempts or 0)
        if pending_cash and pending_cash < 2 * minimum_notional and not (pending_bil or pending_voo):
            results.append({"bot_id": bot_id, "status": "deferred", "reason": "below_minimum"})
            continue
        if pending_cash:
            bil_addition, voo_addition = split_contribution(pending_cash)
            bil = round(float(pending_bil or 0) + bil_addition, 2)
            voo = round(float(pending_voo or 0) + voo_addition, 2)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE per_bot_vault_deployment_queue
                        SET pending_cash_usd = 0, pending_bil_usd = %s,
                            pending_voo_usd = %s,
                            status = CASE
                                WHEN bil_order_id IS NOT NULL OR voo_order_id IS NOT NULL
                                THEN 'submitted' ELSE 'pending'
                            END,
                            updated_at = NOW()
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
                            f"UPDATE per_bot_vault_deployment_queue SET {column} = %s, status = 'submitted', attempts = attempts + 1, last_error = NULL, updated_at = NOW() WHERE bot_id = %s",
                            (order["order_id"], bot_id),
                        )
                attempts += 1
            except Exception as exc:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE per_bot_vault_deployment_queue
                            SET status = CASE
                                    WHEN bil_order_id IS NOT NULL OR voo_order_id IS NOT NULL
                                    THEN 'submitted' ELSE 'retry'
                                END,
                                last_error = %s, updated_at = NOW()
                            WHERE bot_id = %s
                            """,
                            (str(exc)[:500], bot_id),
                        )
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "retry", "error": str(exc)})
                # Keep the same deterministic ID for the next cycle. The request
                # may have reached Alpaca even if the response or DB write failed.
                break
    return {"status": "complete", "orders": results}


def get_vault_inspection(
    bot_id: str | None = None,
    *,
    contribution_limit: int = 100,
) -> dict[str, Any]:
    """Read queue state, broker order states, and recent skims without mutation."""
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return {
            "enabled": vault_enabled(),
            "read_only": True,
            "bots": [],
            "orders": [],
            "skims": [],
            "error": "database_unavailable",
        }
    contribution_limit = max(1, min(int(contribution_limit), 200))
    params: tuple[Any, ...] = (bot_id,) if bot_id else ()
    where = "WHERE a.bot_id = %s" if bot_id else ""
    contribution_where = "WHERE bot_id = %s" if bot_id else ""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT a.bot_id, a.activation_enabled,
                       q.pending_cash_usd, q.pending_bil_usd, q.pending_voo_usd,
                       q.bil_order_id, q.voo_order_id,
                       q.bil_filled_usd, q.voo_filled_usd,
                       q.status, q.attempts, q.last_error, q.updated_at
                FROM per_bot_vault_accounts a
                LEFT JOIN per_bot_vault_deployment_queue q ON q.bot_id = a.bot_id
                {where}
                ORDER BY a.bot_id
                """,
                params,
            )
            queue_rows = [_row_dict(cur, row) for row in cur.fetchall()]
            cur.execute(
                f"""
                SELECT bot_id, source_trade_id, realized_profit, skim_amount,
                       bil_allocated, voo_allocated, cash_accrued, created_at
                FROM per_bot_vault_contributions
                {contribution_where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (*params, contribution_limit),
            )
            skim_rows = [_row_dict(cur, row) for row in cur.fetchall()]

    bots: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    for row in queue_rows:
        bot = {
            "bot_id": row["bot_id"],
            "activation_enabled": bool(row["activation_enabled"]),
            "pending_cash_usd": float(row["pending_cash_usd"] or 0),
            "pending_bil_usd": float(row["pending_bil_usd"] or 0),
            "pending_voo_usd": float(row["pending_voo_usd"] or 0),
            "bil_order_id": row["bil_order_id"],
            "voo_order_id": row["voo_order_id"],
            "bil_filled_usd": float(row["bil_filled_usd"] or 0),
            "voo_filled_usd": float(row["voo_filled_usd"] or 0),
            "status": row["status"],
            "attempts": int(row["attempts"] or 0),
            "last_error": row["last_error"],
            "updated_at": (
                row["updated_at"].isoformat()
                if hasattr(row["updated_at"], "isoformat")
                else row["updated_at"]
            ),
        }
        bots.append(bot)
        for symbol, order_id in (
            (VAULT_BIL_SYMBOL, row["bil_order_id"]),
            (VAULT_VOO_SYMBOL, row["voo_order_id"]),
        ):
            if not order_id:
                continue
            order_report: dict[str, Any] = {
                "bot_id": row["bot_id"],
                "symbol": symbol,
                "order_id": str(order_id),
            }
            try:
                order_report.update(_read_vault_order(row["bot_id"], order_id))
            except Exception as exc:
                order_report["error"] = str(exc)
            orders.append(order_report)

    skims = []
    for row in skim_rows:
        skims.append(
            {
                "bot_id": row["bot_id"],
                "source_trade_id": row["source_trade_id"],
                "realized_profit": float(row["realized_profit"] or 0),
                "skim_amount": float(row["skim_amount"] or 0),
                "bil_allocated": float(row["bil_allocated"] or 0),
                "voo_allocated": float(row["voo_allocated"] or 0),
                "cash_accrued": float(row["cash_accrued"] or 0),
                "created_at": (
                    row["created_at"].isoformat()
                    if hasattr(row["created_at"], "isoformat")
                    else row["created_at"]
                ),
            }
        )
    return {
        "enabled": vault_enabled(),
        "read_only": True,
        "bots": bots,
        "orders": orders,
        "skims": skims,
    }


def preview_deployment_cycle(
    *,
    market_open: bool,
    minimum_notional: float = MIN_TRADE_NOTIONAL,
) -> dict[str, Any]:
    """Read queue and broker order state and describe the next cycle without writes."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "read_only": True, "queues": []}
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        return {
            "status": "blocked",
            "reason": "database_unavailable",
            "read_only": True,
            "queues": [],
        }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.bot_id, q.pending_cash_usd, q.pending_bil_usd,
                       q.pending_voo_usd, q.bil_order_id, q.voo_order_id,
                       q.bil_filled_usd, q.voo_filled_usd, q.attempts, q.status
                FROM per_bot_vault_deployment_queue q
                JOIN per_bot_vault_accounts a ON a.bot_id = q.bot_id
                WHERE a.activation_enabled = TRUE
                ORDER BY q.bot_id
                """
            )
            rows = cur.fetchall()

    queues: list[dict[str, Any]] = []
    reconciliation_orders: list[dict[str, Any]] = []
    planned_orders: list[dict[str, Any]] = []
    for (
        bot_id,
        pending_cash_value,
        pending_bil_value,
        pending_voo_value,
        bil_order_id,
        voo_order_id,
        bil_filled_value,
        voo_filled_value,
        attempts_value,
        current_status,
    ) in rows:
        pending_cash = float(pending_cash_value or 0)
        pending = {
            VAULT_BIL_SYMBOL: float(pending_bil_value or 0),
            VAULT_VOO_SYMBOL: float(pending_voo_value or 0),
        }
        applied = {
            VAULT_BIL_SYMBOL: float(bil_filled_value or 0),
            VAULT_VOO_SYMBOL: float(voo_filled_value or 0),
        }
        order_ids = {
            VAULT_BIL_SYMBOL: bil_order_id,
            VAULT_VOO_SYMBOL: voo_order_id,
        }
        order_errors: list[str] = []
        reconciled_terminal_order = False

        for symbol in (VAULT_BIL_SYMBOL, VAULT_VOO_SYMBOL):
            order_id = order_ids[symbol]
            if not order_id:
                continue
            try:
                order = _read_vault_order(bot_id, order_id)
                filled_value = round(
                    order["filled_qty"] * order["filled_avg_price"], 2
                )
                delta = round(max(0.0, filled_value - applied[symbol]), 2)
                terminal = order["status"] in TERMINAL_ORDER_STATUSES
                if delta > 0:
                    pending[symbol] = max(0.0, round(pending[symbol] - delta, 2))
                    applied[symbol] = filled_value
                if terminal:
                    order_ids[symbol] = (
                        str(order["replaced_by"])
                        if order.get("replaced_by")
                        else None
                    )
                    reconciled_terminal_order = True
                reconciliation_orders.append(
                    {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "order_id": order_id,
                        "broker_status": order["status"],
                        "filled_value_usd": filled_value,
                        "new_fill_usd": delta,
                        "would_clear_order_id": terminal,
                        "replacement_order_id": order.get("replaced_by"),
                    }
                )
            except Exception as exc:
                order_errors.append(f"{symbol}/{order_id}: {exc}")
                reconciliation_orders.append(
                    {
                        "bot_id": bot_id,
                        "symbol": symbol,
                        "order_id": order_id,
                        "error": str(exc),
                    }
                )

        actions: list[dict[str, Any]] = []
        projected_cash = pending_cash
        split_cash = False
        if market_open:
            if (
                projected_cash
                and projected_cash < 2 * minimum_notional
                and not pending[VAULT_BIL_SYMBOL]
                and not pending[VAULT_VOO_SYMBOL]
            ):
                actions.append(
                    {
                        "action": "deferred_below_minimum",
                        "pending_cash_usd": round(projected_cash, 2),
                    }
                )
            elif projected_cash:
                bil_addition, voo_addition = split_contribution(projected_cash)
                pending[VAULT_BIL_SYMBOL] = round(
                    pending[VAULT_BIL_SYMBOL] + bil_addition, 2
                )
                pending[VAULT_VOO_SYMBOL] = round(
                    pending[VAULT_VOO_SYMBOL] + voo_addition, 2
                )
                projected_cash = 0.0
                split_cash = True

        for symbol in (VAULT_BIL_SYMBOL, VAULT_VOO_SYMBOL):
            amount = pending[symbol]
            if order_ids[symbol]:
                actions.append(
                    {
                        "action": "wait_for_open_order",
                        "symbol": symbol,
                        "order_id": order_ids[symbol],
                        "pending_usd": round(amount, 2),
                    }
                )
            elif amount < minimum_notional:
                actions.append(
                    {
                        "action": "below_minimum",
                        "symbol": symbol,
                        "pending_usd": round(amount, 2),
                    }
                )
            elif not market_open:
                actions.append(
                    {
                        "action": "deferred_market_closed",
                        "symbol": symbol,
                        "pending_usd": round(amount, 2),
                    }
                )
            else:
                client_order_id = _vault_client_order_id(
                    bot_id, f"{int(attempts_value or 0) + 1}-{symbol.lower()}"
                )
                action = {
                    "action": "would_submit",
                    "symbol": symbol,
                    "notional_usd": round(amount, 2),
                    "client_order_id": client_order_id,
                }
                actions.append(action)
                planned_orders.append({"bot_id": bot_id, **action})

        any_active_order = any(order_ids.values())
        actionable_pending = (
            projected_cash >= 2 * minimum_notional
            or pending[VAULT_BIL_SYMBOL] >= minimum_notional
            or pending[VAULT_VOO_SYMBOL] >= minimum_notional
        )
        projected_status = (
            "submitted"
            if any_active_order or any(
                action["action"] == "would_submit" for action in actions
            )
            else "pending"
            if actionable_pending or split_cash
            else "complete"
            if reconciled_terminal_order
            else current_status
        )
        queues.append(
            {
                "bot_id": bot_id,
                "current_status": current_status,
                "projected_status": projected_status,
                "pending_cash_usd": round(projected_cash, 2),
                "pending_bil_usd": round(pending[VAULT_BIL_SYMBOL], 2),
                "pending_voo_usd": round(pending[VAULT_VOO_SYMBOL], 2),
                "bil_order_id_after": order_ids[VAULT_BIL_SYMBOL],
                "voo_order_id_after": order_ids[VAULT_VOO_SYMBOL],
                "attempts": int(attempts_value or 0),
                "actions": actions,
                "errors": order_errors,
            }
        )

    return {
        "status": "preview",
        "read_only": True,
        "market_open": bool(market_open),
        "reconciliation_orders": reconciliation_orders,
        "would_submit": planned_orders,
        "queues": queues,
    }


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
                        status = CASE
                            WHEN per_bot_vault_deployment_queue.bil_order_id IS NOT NULL
                              OR per_bot_vault_deployment_queue.voo_order_id IS NOT NULL
                            THEN 'submitted' ELSE 'pending'
                        END,
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


def _latest_vault_prices(bot_id: str, symbols: set[str]) -> dict[str, float]:
    """Read current broker marks for vault-owned symbols on the bot's account."""
    if not symbols:
        return {}
    from alpaca.trading.client import TradingClient

    key_name, secret_name = ACCOUNT_ENV[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing account credentials for {bot_id}")
    positions = TradingClient(key, secret, paper=True).get_all_positions()
    prices: dict[str, float] = {}
    for position in positions:
        symbol = str(getattr(position, "symbol", "")).upper()
        if symbol not in symbols:
            continue
        raw_price = getattr(position, "current_price", None)
        price = float(raw_price or 0)
        if price <= 0:
            raise RuntimeError(f"broker returned no current price for {bot_id}/{symbol}")
        prices[symbol] = price
    missing = sorted(symbols - prices.keys())
    if missing:
        raise RuntimeError(
            f"broker has no current position price for {bot_id}: {', '.join(missing)}"
        )
    return prices


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
                       a.seed_amount,
                       COALESCE(h.bil_qty, a.bil_qty) AS bil_qty,
                       COALESCE(h.voo_qty, a.voo_qty) AS voo_qty,
                       a.cash_usd,
                       a.cumulative_contributions, a.last_rebalance_date,
                       a.trading_capital AS trading_capital
                FROM per_bot_vault_accounts a
                LEFT JOIN bot_portfolio p ON p.bot_id = a.bot_id
                LEFT JOIN (
                    SELECT bot_id,
                           SUM(qty) FILTER (WHERE symbol = 'BIL') AS bil_qty,
                           SUM(qty) FILTER (WHERE symbol = 'VOO') AS voo_qty
                    FROM per_bot_vault_holdings
                    GROUP BY bot_id
                ) h ON h.bot_id = a.bot_id
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
        bil_qty = float(row["bil_qty"] or 0)
        voo_qty = float(row["voo_qty"] or 0)
        requested_symbols = {
            symbol
            for symbol, qty in (
                (VAULT_BIL_SYMBOL, bil_qty),
                (VAULT_VOO_SYMBOL, voo_qty),
            )
            if qty > 0
        }
        prices = _latest_vault_prices(row["bot_id"], requested_symbols)
        bil_value = bil_qty * prices.get(VAULT_BIL_SYMBOL, 0.0)
        voo_value = voo_qty * prices.get(VAULT_VOO_SYMBOL, 0.0)
        vault_value = cash + bil_value + voo_value
        reports.append({
            "bot_id": row["bot_id"],
            "activation_enabled": bool(row["activation_enabled"]),
            "trading_capital": round(trading, 2),
            "trading_return_pct": trading_return_pct(trading, activation),
            "cumulative_contributions": round(contributions, 2),
            "vault_value": round(vault_value, 2),
            "vault_return_pct": round((vault_value / contributions - 1) * 100, 4) if contributions else 0.0,
            "combined_total": round(trading + vault_value, 2),
            "bil_qty": bil_qty,
            "bil_price": round(prices[VAULT_BIL_SYMBOL], 4) if VAULT_BIL_SYMBOL in prices else None,
            "bil_market_value": round(bil_value, 2),
            "voo_qty": voo_qty,
            "voo_price": round(prices[VAULT_VOO_SYMBOL], 4) if VAULT_VOO_SYMBOL in prices else None,
            "voo_market_value": round(voo_value, 2),
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