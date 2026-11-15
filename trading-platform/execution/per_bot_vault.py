"""Per-bot profit vault (VAULT-V2, sleeve_runtime/VAULT-V2-SPEC.md).

Each account's vault is tagged cash and BIL inside its own Alpaca account.
Rule (VAULT-V2): on the first run of each month, before the open, skim 10% of
the account's new high-water gain on trading equity (broker equity minus the
vault) into the vault, then reset the mark to post-skim trading equity. The
vault holds BIL only; the VOO left by VAULT-V1 is sold once and rebought as
BIL. The per-trade skim and the quarterly 50/50 rebalance are retired.

Separate from the retired global JEPQ/HWM vault in profit_sweep.py. Disabled
mode (PER_BOT_VAULT_ENABLED not true) performs no writes and no broker calls.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from uuid import uuid4
from typing import Any

from loguru import logger

# Deliberately remains an Alpaca-only allowlist; forex_ai has no Alpaca vault.
ACTIVE_BOT_IDS = ("oracle", "spy_qqq_trend", "jerome_macro")
SKIM_RATE = 0.10          # VAULT-V2: share of each month's new high-water gain
SEED_RATE = 0.05          # VAULT-V1 activation seed (history; activation code unchanged)
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


def hwm_skim(trading_equity: float, mark: float) -> tuple[float, float]:
    """VAULT-V2 rule: (skim, new mark). 10% of the gain above the mark; the mark
    resets to post-skim trading equity. At or below the mark nothing moves."""
    equity, mark = float(trading_equity), float(mark)
    if equity <= mark:
        return 0.0, mark
    skim = round((equity - mark) * SKIM_RATE, 2)
    return skim, round(equity - skim, 2)


def plan_skim(*, month: str, trading_equity: float, mark: float | None,
              mark_month: str | None, skimmed_months: set[str]) -> dict[str, Any]:
    """Pure decision for one account on one run. `month` is the run's NY month
    (YYYY-MM); the run is before the open, so equity is the previous close."""
    if mark is None:
        return {"action": "seed", "mark_after": round(float(trading_equity), 2), "amount": 0.0}
    if month in skimmed_months or mark_month == month:
        return {"action": "none", "reason": "done_this_month" if month in skimmed_months else "seeded_this_month"}
    amount, mark_after = hwm_skim(trading_equity, mark)
    return {"action": "skim" if amount > 0 else "below_mark", "amount": amount,
            "mark_before": round(float(mark), 2), "mark_after": mark_after}


def calculate_skim(realized_profit: float) -> float:
    """VAULT-V1 per-trade rate, kept only for the verification report's history."""
    return round(max(0.0, float(realized_profit)) * 0.20, 2)


def split_contribution(skim_amount: float) -> tuple[float, float]:
    """VAULT-V2: every contribution goes to BIL. Returns (bil, voo=0)."""
    return round(max(0.0, float(skim_amount)), 2), 0.0


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


def next_skim_day(today: date) -> date:
    """First weekday of next month (exchange holidays not modelled: the job then
    runs that morning anyway, on the previous close)."""
    from datetime import timedelta
    d = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


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
    """Deterministic VAULT-V2 example used by the verification harness."""
    mark, equity = 100_000.0, 103_000.0
    skim, mark_after = hwm_skim(equity, mark)
    down_skim, down_mark = hwm_skim(98_000.0, mark_after)
    return {
        "mark": mark,
        "trading_equity": equity,
        "skim": skim,
        "mark_after": mark_after,
        "next_month_trading_equity": 98_000.0,
        "next_month_skim": down_skim,
        "next_month_mark": down_mark,
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
    CREATE TABLE IF NOT EXISTS per_bot_vault_marks (
        bot_id              TEXT PRIMARY KEY REFERENCES per_bot_vault_accounts(bot_id),
        high_water_mark     NUMERIC NOT NULL,
        mark_month          TEXT NOT NULL,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS per_bot_vault_skims (
        id                  BIGSERIAL PRIMARY KEY,
        bot_id              TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
        month               TEXT NOT NULL,
        as_of               DATE NOT NULL,
        broker_equity       NUMERIC NOT NULL,
        vault_value         NUMERIC NOT NULL,
        trading_equity      NUMERIC NOT NULL,
        mark_before         NUMERIC NOT NULL,
        mark_after          NUMERIC NOT NULL,
        amount              NUMERIC NOT NULL,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (bot_id, month)
    );
    CREATE TABLE IF NOT EXISTS per_bot_vault_liquidations (
        bot_id              TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
        symbol              TEXT NOT NULL,
        order_id            TEXT,
        qty                 NUMERIC NOT NULL,
        status              TEXT NOT NULL DEFAULT 'submitted',
        proceeds_usd        NUMERIC NOT NULL DEFAULT 0,
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


# Circuit breaker (Claude's design value, 22 Oct 2026): a normal day needs a
# handful of vault buys per bot; more than this means something is looping.
# Counted per process and New York day; a restart resets it, which is fine
# for a breaker whose job is to stop a runaway within one day.
DAILY_ORDER_CAP = 10
_orders_today: dict[tuple[str, str], int] = {}


def _orders_blocked(bot_id: str) -> str | None:
    """Why the vault may not place an order for this bot now, or None. The
    vault obeys the same switches as the bots: a paused bot and a tripped
    kill-switch latch place no vault orders (16 Nov 2026 order-path audit,
    F4). Both reads fail closed. Reading and recording broker fills still runs."""
    from core.bot_state import is_paused
    from core.kill_switch import latch_tripped
    if latch_tripped():
        return "kill_switch_latched"
    if is_paused(bot_id):
        return "bot_paused"
    return None


def _ny_day() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _count_order(bot_id: str) -> None:
    key = (bot_id, _ny_day())
    _orders_today[key] = _orders_today.get(key, 0) + 1


def _order_budget_left(bot_id: str) -> bool:
    if _orders_today.get((bot_id, _ny_day()), 0) < DAILY_ORDER_CAP:
        return True
    logger.critical(f"PerBotVault | {bot_id} hit {DAILY_ORDER_CAP} vault orders today; no more buys until tomorrow")
    try:
        from core.degradation_tracker import record_degradation
        record_degradation(component="per_bot_vault", severity="critical", error_type="daily_order_cap",
                           message=f"Vault order cap hit ({DAILY_ORDER_CAP} today): possible loop, buys stopped",
                           bot_id=bot_id)
    except Exception as exc:
        logger.warning(f"PerBotVault | cap alert failed: {exc}")
    return False


def run_deployment_cycle(*, market_open: bool, minimum_notional: float = MIN_TRADE_NOTIONAL) -> dict[str, Any]:
    """Deploy queued cash; failures leave the queue untouched for retry."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "orders": []}
    reconciliation = reconcile_deployment_orders()
    liquidation = run_voo_liquidation(market_open=market_open)
    if not market_open:
        return {
            "status": "deferred",
            "reason": "market_closed",
            "orders": [],
            "reconciliation": reconciliation,
            "liquidation": liquidation,
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
        blocked = _orders_blocked(bot_id)
        if blocked:
            results.append({"bot_id": bot_id, "status": "blocked", "reason": blocked})
            continue
        pending_cash = float(pending_cash or 0)
        attempts = int(attempts or 0)
        if pending_cash and pending_cash < minimum_notional and not (pending_bil or pending_voo):
            results.append({"bot_id": bot_id, "status": "deferred", "reason": "below_minimum"})
            continue
        # VAULT-V2: everything is bought as BIL. A VOO amount still pending from
        # VAULT-V1 moves to BIL unless a VOO buy is still open at the broker.
        fold_voo = float(pending_voo or 0) if not voo_order else 0.0
        if pending_cash or fold_voo:
            bil_addition, _ = split_contribution(pending_cash)
            bil = round(float(pending_bil or 0) + bil_addition + fold_voo, 2)
            voo = round(float(pending_voo or 0) - fold_voo, 2)
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
            if not _order_budget_left(bot_id):
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "blocked",
                                "reason": "daily_order_cap"})
                continue
            try:
                order = _submit_vault_buy(bot_id, symbol, amount, f"{attempts + 1}-{symbol.lower()}")
                if order.get("status") != "skipped":
                    _count_order(bot_id)
                results.append({"bot_id": bot_id, "symbol": symbol, "status": "submitted", **order})
                if order.get("status") == "skipped":
                    results[-1]["status"] = "skipped"
                    continue
                column = "bil_order_id" if symbol == VAULT_BIL_SYMBOL else "voo_order_id"
                applied_col = "bil_filled_usd" if symbol == VAULT_BIL_SYMBOL else "voo_filled_usd"
                # The applied amount belongs to the order in the queue. A new
                # order starts at zero; otherwise its fill is compared with the
                # previous order's and never recorded, and the same pending
                # amount is bought again every cycle (oracle, 15-21 Oct 2026).
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE per_bot_vault_deployment_queue SET {column} = %s, {applied_col} = 0, status = 'submitted', attempts = attempts + 1, last_error = NULL, updated_at = NOW() WHERE bot_id = %s",
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
    return {"status": "complete", "orders": results, "liquidation": liquidation}


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
                and projected_cash < minimum_notional
                and not pending[VAULT_BIL_SYMBOL]
                and not pending[VAULT_VOO_SYMBOL]
            ):
                actions.append(
                    {
                        "action": "deferred_below_minimum",
                        "pending_cash_usd": round(projected_cash, 2),
                    }
                )
            elif projected_cash or (pending[VAULT_VOO_SYMBOL] and not order_ids[VAULT_VOO_SYMBOL]):
                # Same as run_deployment_cycle: cash and any VAULT-V1 VOO amount go to BIL.
                fold_voo = pending[VAULT_VOO_SYMBOL] if not order_ids[VAULT_VOO_SYMBOL] else 0.0
                bil_addition, _ = split_contribution(projected_cash)
                pending[VAULT_BIL_SYMBOL] = round(
                    pending[VAULT_BIL_SYMBOL] + bil_addition + fold_voo, 2
                )
                pending[VAULT_VOO_SYMBOL] = round(pending[VAULT_VOO_SYMBOL] - fold_voo, 2)
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


# VAULT-V2 retired the quarterly 50/50 rebalance and the per-trade hook
# (record_profitable_close): profit is measured monthly on equity instead.


# ── VAULT-V2: sell the VAULT-V1 VOO once and rebuy it as BIL ────────────────

def _submit_vault_sell(bot_id: str, symbol: str, qty: float, tag: str) -> dict[str, Any]:
    """Sell vault-owned shares, never more than the broker position."""
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
    held = 0.0
    for pos in client.get_all_positions():
        if str(getattr(pos, "symbol", "")).upper() == symbol:
            held = float(getattr(pos, "qty", 0) or 0)
    qty = round(min(float(qty), held), 9)
    if qty <= 0:
        return {"status": "skipped", "reason": "no_broker_position", "qty": 0.0}
    client_id = _vault_client_order_id(bot_id, tag)
    request = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.SELL,
                                 time_in_force=TimeInForce.DAY, client_order_id=client_id)
    try:
        order = client.submit_order(request)
    except Exception as exc:
        if not is_duplicate_client_order_id_error(exc):
            raise
        order = client.get_order_by_client_id(client_id)
    return {"order_id": str(order.id), "client_order_id": client_id,
            "status": _order_status_value(order), "qty": qty}


def run_voo_liquidation(*, market_open: bool) -> dict[str, Any]:
    """One-time transition: sell each vault's VOO; proceeds become pending vault
    cash, which the deployment cycle buys as BIL. Partial or failed sells are
    retried; a completed sell is never repeated."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "bots": []}
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"status": "blocked", "reason": "database_unavailable", "bots": []}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.bot_id, COALESCE(h.qty, 0), h.cost_basis_usd, l.order_id, l.status, q.voo_order_id
                FROM per_bot_vault_accounts a
                LEFT JOIN per_bot_vault_holdings h ON h.bot_id = a.bot_id AND h.symbol = 'VOO'
                LEFT JOIN per_bot_vault_liquidations l ON l.bot_id = a.bot_id AND l.symbol = 'VOO'
                LEFT JOIN per_bot_vault_deployment_queue q ON q.bot_id = a.bot_id
                WHERE a.activation_enabled = TRUE
                ORDER BY a.bot_id
                """
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for bot_id, qty, cost_basis, order_id, status, open_voo_buy in rows:
        qty, cost_basis = float(qty or 0), float(cost_basis or 0)
        try:
            if status == "submitted" and order_id:
                order = _read_vault_order(bot_id, order_id)
                if order["status"] not in TERMINAL_ORDER_STATUSES:
                    out.append({"bot_id": bot_id, "action": "wait", "order_id": order_id})
                    continue
                if order.get("replaced_by"):
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE per_bot_vault_liquidations SET order_id = %s, updated_at = NOW() "
                                        "WHERE bot_id = %s AND symbol = 'VOO'", (order["replaced_by"], bot_id))
                    out.append({"bot_id": bot_id, "action": "wait", "order_id": order["replaced_by"]})
                    continue
                sold = min(qty, float(order["filled_qty"]))
                proceeds = round(sold * float(order["filled_avg_price"]), 2)
                left = max(0.0, qty - sold)
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE per_bot_vault_holdings SET qty = %s, cost_basis_usd = %s, updated_at = NOW() "
                            "WHERE bot_id = %s AND symbol = 'VOO'",
                            (left, round(cost_basis * (left / qty), 2) if qty else 0.0, bot_id))
                        cur.execute("UPDATE per_bot_vault_accounts SET cash_usd = cash_usd + %s, updated_at = NOW() "
                                    "WHERE bot_id = %s", (proceeds, bot_id))
                        cur.execute(
                            """
                            INSERT INTO per_bot_vault_deployment_queue (bot_id, pending_cash_usd)
                            VALUES (%s, %s)
                            ON CONFLICT (bot_id) DO UPDATE
                            SET pending_cash_usd = per_bot_vault_deployment_queue.pending_cash_usd + EXCLUDED.pending_cash_usd,
                                status = CASE WHEN per_bot_vault_deployment_queue.bil_order_id IS NOT NULL
                                              THEN 'submitted' ELSE 'pending' END,
                                updated_at = NOW()
                            """, (bot_id, proceeds))
                        if left > 1e-6:
                            # Partial fill or cancel: forget this order so the next cycle sells the rest.
                            cur.execute("DELETE FROM per_bot_vault_liquidations WHERE bot_id = %s AND symbol = 'VOO'",
                                        (bot_id,))
                        else:
                            cur.execute("UPDATE per_bot_vault_liquidations SET status = 'complete', "
                                        "proceeds_usd = proceeds_usd + %s, updated_at = NOW() "
                                        "WHERE bot_id = %s AND symbol = 'VOO'", (proceeds, bot_id))
                logger.info(f"PerBotVault | {bot_id} sold {sold:.6f} VOO for ${proceeds:.2f}; queued for BIL")
                out.append({"bot_id": bot_id, "action": "sold", "qty": sold, "proceeds": proceeds, "left": left})
                continue
            if status == "complete" or qty <= 1e-6:
                continue
            if not market_open or open_voo_buy:
                out.append({"bot_id": bot_id, "action": "deferred",
                            "reason": "market_closed" if not market_open else "open_voo_buy"})
                continue
            blocked = _orders_blocked(bot_id)
            if blocked:
                out.append({"bot_id": bot_id, "action": "blocked", "reason": blocked})
                continue
            if not _order_budget_left(bot_id):
                out.append({"bot_id": bot_id, "action": "blocked", "reason": "daily_order_cap"})
                continue
            order = _submit_vault_sell(bot_id, VAULT_VOO_SYMBOL, qty, f"sell-voo-{datetime.now(timezone.utc):%Y%m%d%H%M}")
            if order.get("status") == "skipped":
                logger.critical(f"PerBotVault | {bot_id} vault says {qty} VOO but the broker holds none")
                out.append({"bot_id": bot_id, "action": "skipped", "reason": order["reason"]})
                continue
            _count_order(bot_id)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO per_bot_vault_liquidations (bot_id, symbol, order_id, qty, status)
                        VALUES (%s, 'VOO', %s, %s, 'submitted')
                        ON CONFLICT (bot_id, symbol) DO UPDATE
                        SET order_id = EXCLUDED.order_id, qty = EXCLUDED.qty, status = 'submitted', updated_at = NOW()
                        """, (bot_id, order["order_id"], order["qty"]))
            out.append({"bot_id": bot_id, "action": "submitted", **order})
        except Exception as exc:
            logger.error(f"PerBotVault | VOO liquidation failed for {bot_id}: {exc}")
            out.append({"bot_id": bot_id, "action": "error", "error": str(exc)})
    return {"status": "complete", "bots": out}


# ── VAULT-V2: the monthly high-water skim ───────────────────────────────────

def _broker_equity(bot_id: str) -> float:
    from alpaca.trading.client import TradingClient
    key_name, secret_name = ACCOUNT_ENV[bot_id]
    key, secret = os.environ.get(key_name, ""), os.environ.get(secret_name, "")
    if not key or not secret:
        raise RuntimeError(f"missing account credentials for {bot_id}")
    equity = float(TradingClient(key, secret, paper=True).get_account().equity or 0)
    if equity <= 0:
        raise RuntimeError(f"broker returned no equity for {bot_id}")
    return equity


def _ny_now() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def run_monthly_skim(*, now: datetime | None = None) -> dict[str, Any]:
    """Daily, before the open. Records each account's vault value and trading
    equity; on the first run of a month, skims 10% of the new high-water gain.
    One ledger row per account per month (also when nothing moves)."""
    if not vault_enabled():
        return {"status": "blocked", "reason": "inactive", "bots": []}
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"status": "blocked", "reason": "database_unavailable", "bots": []}
    ensure_schema()
    now = now or _ny_now()
    today, month = now.date(), now.strftime("%Y-%m")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.bot_id, a.cash_usd, a.cumulative_contributions, m.high_water_mark, m.mark_month,
                       COALESCE(SUM(h.qty) FILTER (WHERE h.symbol = 'BIL'), 0),
                       COALESCE(SUM(h.qty) FILTER (WHERE h.symbol = 'VOO'), 0)
                FROM per_bot_vault_accounts a
                LEFT JOIN per_bot_vault_marks m ON m.bot_id = a.bot_id
                LEFT JOIN per_bot_vault_holdings h ON h.bot_id = a.bot_id
                WHERE a.activation_enabled = TRUE
                GROUP BY a.bot_id, a.cash_usd, a.cumulative_contributions, m.high_water_mark, m.mark_month
                ORDER BY a.bot_id
                """
            )
            rows = cur.fetchall()
            cur.execute("SELECT bot_id, month FROM per_bot_vault_skims WHERE month = %s", (month,))
            skimmed = {r[0] for r in cur.fetchall()}
    out: list[dict[str, Any]] = []
    for bot_id, cash, contributed, mark, mark_month, bil_qty, voo_qty in rows:
        try:
            held = {s: float(q) for s, q in ((VAULT_BIL_SYMBOL, bil_qty), (VAULT_VOO_SYMBOL, voo_qty)) if float(q) > 0}
            prices = _latest_vault_prices(bot_id, set(held))
            vault_value = round(float(cash or 0) + sum(q * prices[s] for s, q in held.items()), 2)
            equity = _broker_equity(bot_id)
            trading = round(equity - vault_value, 2)
            if trading <= 0:
                raise RuntimeError(f"trading equity {trading} not positive (equity {equity}, vault {vault_value})")
            plan = plan_skim(month=month, trading_equity=trading,
                             mark=None if mark is None else float(mark), mark_month=mark_month,
                             skimmed_months={month} if bot_id in skimmed else set())
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO per_bot_vault_value_history
                            (bot_id, trading_capital, cumulative_contributions, vault_value, combined_total)
                        VALUES (%s, %s, %s, %s, %s)
                        """, (bot_id, trading, float(contributed or 0), vault_value, equity))
                    if plan["action"] == "seed":
                        cur.execute(
                            "INSERT INTO per_bot_vault_marks (bot_id, high_water_mark, mark_month) VALUES (%s, %s, %s) "
                            "ON CONFLICT (bot_id) DO NOTHING", (bot_id, plan["mark_after"], month))
                    elif plan["action"] in ("skim", "below_mark"):
                        cur.execute(
                            """
                            INSERT INTO per_bot_vault_skims
                                (bot_id, month, as_of, broker_equity, vault_value, trading_equity,
                                 mark_before, mark_after, amount)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (bot_id, month) DO NOTHING
                            RETURNING id
                            """, (bot_id, month, today, equity, vault_value, trading,
                                  plan["mark_before"], plan["mark_after"], plan["amount"]))
                        if cur.fetchone() is None:
                            out.append({"bot_id": bot_id, "action": "none", "reason": "done_this_month"})
                            continue
                        cur.execute("UPDATE per_bot_vault_marks SET high_water_mark = %s, mark_month = %s, "
                                    "updated_at = NOW() WHERE bot_id = %s", (plan["mark_after"], month, bot_id))
                        if plan["amount"] > 0:
                            amount = plan["amount"]
                            cur.execute(
                                """
                                INSERT INTO per_bot_vault_contributions
                                    (bot_id, source_trade_id, realized_profit, skim_amount,
                                     bil_allocated, voo_allocated, cash_accrued)
                                VALUES (%s, %s, %s, %s, %s, 0, %s)
                                ON CONFLICT (bot_id, source_trade_id) DO NOTHING
                                """, (bot_id, f"hwm-{month}", round(trading - plan["mark_before"], 2),
                                      amount, amount, amount))
                            cur.execute(
                                """
                                UPDATE per_bot_vault_accounts
                                SET cash_usd = cash_usd + %s,
                                    cumulative_contributions = cumulative_contributions + %s,
                                    trading_capital = %s, updated_at = NOW()
                                WHERE bot_id = %s
                                """, (amount, amount, plan["mark_after"], bot_id))
                            cur.execute(
                                """
                                INSERT INTO per_bot_vault_deployment_queue (bot_id, pending_cash_usd)
                                VALUES (%s, %s)
                                ON CONFLICT (bot_id) DO UPDATE
                                SET pending_cash_usd = per_bot_vault_deployment_queue.pending_cash_usd + EXCLUDED.pending_cash_usd,
                                    status = CASE WHEN per_bot_vault_deployment_queue.bil_order_id IS NOT NULL
                                                  THEN 'submitted' ELSE 'pending' END,
                                    updated_at = NOW()
                                """, (bot_id, amount))
            if plan["action"] == "skim":
                logger.info(f"PerBotVault | {bot_id} {month}: skimmed ${plan['amount']:.2f} "
                            f"(trading ${trading:,.2f} over mark ${plan['mark_before']:,.2f})")
            out.append({"bot_id": bot_id, "trading_equity": trading, "vault_value": vault_value, **plan})
        except Exception as exc:
            logger.error(f"PerBotVault | monthly skim failed for {bot_id}: {exc}")
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(component="per_bot_vault", severity="warning", error_type="monthly_skim",
                                   message=f"Vault skim/mark read failed: {type(exc).__name__}", bot_id=bot_id)
            except Exception:
                pass
            out.append({"bot_id": bot_id, "action": "error", "error": str(exc)})
    return {"status": "complete", "month": month, "bots": out}


def summary_view(*, today: date, accounts: list[dict[str, Any]], history: dict[str, list[dict[str, Any]]],
                 contributions: dict[str, list[dict[str, Any]]], bil_symbol: str = VAULT_BIL_SYMBOL) -> dict[str, Any]:
    """Pure: the dashboard's vault card from DB rows (no broker calls).

    accounts: bot_id, seed_amount, cumulative_contributions, mark, mark_month,
      bil_qty, voo_qty. history (oldest first): recorded_at (date),
      trading_capital, vault_value, combined_total. contributions: created_at
      (date), skim_amount."""
    from datetime import timedelta
    bots = []
    for a in accounts:
        rows = history.get(a["bot_id"], [])
        last = rows[-1] if rows else None
        value = float(last["vault_value"]) if last else None
        principal = float(a["seed_amount"] or 0) + float(a["cumulative_contributions"] or 0)
        contrib = contributions.get(a["bot_id"], [])
        month_start = today.replace(day=1)
        this_month = [r for r in rows if r["recorded_at"] >= month_start]
        added_month = sum(float(c["skim_amount"]) for c in contrib if c["created_at"] >= month_start)
        income_month = (round(value - float(this_month[0]["vault_value"]) - added_month, 2)
                        if value is not None and this_month else None)
        window = [r for r in rows if r["recorded_at"] >= today - timedelta(days=30)]
        yield_30d = None
        if value is not None and len(window) >= 15 and float(window[0]["vault_value"]) > 0:
            days = max(1, (window[-1]["recorded_at"] - window[0]["recorded_at"]).days)
            added = sum(float(c["skim_amount"]) for c in contrib if c["created_at"] > window[0]["recorded_at"])
            yield_30d = round((value - float(window[0]["vault_value"]) - added)
                              / float(window[0]["vault_value"]) * 365 / days, 4)
        trading = float(last["trading_capital"]) if last else None
        mark = None if a.get("mark") is None else float(a["mark"])
        bots.append({
            "bot_id": a["bot_id"],
            "value": value,
            "as_of": last["recorded_at"].isoformat() if last else None,
            "bil_qty": float(a["bil_qty"] or 0),
            "voo_qty": float(a["voo_qty"] or 0),
            "money_in": round(principal, 2),
            "income_lifetime": round(value - principal, 2) if value is not None else None,
            "income_month": income_month,
            "yield_30d_realized": yield_30d,
            "contributions_year": round(sum(float(c["skim_amount"]) for c in contrib
                                            if c["created_at"].year == today.year), 2),
            "contributions_lifetime": round(float(a["cumulative_contributions"] or 0), 2),
            "trading_equity": trading,
            "total_equity": float(last["combined_total"]) if last else None,
            "high_water_mark": mark,
            "from_mark": round(trading / mark - 1, 4) if trading is not None and mark else None,
        })
    vals = [b["value"] for b in bots if b["value"] is not None]
    return {
        "rule": f"{SKIM_RATE:.0%} of each month's new high on trading equity, into {bil_symbol}",
        "asset": bil_symbol,
        "next_skim": next_skim_day(today).isoformat(),
        "total": round(sum(vals), 2) if vals else None,
        "bots": bots,
    }


def get_vault_summary(today: date | None = None) -> dict[str, Any]:
    """Read the vault card's rows; every figure was written by run_monthly_skim."""
    from db.postgres import get_conn, is_pg_available
    if not is_pg_available():
        return {"enabled": vault_enabled(), "error": "database_unavailable", "bots": []}
    ensure_schema()
    today = today or _ny_now().date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.bot_id, a.seed_amount, a.cumulative_contributions,
                       m.high_water_mark AS mark, m.mark_month,
                       COALESCE(SUM(h.qty) FILTER (WHERE h.symbol = 'BIL'), 0) AS bil_qty,
                       COALESCE(SUM(h.qty) FILTER (WHERE h.symbol = 'VOO'), 0) AS voo_qty
                FROM per_bot_vault_accounts a
                LEFT JOIN per_bot_vault_marks m ON m.bot_id = a.bot_id
                LEFT JOIN per_bot_vault_holdings h ON h.bot_id = a.bot_id
                WHERE a.activation_enabled = TRUE
                GROUP BY a.bot_id, a.seed_amount, a.cumulative_contributions, m.high_water_mark, m.mark_month
                ORDER BY a.bot_id
                """
            )
            accounts = [_row_dict(cur, r) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT bot_id, (recorded_at AT TIME ZONE 'America/New_York')::date AS recorded_at,
                       trading_capital, vault_value, combined_total
                FROM per_bot_vault_value_history
                WHERE recorded_at >= NOW() - INTERVAL '40 days'
                ORDER BY recorded_at
                """
            )
            history: dict[str, list[dict[str, Any]]] = {}
            for r in cur.fetchall():
                row = _row_dict(cur, r)
                history.setdefault(row["bot_id"], []).append(row)
            cur.execute(
                """
                SELECT bot_id, (created_at AT TIME ZONE 'America/New_York')::date AS created_at, skim_amount
                FROM per_bot_vault_contributions
                ORDER BY created_at
                """
            )
            contributions: dict[str, list[dict[str, Any]]] = {}
            for r in cur.fetchall():
                row = _row_dict(cur, r)
                contributions.setdefault(row["bot_id"], []).append(row)
            cur.execute("SELECT bot_id, month, as_of, trading_equity, mark_before, mark_after, amount "
                        "FROM per_bot_vault_skims ORDER BY as_of DESC LIMIT 36")
            ledger = [_row_dict(cur, r) for r in cur.fetchall()]
    out = summary_view(today=today, accounts=accounts, history=history, contributions=contributions)
    out["enabled"] = vault_enabled()
    out["ledger"] = [{k: (v.isoformat() if hasattr(v, "isoformat") else float(v) if k not in ("bot_id", "month") else v)
                      for k, v in r.items()} for r in ledger]
    return out


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
        "rule": "VAULT-V2: 10% of each month's new high-water gain on trading equity, into BIL",
        "example": example,
        "below_mark": {"trading_equity": 99_000.0, "mark": 100_000.0, "skim": hwm_skim(99_000.0, 100_000.0)[0]},
        "trading_return_example": trading_return_pct(108.0, 100.0),
        "deployment_when_inactive": deployment_plan(10.0, market_open=True),
        "seed_preview": seed_preview(),
        "enabled": vault_enabled(),
    }