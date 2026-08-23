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
SGOV_SYMBOL = "SGOV"
QQQ_SYMBOL = "QQQ"
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
    """Split a contribution equally between SGOV and QQQ."""
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
    sgov, qqq = split_contribution(vault_value)
    return {"action": "planned", "sgov_notional": sgov, "qqq_notional": qqq}


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
    sgov, qqq = split_contribution(skim)
    return {
        "starting_trading_capital": starting,
        "profit": profit,
        "skim": skim,
        "sgov_allocated": sgov,
        "qqq_allocated": qqq,
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
        sgov_qty NUMERIC NOT NULL DEFAULT 0,
        qqq_qty NUMERIC NOT NULL DEFAULT 0,
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
        sgov_allocated NUMERIC NOT NULL DEFAULT 0,
        qqq_allocated NUMERIC NOT NULL DEFAULT 0,
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
        pending_sgov_usd    NUMERIC NOT NULL DEFAULT 0,
        pending_qqq_usd     NUMERIC NOT NULL DEFAULT 0,
        sgov_order_id       TEXT,
        qqq_order_id        TEXT,
        status              TEXT NOT NULL DEFAULT 'pending',
        attempts            INTEGER NOT NULL DEFAULT 0,
        last_error          TEXT,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS per_bot_vault_holdings (
        bot_id              TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
        symbol              TEXT NOT NULL CHECK (symbol IN ('SGOV', 'QQQ')),
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
        return {
            "activated": False,
            "dry_run": True,
            "enabled": vault_enabled(),
            "bots": activation_plan({p["bot_id"]: p["equity"] or 0 for p in previews}),
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
                    [(bot_id, SGOV_SYMBOL), (bot_id, QQQ_SYMBOL)],
                )
                result.append({"bot_id": bot_id, "action": "activated", "seed": seed})
    return {"activated": True, "dry_run": False, "bots": result}


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
    sgov, qqq = split_contribution(skim)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO per_bot_vault_accounts (bot_id)
                    VALUES (%s)
                    ON CONFLICT (bot_id) DO NOTHING
                    """,
                    (bot_id,),
                )
                cur.execute(
                    """
                    INSERT INTO per_bot_vault_contributions
                        (bot_id, source_trade_id, realized_profit, skim_amount,
                         sgov_allocated, qqq_allocated, cash_accrued)
                    VALUES (%s, %s, %s, %s, %s, %s, 0)
                    ON CONFLICT (bot_id, source_trade_id) DO NOTHING
                    RETURNING id
                    """,
                    (bot_id, source_trade_id, realized_profit, skim, sgov, qqq),
                )
                inserted = cur.fetchone()
                if not inserted:
                    return {"recorded": False, "reason": "duplicate", "skim_amount": skim}
                cur.execute(
                    """
                    UPDATE per_bot_vault_accounts
                    SET cash_usd = cash_usd + %s,
                        cumulative_contributions = cumulative_contributions + %s,
                        updated_at = NOW()
                    WHERE bot_id = %s AND activation_enabled = TRUE
                    """,
                    (skim, skim, bot_id),
                )
        return {
            "recorded": True,
            "bot_id": bot_id,
            "source_trade_id": source_trade_id,
            "realized_profit": round(float(realized_profit), 2),
            "skim_amount": skim,
            "sgov_allocated": sgov,
            "qqq_allocated": qqq,
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
                       a.seed_amount, a.sgov_qty, a.qqq_qty, a.cash_usd,
                       a.cumulative_contributions, a.last_rebalance_date,
                       p.equity_usd AS trading_capital
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
            "sgov_qty": float(row["sgov_qty"] or 0),
            "qqq_qty": float(row["qqq_qty"] or 0),
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