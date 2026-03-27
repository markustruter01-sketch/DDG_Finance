"""
High-Yield Growth Vault — Profit Sweep
----------------------------------------
Automatically sweeps 20 % of *new* realised profits into JEPQ to generate
compounding dividend income.

Mathematics
-----------
  HWM  = High Water Mark (permanent floor, updated on every sweep)
  Eligible_Profit = max(0, current_equity − HWM)
  Sweep_Amount    = Eligible_Profit × 0.20
  new_HWM         = current_equity − Sweep_Amount

First-run initialisation
------------------------
  If the vault_ledger table has no row, we query Alpaca for the live
  portfolio_value and set that as the founding HWM.  No sweep fires on the
  first run — we start compounding from this baseline.

Guard rails
-----------
  • The LLM is never told about JEPQ/SCHD — vault shares are invisible to
    the allocation loop and are protected from liquidation.
  • Sweep_Amount < $1.00 → silently skipped (Alpaca minimum).
  • dry_run=True → all calculations run but no Alpaca order is placed.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator

from loguru import logger

DB_PATH = Path(__file__).parent.parent / "trade_journal.db"

VAULT_SYMBOL = "JEPQ"
SWEEP_RATE   = 0.20       # 20 % of new profits
MIN_SWEEP    = 1.0        # Alpaca $1 minimum notional


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_vault_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vault_ledger (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                hwm                REAL    NOT NULL,
                total_vaulted_usd  REAL    NOT NULL DEFAULT 0.0,
                total_sweeps       INTEGER NOT NULL DEFAULT 0,
                vault_symbol       TEXT    NOT NULL DEFAULT 'JEPQ',
                last_sweep_date    TEXT,
                last_sweep_amount  REAL
            )
        """)
    logger.debug("Vault | vault_ledger table ensured")


def get_vault_state() -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM vault_ledger WHERE id = 1").fetchone()
    if row is None:
        return None
    return dict(row)


def _set_vault_state(
    hwm: float,
    total_vaulted_usd: float,
    total_sweeps: int,
    last_sweep_date: str | None,
    last_sweep_amount: float | None,
) -> None:
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO vault_ledger
                (id, hwm, total_vaulted_usd, total_sweeps, vault_symbol,
                 last_sweep_date, last_sweep_amount)
            VALUES (1, ?, ?, ?, 'JEPQ', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                hwm               = excluded.hwm,
                total_vaulted_usd = excluded.total_vaulted_usd,
                total_sweeps      = excluded.total_sweeps,
                last_sweep_date   = excluded.last_sweep_date,
                last_sweep_amount = excluded.last_sweep_amount
        """, (hwm, total_vaulted_usd, total_sweeps, last_sweep_date, last_sweep_amount))


def run_profit_sweep(current_equity: float, dry_run: bool = False) -> dict:
    """
    Run the profit sweep logic.

    Returns a dict describing what happened (sweep fired or not, amounts,
    new HWM, etc.).  Never raises — failures are caught and returned in the
    result dict.
    """
    from execution.broker import place_order

    try:
        state = get_vault_state()

        if state is None:
            logger.info(
                f"Vault | First run — initialising HWM to current equity "
                f"${current_equity:,.2f}"
            )
            _set_vault_state(
                hwm=current_equity,
                total_vaulted_usd=0.0,
                total_sweeps=0,
                last_sweep_date=None,
                last_sweep_amount=None,
            )
            return {
                "swept":          False,
                "reason":         "first_run_hwm_initialised",
                "hwm":            current_equity,
                "current_equity": current_equity,
                "eligible_profit": 0.0,
            }

        hwm = state["hwm"]
        eligible_profit = max(0.0, current_equity - hwm)

        if eligible_profit <= 0:
            logger.debug(
                f"Vault | No new profit above HWM "
                f"(equity=${current_equity:,.2f} HWM=${hwm:,.2f})"
            )
            return {
                "swept":           False,
                "reason":          "no_new_profit",
                "hwm":             hwm,
                "current_equity":  current_equity,
                "eligible_profit": eligible_profit,
            }

        sweep_amount = eligible_profit * SWEEP_RATE

        if sweep_amount < MIN_SWEEP:
            logger.info(
                f"Vault | Eligible=${eligible_profit:.2f} → "
                f"sweep=${sweep_amount:.2f} below ${MIN_SWEEP} min — skipped"
            )
            return {
                "swept":           False,
                "reason":          "sweep_below_minimum",
                "hwm":             hwm,
                "current_equity":  current_equity,
                "eligible_profit": eligible_profit,
                "sweep_amount":    sweep_amount,
            }

        logger.info(
            f"Vault | 💰 Profit sweep firing! "
            f"equity=${current_equity:,.2f} HWM=${hwm:,.2f} "
            f"eligible=${eligible_profit:,.2f} → "
            f"sweep=${sweep_amount:,.2f} → buying {VAULT_SYMBOL}"
        )

        order_info: dict | None = None
        if not dry_run:
            try:
                order_info = place_order(
                    ticker=VAULT_SYMBOL,
                    notional_usd=sweep_amount,
                    side="buy",
                )
                logger.info(
                    f"Vault | {VAULT_SYMBOL} order placed: "
                    f"id={order_info['id']} status={order_info['status']}"
                )
            except Exception as exc:
                logger.error(f"Vault | Failed to buy {VAULT_SYMBOL}: {exc}")
                return {
                    "swept":           False,
                    "reason":          f"order_failed: {exc}",
                    "hwm":             hwm,
                    "current_equity":  current_equity,
                    "eligible_profit": eligible_profit,
                    "sweep_amount":    sweep_amount,
                }

        new_hwm = current_equity - sweep_amount
        new_total_vaulted = state["total_vaulted_usd"] + sweep_amount
        new_total_sweeps  = state["total_sweeps"] + 1
        today = date.today().isoformat()

        _set_vault_state(
            hwm=new_hwm,
            total_vaulted_usd=new_total_vaulted,
            total_sweeps=new_total_sweeps,
            last_sweep_date=today,
            last_sweep_amount=sweep_amount,
        )

        logger.info(
            f"Vault | HWM updated: ${hwm:,.2f} → ${new_hwm:,.2f} | "
            f"total vaulted: ${new_total_vaulted:,.2f} across "
            f"{new_total_sweeps} sweeps"
        )

        return {
            "swept":             not dry_run,
            "dry_run":           dry_run,
            "vault_symbol":      VAULT_SYMBOL,
            "current_equity":    current_equity,
            "eligible_profit":   eligible_profit,
            "sweep_amount":      sweep_amount,
            "previous_hwm":      hwm,
            "new_hwm":           new_hwm,
            "total_vaulted_usd": new_total_vaulted,
            "total_sweeps":      new_total_sweeps,
            "order":             order_info,
        }

    except Exception as exc:
        logger.error(f"Vault | Unexpected error in run_profit_sweep: {exc}")
        return {
            "swept":  False,
            "reason": f"internal_error: {exc}",
        }
