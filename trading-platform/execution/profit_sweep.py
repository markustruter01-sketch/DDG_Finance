"""
High-Yield Growth Vault — Profit Sweep  (v3 — self-contained PostgreSQL)
------------------------------------------------------------------------
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
  Primary  : PostgreSQL (uses DATABASE_URL env var directly via psycopg2 —
             no dependency on db.postgres import paths so this module works
             correctly from any process, including kraken-bot)
  Fallback : SQLite at trade_journal.db

Migration
---------
  On first call to init_vault_db() when PostgreSQL is available, any
  existing SQLite vault_ledger accumulation is merged into PostgreSQL
  (total_vaulted_usd and total_sweeps are summed) and the SQLite row is
  zeroed so future writes never go there again.
"""

from __future__ import annotations

import os
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

# Track whether we have already attempted the one-time SQLite→PG migration
# so we do not repeat it every call within the same process.
_MIGRATION_DONE: bool = False


# ── Backend helpers ────────────────────────────────────────────────────────

def _use_pg() -> bool:
    """Return True when psycopg2 is importable AND a DSN is available.

    This check is entirely self-contained — it does NOT import anything from
    db.postgres, which would fail in the kraken-bot process because
    kraken-bot/db.py (a flat file) shadows the trading-platform/db/ package.
    """
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        return False
    return bool(
        os.environ.get("DATABASE_URL") or os.environ.get("PGHOST")
    )


def _build_dsn() -> str:
    """Construct a psycopg2 DSN from environment variables."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    return (
        f"postgresql://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ.get('PGPORT', 5432)}"
        f"/{os.environ['PGDATABASE']}"
    )


@contextmanager
def _pg_conn() -> Generator:
    """Self-contained psycopg2 connection — no dependency on db.postgres."""
    import psycopg2
    conn = psycopg2.connect(_build_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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


# ── Schema bootstrap ────────────────────────────────────────────────────────

_PG_VAULT_DDL = """
CREATE TABLE IF NOT EXISTS vault_ledger (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    hwm                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_vaulted_usd     DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_sweeps          INTEGER NOT NULL DEFAULT 0,
    vault_symbol          TEXT NOT NULL DEFAULT 'JEPQ',
    last_sweep_date       DATE,
    last_sweep_amount     DOUBLE PRECISION,
    da_adjustment         DOUBLE PRECISION NOT NULL DEFAULT 0
)
"""


def _ensure_pg_schema() -> None:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_PG_VAULT_DDL)


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_ledger (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            hwm                REAL NOT NULL DEFAULT 0.0,
            total_vaulted_usd  REAL NOT NULL DEFAULT 0.0,
            total_sweeps       INTEGER NOT NULL DEFAULT 0,
            vault_symbol       TEXT NOT NULL DEFAULT 'JEPQ',
            last_sweep_date    TEXT,
            last_sweep_amount  REAL,
            da_adjustment      REAL NOT NULL DEFAULT 0.0
        )
    """)
    try:
        conn.execute(
            "ALTER TABLE vault_ledger ADD COLUMN da_adjustment REAL NOT NULL DEFAULT 0.0"
        )
    except Exception:
        pass


# ── One-time SQLite → PostgreSQL migration ─────────────────────────────────

_VAULT_MIGRATION_LOCK_ID = 7_429_384_756  # arbitrary stable advisory-lock key

_PG_VAULT_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS vault_migrations (
    key         TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
_VAULT_SQLITE_MIGRATION_KEY = "sqlite_to_pg_v1"


def _migrate_sqlite_to_pg() -> None:
    """
    Merge any existing SQLite vault_ledger accumulation into PostgreSQL once.

    Fully idempotent and cross-process safe:

    1. In-process guard (_MIGRATION_DONE) short-circuits hot-reload re-runs.
    2. PostgreSQL advisory lock (pg_try_advisory_lock) ensures only one
       concurrent process proceeds when multiple bots start simultaneously.
    3. Durable PG marker (vault_migrations table) persists across restarts:
       if a process crashes after committing the vault_ledger merge but before
       zeroing SQLite, the next restart finds the marker and skips — preventing
       double-counting even in crash-recovery scenarios.

    Protocol:
      a. Lock → b. Check durable marker → c. Read SQLite → d. Merge PG +
      write marker (single commit) → e. Zero SQLite (best-effort) → f. Unlock
    """
    global _MIGRATION_DONE
    if _MIGRATION_DONE:
        return
    _MIGRATION_DONE = True

    if not SQLITE_DB_PATH.exists():
        return

    conn = None
    try:
        import psycopg2

        conn = psycopg2.connect(_build_dsn())
        conn.autocommit = False

        # Ensure the migrations marker table exists.
        with conn.cursor() as cur:
            cur.execute(_PG_VAULT_MIGRATIONS_DDL)
        conn.commit()

        # Acquire advisory lock — only one process proceeds.
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_VAULT_MIGRATION_LOCK_ID,))
            acquired = cur.fetchone()[0]

        if not acquired:
            logger.debug(
                "Vault | SQLite→PG migration lock held by another process — skipped"
            )
            conn.close()
            return

        # Check durable marker — skip if already applied (crash-safe).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM vault_migrations WHERE key = %s",
                (_VAULT_SQLITE_MIGRATION_KEY,),
            )
            already_done = cur.fetchone() is not None

        if already_done:
            logger.debug("Vault | SQLite→PG migration already applied (durable marker) — skipped")
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_MIGRATION_LOCK_ID,))
            conn.commit()
            conn.close()
            return

        # We hold the lock and the marker is absent — read SQLite.
        try:
            with _sqlite_conn() as sc:
                _ensure_sqlite_schema(sc)
                row = sc.execute(
                    "SELECT total_vaulted_usd, total_sweeps FROM vault_ledger WHERE id = 1"
                ).fetchone()
        except Exception as exc:
            logger.warning(f"Vault | Could not read SQLite for migration: {exc}")
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_MIGRATION_LOCK_ID,))
            conn.commit()
            conn.close()
            return

        if row is None or float(row["total_vaulted_usd"] or 0) <= 0:
            # Nothing to migrate — write marker anyway so this path is fast on future restarts.
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO vault_migrations (key) VALUES (%s) ON CONFLICT DO NOTHING",
                    (_VAULT_SQLITE_MIGRATION_KEY,),
                )
                cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_MIGRATION_LOCK_ID,))
            conn.commit()
            conn.close()
            return

        sqlite_vaulted = float(row["total_vaulted_usd"])
        sqlite_sweeps  = int(row["total_sweeps"] or 0)

        logger.info(
            f"Vault | Migrating SQLite→PG: ${sqlite_vaulted:.2f} across "
            f"{sqlite_sweeps} sweeps"
        )

        # Merge vault_ledger + write durable marker in one atomic commit.
        with conn.cursor() as cur:
            cur.execute(_PG_VAULT_DDL)
            cur.execute("""
                INSERT INTO vault_ledger
                    (id, hwm, total_vaulted_usd, total_sweeps, vault_symbol,
                     last_sweep_date, last_sweep_amount, da_adjustment)
                VALUES (1, 0, %s, %s, 'JEPQ', NULL, NULL, 0)
                ON CONFLICT (id) DO UPDATE SET
                    total_vaulted_usd = vault_ledger.total_vaulted_usd + EXCLUDED.total_vaulted_usd,
                    total_sweeps      = vault_ledger.total_sweeps      + EXCLUDED.total_sweeps
            """, (sqlite_vaulted, sqlite_sweeps))
            cur.execute(
                "INSERT INTO vault_migrations (key) VALUES (%s) ON CONFLICT DO NOTHING",
                (_VAULT_SQLITE_MIGRATION_KEY,),
            )
        conn.commit()

        # Zero SQLite — best effort.  Even if this fails, the PG marker prevents re-run.
        try:
            with _sqlite_conn() as sc:
                sc.execute(
                    "UPDATE vault_ledger SET total_vaulted_usd = 0.0, total_sweeps = 0 WHERE id = 1"
                )
        except Exception as exc:
            logger.warning(
                f"Vault | Could not zero SQLite row (non-fatal, PG marker prevents re-run): {exc}"
            )

        logger.info(
            f"Vault | Migration complete — ${sqlite_vaulted:.2f} merged into "
            f"PostgreSQL; SQLite row zeroed."
        )

    except Exception as exc:
        logger.warning(f"Vault | SQLite→PG migration failed (non-fatal): {exc}")
    finally:
        if conn is not None and not conn.closed:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_MIGRATION_LOCK_ID,))
                conn.commit()
            except Exception:
                pass
            conn.close()


# ── One-time trade-history backfill ────────────────────────────────────────

_VAULT_BACKFILL_LOCK_ID  = 7_429_384_757  # distinct from SQLite migration lock
_VAULT_BACKFILL_KEY      = "kraken_forex_backfill_v1"


def _backfill_from_trade_history() -> None:
    """
    One-time startup backfill: add missing 20% vault contributions from all
    profitable Kraken and Forex trades recorded in the database.

    Why this is needed
    ------------------
    Before Task #64 fixed profit_sweep._use_pg(), every Kraken/Forex per-trade
    vault contribution was silently routed to SQLite instead of PostgreSQL.
    The SQLite data in the *development* container was migrated by
    _migrate_sqlite_to_pg(), but the *production* container's SQLite file
    starts fresh on every deployment, so production vault_ledger only ever
    accumulated the 4 Alpaca HWM sweeps that ran correctly from the beginning.

    This function computes:
        expected = SUM(kraken_trades.pnl_usd * 0.20 WHERE pnl_usd > 0)
                 + SUM(forex_trades.pnl_usd  * 0.20 WHERE pnl_usd > 0)
    and adds that full amount to vault_ledger in one atomic commit.  It then
    writes the marker so it never fires again.

    Safety
    ------
    • Advisory lock (distinct ID from SQLite migration) — one winner per restart burst.
    • Durable PG marker — idempotent across restarts / crash-recovery.
    • Non-fatal — all errors are caught and logged; startup continues normally.
    """
    conn = None
    try:
        import psycopg2

        conn = psycopg2.connect(_build_dsn())
        conn.autocommit = False

        # Ensure migrations table exists (may have been created by _migrate_sqlite_to_pg,
        # but _backfill can also be the first to run if SQLite migration was a no-op).
        with conn.cursor() as cur:
            cur.execute(_PG_VAULT_MIGRATIONS_DDL)
        conn.commit()

        # Try to acquire advisory lock.
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_VAULT_BACKFILL_LOCK_ID,))
            acquired = cur.fetchone()[0]

        if not acquired:
            logger.debug("Vault | Trade backfill lock held by another process — skipped")
            conn.close()
            return

        # Check durable marker — skip if already applied.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM vault_migrations WHERE key = %s",
                (_VAULT_BACKFILL_KEY,),
            )
            already_done = cur.fetchone() is not None

        if already_done:
            logger.debug("Vault | Trade backfill already applied (durable marker) — skipped")
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_BACKFILL_LOCK_ID,))
            conn.commit()
            conn.close()
            return

        # Compute expected contributions from trade tables.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(pnl_usd * 0.20), 0.0) "
                "FROM kraken_trades WHERE pnl_usd > 0"
            )
            k_count, k_amount = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(pnl_usd * 0.20), 0.0) "
                "FROM forex_trades WHERE pnl_usd > 0"
            )
            f_count, f_amount = cur.fetchone()

        total_wins   = int(k_count or 0) + int(f_count or 0)
        total_amount = float(k_amount or 0) + float(f_amount or 0)

        if total_amount <= 0:
            # Nothing to backfill — write marker so we skip cleanly on future startups.
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO vault_migrations (key) VALUES (%s) ON CONFLICT DO NOTHING",
                    (_VAULT_BACKFILL_KEY,),
                )
                cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_BACKFILL_LOCK_ID,))
            conn.commit()
            conn.close()
            return

        logger.info(
            f"Vault | Trade backfill: Kraken {k_count} wins ${float(k_amount):.2f} + "
            f"Forex {f_count} wins ${float(f_amount):.2f} "
            f"→ adding ${total_amount:.2f} to Growth Vault"
        )

        # Add backfill amount + write marker in one atomic commit.
        with conn.cursor() as cur:
            cur.execute(_PG_VAULT_DDL)
            cur.execute("""
                INSERT INTO vault_ledger
                    (id, hwm, total_vaulted_usd, total_sweeps, vault_symbol,
                     last_sweep_date, last_sweep_amount, da_adjustment)
                VALUES (1, 0, %s, %s, 'JEPQ', CURRENT_DATE, %s, 0)
                ON CONFLICT (id) DO UPDATE SET
                    total_vaulted_usd = vault_ledger.total_vaulted_usd + EXCLUDED.total_vaulted_usd,
                    total_sweeps      = vault_ledger.total_sweeps      + EXCLUDED.total_sweeps,
                    last_sweep_date   = EXCLUDED.last_sweep_date,
                    last_sweep_amount = EXCLUDED.last_sweep_amount
            """, (total_amount, total_wins, total_amount))
            cur.execute(
                "INSERT INTO vault_migrations (key) VALUES (%s) ON CONFLICT DO NOTHING",
                (_VAULT_BACKFILL_KEY,),
            )
        conn.commit()

        logger.info(
            f"Vault | Trade backfill complete — ${total_amount:.2f} added "
            f"({total_wins} historical wins). Growth Vault now reflects full history."
        )

    except Exception as exc:
        logger.warning(f"Vault | Trade backfill failed (non-fatal): {exc}")
    finally:
        if conn is not None and not conn.closed:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (_VAULT_BACKFILL_LOCK_ID,))
                conn.commit()
            except Exception:
                pass
            conn.close()


# ── Schema + migration entry point ─────────────────────────────────────────

def init_vault_db() -> None:
    if _use_pg():
        _ensure_pg_schema()
        logger.debug("Vault | vault_ledger table ensured (PostgreSQL)")
        _migrate_sqlite_to_pg()
        _backfill_from_trade_history()
    else:
        with _sqlite_conn() as conn:
            _ensure_sqlite_schema(conn)
        logger.debug("Vault | vault_ledger table ensured (SQLite)")


# ── State read / write ─────────────────────────────────────────────────────

def get_vault_state() -> dict | None:
    if _use_pg():
        with _pg_conn() as conn:
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
        with _pg_conn() as conn:
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

        if not dry_run:
            try:
                from notifications.discord import notify_profit_sweep
                notify_profit_sweep(sweep_amount, VAULT_SYMBOL, new_hwm)
            except Exception:
                pass

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


def record_kraken_vault_contribution(pnl_usd: float, sweep_rate: float = 0.20, source: str = "kraken_paper") -> dict:
    """
    Record a per-trade vault contribution (atomic — race-condition safe).

    Called after each profitable paper trade closes.  sweep_rate % of
    each winning trade's gross PnL is earmarked for the Growth Vault (JEPQ).

    The `source` parameter identifies which bot produced the profit
    (e.g. "kraken_paper", "options_paper", "forex_paper").

    No minimum threshold — every profitable trade, no matter how small,
    has 20% recorded in the ledger.  This is pure bookkeeping; no real
    Alpaca order is placed here, so the $1 Alpaca floor does not apply.

    Uses an atomic SQL increment (+=) instead of read-modify-write to prevent
    lost updates when multiple Kraken bots close trades simultaneously.

    Returns a dict with swept=True/False and the contributed amount.
    """
    if pnl_usd <= 0:
        return {"swept": False, "reason": "no_profit"}

    amount = round(pnl_usd * sweep_rate, 4)
    today = str(date.today())

    try:
        init_vault_db()

        if _use_pg():
            with _pg_conn() as conn:
                with conn.cursor() as cur:
                    # Upsert with atomic += to prevent race conditions across bots
                    cur.execute("""
                        INSERT INTO vault_ledger
                            (id, hwm, total_vaulted_usd, total_sweeps, vault_symbol,
                             last_sweep_date, last_sweep_amount, da_adjustment)
                        VALUES (1, 0.0, %s, 1, 'JEPQ', %s, %s, 0.0)
                        ON CONFLICT (id) DO UPDATE SET
                            total_vaulted_usd = vault_ledger.total_vaulted_usd + EXCLUDED.total_vaulted_usd,
                            total_sweeps      = vault_ledger.total_sweeps + 1,
                            last_sweep_date   = EXCLUDED.last_sweep_date,
                            last_sweep_amount = EXCLUDED.last_sweep_amount
                    """, (amount, today, amount))
        else:
            # SQLite is single-writer — original approach is safe
            state = get_vault_state()
            if state is None:
                _set_vault_state(
                    hwm=0.0,
                    total_vaulted_usd=amount,
                    total_sweeps=1,
                    last_sweep_date=today,
                    last_sweep_amount=amount,
                )
            else:
                _set_vault_state(
                    hwm=float(state["hwm"]),
                    total_vaulted_usd=float(state["total_vaulted_usd"]) + amount,
                    total_sweeps=int(state["total_sweeps"]) + 1,
                    last_sweep_date=today,
                    last_sweep_amount=amount,
                    da_adjustment=float(state.get("da_adjustment", 0.0)),
                )

        logger.info(
            f"Vault | {source} contribution: ${amount:.2f} "
            f"({sweep_rate*100:.0f}% of ${pnl_usd:.2f} profit) → Growth Vault"
        )
        return {"swept": True, "amount": amount, "source": source}

    except Exception as exc:
        logger.error(f"Vault | {source} contribution failed: {exc}")
        return {"swept": False, "reason": f"error: {exc}"}
