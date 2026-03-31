"""
db.py — PostgreSQL access layer for Davy Jones' Portfolio (kraken-bot).

The bot process runs independently from the FastAPI server; this module
provides all DB I/O the bot needs: heartbeat upserts, portfolio load/save,
and trade inserts.  It also handles the one-time bootstrap migration that
seeds the DB tables from legacy JSON files on first startup.

All public functions degrade gracefully if PostgreSQL is unavailable —
the caller should always handle a None / empty return value.

Tables owned here (created idempotently on first call to ensure_schema()):
  kraken_heartbeat  — single-row (id=1) heartbeat upserted every cycle
  kraken_portfolio  — single-row (id=1) portfolio state (cash + positions)
  kraken_trades     — append-only trade history

kraken_adaptive_params is managed by adaptive_params.py and is NOT touched
here to avoid any cross-module schema conflicts.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from loguru import logger

try:
    import psycopg2
    import psycopg2.extras
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False
    logger.warning("DB | psycopg2 not installed — Kraken bot DB unavailable")


# ── Schema ─────────────────────────────────────────────────────────────────────

_KRAKEN_SCHEMA = """
-- Single-row heartbeat updated every bot cycle (id always = 1)
CREATE TABLE IF NOT EXISTS kraken_heartbeat (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    status          TEXT    NOT NULL DEFAULT 'not_started',
    cycle_count     INTEGER NOT NULL DEFAULT 0,
    equity_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    position_count  INTEGER NOT NULL DEFAULT 0,
    paper_trading   BOOLEAN NOT NULL DEFAULT TRUE,
    bot_paused      BOOLEAN NOT NULL DEFAULT FALSE,
    circuit_breaker JSONB,
    error           TEXT,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Single-row portfolio state (id always = 1)
CREATE TABLE IF NOT EXISTS kraken_portfolio (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    starting_balance_usd DOUBLE PRECISION NOT NULL DEFAULT 100000,
    cash_usd             DOUBLE PRECISION NOT NULL DEFAULT 100000,
    positions            JSONB NOT NULL DEFAULT '{}'
);

-- Append-only trade history
CREATE TABLE IF NOT EXISTS kraken_trades (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT             NOT NULL,
    side        TEXT             NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price  DOUBLE PRECISION NOT NULL,
    pnl_pct     DOUBLE PRECISION NOT NULL,
    pnl_usd     DOUBLE PRECISION NOT NULL,
    fees_usd    DOUBLE PRECISION,
    reason      TEXT,
    closed_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    paper       BOOLEAN          NOT NULL DEFAULT TRUE,
    order_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_kraken_trades_closed_at ON kraken_trades (closed_at DESC);

-- Single-row adaptive params (id=1) upserted by adaptive_params.py every adaptation cycle.
CREATE TABLE IF NOT EXISTS kraken_adaptive_params (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    params      JSONB NOT NULL DEFAULT '{}',
    metrics     JSONB,
    reasons     JSONB,
    adapted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lookback_n  INTEGER NOT NULL DEFAULT 0
);
"""


# ── Connection helper ──────────────────────────────────────────────────────────

def _get_dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


def _is_available() -> bool:
    return _PG_AVAILABLE and bool(_get_dsn())


@contextmanager
def _conn() -> "Generator[psycopg2.extensions.connection, None, None]":
    """Open a psycopg2 connection; commit on success, rollback on failure."""
    conn = psycopg2.connect(_get_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema bootstrap ──────────────────────────────────────────────────────────

def ensure_schema() -> None:
    """
    Create the three Kraken DB tables if they don't already exist.
    Fully idempotent — safe to call on every bot startup.
    """
    if not _is_available():
        logger.debug("DB | ensure_schema skipped (PostgreSQL unavailable)")
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_KRAKEN_SCHEMA)
        logger.info("DB | Kraken schema verified / created")
    except Exception as exc:
        logger.error(f"DB | Kraken schema bootstrap failed: {exc}")


# ── Migration bootstrap ───────────────────────────────────────────────────────

def migrate_from_json(paper_portfolio_path: str) -> bool:
    """
    Seed the DB tables from paper_portfolio.json on first startup.

    Only runs when kraken_portfolio is empty (cash_usd = 0 or no row).
    Returns True if migration was performed, False if skipped.
    """
    if not _is_available():
        return False
    if not os.path.exists(paper_portfolio_path):
        return False
    try:
        with open(paper_portfolio_path) as f:
            pf = json.load(f)
    except Exception as exc:
        logger.warning(f"DB | migration_from_json: could not read {paper_portfolio_path}: {exc}")
        return False

    # Check if portfolio row already exists — row existence is authoritative.
    # Do NOT gate on cash_usd > 0: a zero-cash (fully-deployed) row is valid state.
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM kraken_portfolio WHERE id = 1")
                row = cur.fetchone()
                if row is not None:
                    logger.debug("DB | Portfolio row already exists — skipping JSON migration")
                    return False
    except Exception:
        pass

    try:
        starting = pf.get("starting_balance_usd", 100_000)
        cash     = pf.get("cash_usd", starting)
        positions = pf.get("positions", {})
        all_trades = pf.get("all_trades", [])

        with _conn() as conn:
            with conn.cursor() as cur:
                # Seed portfolio
                cur.execute(
                    """
                    INSERT INTO kraken_portfolio (id, starting_balance_usd, cash_usd, positions)
                    VALUES (1, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        starting_balance_usd = EXCLUDED.starting_balance_usd,
                        cash_usd             = EXCLUDED.cash_usd,
                        positions            = EXCLUDED.positions
                    """,
                    (starting, cash, json.dumps(positions, default=str)),
                )

                # Seed trade history (only if table is empty)
                cur.execute("SELECT COUNT(*) FROM kraken_trades")
                existing = cur.fetchone()[0]
                if existing == 0 and all_trades:
                    for t in all_trades:
                        cur.execute(
                            """
                            INSERT INTO kraken_trades
                                (symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                                 fees_usd, reason, closed_at, paper)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                            """,
                            (
                                t.get("symbol"),
                                t.get("side"),
                                t.get("entry_price", 0),
                                t.get("exit_price", 0),
                                t.get("pnl_pct", 0),
                                t.get("pnl_usd", 0),
                                t.get("fees_usd"),
                                t.get("reason"),
                                t.get("closed_at"),
                            ),
                        )
                    logger.info(f"DB | Migrated {len(all_trades)} trades from JSON")

        logger.info(
            f"DB | Migration complete — "
            f"cash=${cash:,.2f}, {len(positions)} open positions, "
            f"{len(all_trades)} historical trades"
        )
        return True

    except Exception as exc:
        logger.error(f"DB | Migration from JSON failed: {exc}")
        return False


def migrate_heartbeat_from_json(status_file_path: str) -> bool:
    """
    Seed kraken_heartbeat (id=1) from status.json if the DB row is absent.
    Only runs when the heartbeat row does not yet exist.
    Returns True if migration was performed, False if skipped.
    """
    if not _is_available():
        return False
    if not os.path.exists(status_file_path):
        return False
    # Only seed if row is absent
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM kraken_heartbeat WHERE id = 1")
                if cur.fetchone():
                    logger.debug("DB | kraken_heartbeat row exists — skipping heartbeat migration")
                    return False
    except Exception:
        return False
    # Read status.json
    try:
        with open(status_file_path) as f:
            st = json.load(f)
    except Exception as exc:
        logger.warning(f"DB | migrate_heartbeat_from_json: could not read {status_file_path}: {exc}")
        return False
    try:
        cb = st.get("circuit_breaker") or {"active": False, "paused_until": None}
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_heartbeat
                        (id, status, cycle_count, equity_usd, position_count,
                         paper_trading, bot_paused, circuit_breaker, error, last_updated)
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        st.get("status", "not_started"),
                        st.get("cycle_count", 0),
                        st.get("total_equity_usd", 0),
                        st.get("position_count", 0),
                        st.get("paper_trading", True),
                        st.get("bot_paused", False),
                        json.dumps(cb),
                        st.get("error"),
                    ),
                )
        logger.info(f"DB | Migrated heartbeat from {status_file_path} to PostgreSQL")
        return True
    except Exception as exc:
        logger.error(f"DB | migrate_heartbeat_from_json failed: {exc}")
        return False


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def upsert_heartbeat(
    status: str,
    cycle_count: int,
    equity_usd: float,
    position_count: int,
    paper_trading: bool,
    bot_paused: bool,
    circuit_breaker: dict,
    error: str | None,
) -> bool:
    """
    Upsert the single-row heartbeat (id=1) in kraken_heartbeat.
    Returns True on success, False on failure.
    """
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_heartbeat
                        (id, status, cycle_count, equity_usd, position_count,
                         paper_trading, bot_paused, circuit_breaker, error, last_updated)
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        status          = EXCLUDED.status,
                        cycle_count     = EXCLUDED.cycle_count,
                        equity_usd      = EXCLUDED.equity_usd,
                        position_count  = EXCLUDED.position_count,
                        paper_trading   = EXCLUDED.paper_trading,
                        bot_paused      = EXCLUDED.bot_paused,
                        circuit_breaker = EXCLUDED.circuit_breaker,
                        error           = EXCLUDED.error,
                        last_updated    = NOW()
                    """,
                    (
                        status,
                        cycle_count,
                        equity_usd,
                        position_count,
                        paper_trading,
                        bot_paused,
                        json.dumps(circuit_breaker),
                        error,
                    ),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | upsert_heartbeat failed: {exc}")
        return False


def load_heartbeat() -> dict | None:
    """Load the kraken_heartbeat row (id=1). Returns None if unavailable."""
    if not _is_available():
        return None
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM kraken_heartbeat WHERE id = 1")
                row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("last_updated"):
            d["last_updated"] = d["last_updated"].isoformat()
        if isinstance(d.get("circuit_breaker"), str):
            d["circuit_breaker"] = json.loads(d["circuit_breaker"])
        return d
    except Exception as exc:
        logger.warning(f"DB | load_heartbeat failed: {exc}")
        return None


# ── Portfolio ──────────────────────────────────────────────────────────────────

def load_portfolio() -> dict | None:
    """
    Load the kraken_portfolio row (id=1).
    Returns None if unavailable or not yet seeded.
    """
    if not _is_available():
        return None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT starting_balance_usd, cash_usd, positions FROM kraken_portfolio WHERE id = 1"
                )
                row = cur.fetchone()
        if not row:
            return None
        starting, cash, positions_raw = row
        if isinstance(positions_raw, str):
            positions_raw = json.loads(positions_raw)
        return {
            "starting_balance_usd": starting,
            "cash_usd":             cash,
            "positions":            positions_raw or {},
        }
    except Exception as exc:
        logger.warning(f"DB | load_portfolio failed: {exc}")
        return None


def save_portfolio(
    cash_usd: float,
    positions: dict,
    starting_balance_usd: float | None = None,
) -> bool:
    """
    Upsert the single-row portfolio (id=1).
    Returns True on success, False on failure.
    """
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                if starting_balance_usd is not None:
                    cur.execute(
                        """
                        INSERT INTO kraken_portfolio (id, starting_balance_usd, cash_usd, positions)
                        VALUES (1, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            starting_balance_usd = EXCLUDED.starting_balance_usd,
                            cash_usd             = EXCLUDED.cash_usd,
                            positions            = EXCLUDED.positions
                        """,
                        (starting_balance_usd, cash_usd, json.dumps(positions, default=str)),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO kraken_portfolio (id, cash_usd, positions)
                        VALUES (1, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            cash_usd  = EXCLUDED.cash_usd,
                            positions = EXCLUDED.positions
                        """,
                        (cash_usd, json.dumps(positions, default=str)),
                    )
        return True
    except Exception as exc:
        logger.warning(f"DB | save_portfolio failed: {exc}")
        return False


# ── Trades ────────────────────────────────────────────────────────────────────

def insert_trade(trade: dict) -> bool:
    """
    Insert a closed trade record into kraken_trades.
    The trade dict matches the format from paper_engine.paper_close_position().
    Returns True on success.
    """
    if not _is_available():
        return False
    try:
        closed_at = trade.get("closed_at")
        if isinstance(closed_at, str):
            try:
                closed_at = datetime.fromisoformat(closed_at)
            except Exception:
                closed_at = datetime.now(tz=timezone.utc)
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_trades
                        (symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                         fees_usd, reason, closed_at, paper, order_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    """,
                    (
                        trade.get("symbol"),
                        trade.get("side"),
                        trade.get("entry_price", 0),
                        trade.get("exit_price", 0),
                        trade.get("pnl_pct", 0),
                        trade.get("pnl_usd", 0),
                        trade.get("fees_usd"),
                        trade.get("reason"),
                        closed_at,
                        trade.get("order_id"),
                    ),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | insert_trade failed: {exc}")
        return False


def load_all_trades(limit: int | None = None) -> list[dict]:
    """
    Load all kraken trades ordered by closed_at ascending.
    Returns empty list if unavailable.
    """
    if not _is_available():
        return []
    try:
        sql = """
            SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                   fees_usd, reason, closed_at, paper, order_id
            FROM   kraken_trades
            ORDER  BY closed_at ASC
        """
        params = []
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        cols = ("symbol", "side", "entry_price", "exit_price", "pnl_pct", "pnl_usd",
                "fees_usd", "reason", "closed_at", "paper", "order_id")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get("closed_at"):
                d["closed_at"] = d["closed_at"].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.warning(f"DB | load_all_trades failed: {exc}")
        return []
