"""
High-Yield Growth Vault — Profit Sweep  (v2 — PostgreSQL + DA-HWM)
--------------------------------------------------------------------
Automatically sweeps 20 % of new realised profits into JEPQ to generate
compounding dividend income.

Mathematics (Distribution-Adjusted HWM)
----------------------------------------
  HWM          = High Water Mark (permanent floor, updated on every sweep)
  DA_Equity    = current_equity − max(0, jepq_unrealized_pl)
                 (strips JEPQ's own dividend / appreciation from the
                  trigger so a fat quarterly distribution doesn't look
                  like new trading alpha and fire a cascade sweep)
  Eligible     = max(0, DA_Equity − HWM)
  Sweep_Amount = Eligible × 0.20
  new_HWM      = DA_Equity − Sweep_Amount

  The `da_adjustment` column records the cumulative JEPQ unrealized P&L
  excluded from HWM comparisons for audit purposes.

First-run initialisation
------------------------
  HWM is set to current_equity on the very first run.  No sweep fires —
  we start compounding from this baseline.

Guard rails
-----------
  • JEPQ / vault shares are invisible to the allocation loop and are
    protected from liquidation by the executor.
  • Sweep_Amount < $1.00 → silently skipped (Alpaca minimum).
  • dry_run=True → all calculations run but no Alpaca order is placed.

Backend
-------
  Primary  : PostgreSQL (Replit managed DB, db/postgres.py)
  Fallback : SQLite at trade_journal.db
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator

from loguru import logger

# ── Constants ──────────────────────────────────────────────────────────────
VAULT_SYMBOL = "JEPQ"
SWEEP_RATE   = 0.20
MIN_SWEEP    = 1.0

SQLITE_DB_PATH = Path(__file__).parent.parent / "trade_journal.db"


# ── Backend helpers ────────────────────────────────────────────────────────

def _use_pg() -> bool:
    try:
        from db.postgres import is_pg_available
        return is_pg_available()
    except Exception:
        return False


@contextmanager
def _sqlite_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema bootstrap (SQLite fallback) ────────────────────────────────────

def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_ledger (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            hwm                REAL NOT NULL,
            total_vaulted_usd  REAL NOT NULL DEFAULT 0.0,
            total_sweeps       INTEGER NOT NULL DEFAULT 0,
            vault_symbol       TEXT NOT NULL DEFAULT 'JEPQ',
            last_sweep_date    TEXT,
            last_sweep_amount  REAL,
            da_adjustment      REAL NOT NULL DEFAULT 0.0
        )
    """)
    # migrate old rows missing da_adjustment
    try:
        conn.execute("ALTER TABLE vault_ledger ADD COLUMN da_adjustment REAL NOT NULL DEFAULT 0.0")
    except Exception:
        pass


def init_vault_db() -> None:
    if _use_pg():
        from db.postgres import ensure_schema
        ensure_schema()
        logger.debug("Vault | vault_ledger table ensured (PostgreSQL)")
    else:
        with _sqlite_conn() as conn:
            _ensure_sqlite_schema(conn)
        logger.debug("Vault | vault_ledger table ensured (SQLite)")


# ── State read / write ─────────────────────────────────────────────────────

def get_vault_state() -> dict | None:
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM vault_ledger WHERE id = 1")
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    else:
        with _sqlite_conn() as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute("SELECT * FROM vault_ledger WHERE id = 1").fetchone()
        return dict(row) if row else None


def _set_vault_state(
    hwm: float,
    total_vaulted_usd: float,
    total_sweeps: int,
    last_sweep_date: str | None,
    last_sweep_amount: float | None,
    da_adjustment: float = 0.0,
) -> None:
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vault_ledger
                        (id, hwm, total_vaulted_usd, total_sweeps, vault_symbol,
                         last_sweep_date, last_sweep_amount, da_adjustment)
                    VALUES (1, %s, %s, %s, 'JEPQ', %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        hwm               = EXCLUDED.hwm,
                        total_vaulted_usd = EXCLUDED.total_vaulted_usd,
                        total_sweeps      = EXCLUDED.total_sweeps,
                        last_sweep_date   = EXCLUDED.last_sweep_date,
                        last_sweep_amount = EXCLUDED.last_sweep_amount,
                        da_adjustment     = EXCLUDED.da_adjustment
                """, (hwm, total_vaulted_usd, total_sweeps,
                      last_sweep_date, last_sweep_amount, da_adjustment))
    else:
        with _sqlite_conn() as conn:
            _ensure_sqlite_schema(conn)
            conn.execute("""
                INSERT INTO vault_ledger
                    (id, hwm, total_vaulted_usd, total_sweeps, vault_symbol,
                     last_sweep_date, last_sweep_amount, da_adjustment)
                VALUES (1, ?, ?, ?, 'JEPQ', ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    hwm               = excluded.hwm,
                    total_vaulted_usd = excluded.total_vaulted_usd,
                    total_sweeps      = excluded.total_sweeps,
                    last_sweep_date   = excluded.last_sweep_date,
                    last_sweep_amount = excluded.last_sweep_amount,
                    da_adjustment     = excluded.da_adjustment
            """, (hwm, total_vaulted_usd, total_sweeps,
                  last_sweep_date, last_sweep_amount, da_adjustment))


# ── Fetch JEPQ unrealized P&L for DA-HWM ──────────────────────────────────

def _get_jepq_unrealized_pl() -> float:
    """
    Fetch the unrealized P&L of the JEPQ vault position from Alpaca.
    Returns 0.0 if the position doesn't exist or the call fails.
    This is subtracted from equity before the HWM comparison so that
    JEPQ's own distributions/appreciation don't cascade into new sweeps.
    """
    try:
        from execution.broker import get_positions
        positions = get_positions()
        for p in positions:
            if p["symbol"] == VAULT_SYMBOL:
                pl = p.get("unrealized_pl", 0.0)
                logger.debug(f"Vault | JEPQ unrealised P&L = ${pl:+,.2f} (DA-HWM adjustment)")
                return float(pl)
    except Exception as exc:
        logger.warning(f"Vault | Could not fetch JEPQ P&L for DA-HWM: {exc} — using 0.0")
    return 0.0


# ── Main sweep logic ───────────────────────────────────────────────────────

def run_profit_sweep(current_equity: float, dry_run: bool = False) -> dict:
    """
    Run the distribution-adjusted profit sweep.

    Returns a dict describing what happened (sweep fired or not, amounts,
    new HWM, etc.).  Never raises — failures are caught and returned.
    """
    from execution.broker import place_order

    try:
        state = get_vault_state()

        # ── First run: initialise HWM ──────────────────────────────────────
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
                da_adjustment=0.0,
            )
            return {
                "swept":           False,
                "reason":          "first_run_hwm_initialised",
                "hwm":             current_equity,
                "current_equity":  current_equity,
                "eligible_profit": 0.0,
            }

        hwm = float(state["hwm"])

        # ── Distribution-Adjusted Equity ───────────────────────────────────
        jepq_pl     = _get_jepq_unrealized_pl()
        da_equity   = current_equity - max(0.0, jepq_pl)
        cumulative_da = float(state.get("da_adjustment") or 0.0) + max(0.0, jepq_pl)

        eligible_profit = max(0.0, da_equity - hwm)

        if eligible_profit <= 0:
            logger.debug(
                f"Vault | No new profit above HWM "
                f"(DA_equity=${da_equity:,.2f} HWM=${hwm:,.2f} "
                f"JEPQ_adj=${jepq_pl:+,.2f})"
            )
            return {
                "swept":           False,
                "reason":          "no_new_profit",
                "hwm":             hwm,
                "current_equity":  current_equity,
                "da_equity":       da_equity,
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
            f"equity=${current_equity:,.2f} DA_equity=${da_equity:,.2f} "
            f"HWM=${hwm:,.2f} eligible=${eligible_profit:,.2f} "
            f"→ sweep=${sweep_amount:,.2f} → buying {VAULT_SYMBOL}"
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

        new_hwm           = da_equity - sweep_amount
        new_total_vaulted = float(state["total_vaulted_usd"]) + sweep_amount
        new_total_sweeps  = int(state["total_sweeps"]) + 1
        today             = date.today().isoformat()

        _set_vault_state(
            hwm=new_hwm,
            total_vaulted_usd=new_total_vaulted,
            total_sweeps=new_total_sweeps,
            last_sweep_date=today,
            last_sweep_amount=sweep_amount,
            da_adjustment=cumulative_da,
        )

        logger.info(
            f"Vault | HWM updated: ${hwm:,.2f} → ${new_hwm:,.2f} | "
            f"total vaulted: ${new_total_vaulted:,.2f} across {new_total_sweeps} sweeps"
        )

        return {
            "swept":             not dry_run,
            "dry_run":           dry_run,
            "vault_symbol":      VAULT_SYMBOL,
            "current_equity":    current_equity,
            "da_equity":         da_equity,
            "jepq_pl_excluded":  jepq_pl,
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
        return {"swept": False, "reason": f"internal_error: {exc}"}
