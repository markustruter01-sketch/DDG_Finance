"""
db.py — PostgreSQL access layer for the Navigator Forex bot.

Tables:
  forex_heartbeat — single row (id=10) for dashboard polling
  forex_portfolio — single row (id=10) for paper portfolio state
  forex_trades    — append-only trade history
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
    logger.warning("DB | psycopg2 not installed — Forex bot DB unavailable")


_FOREX_SCHEMA = """
CREATE TABLE IF NOT EXISTS forex_heartbeat (
    id              INTEGER PRIMARY KEY,
    bot_id          TEXT    NOT NULL DEFAULT 'navigator',
    status          TEXT    NOT NULL DEFAULT 'not_started',
    cycle_count     INTEGER NOT NULL DEFAULT 0,
    equity_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    position_count  INTEGER NOT NULL DEFAULT 0,
    paper_trading   BOOLEAN NOT NULL DEFAULT TRUE,
    bot_paused      BOOLEAN NOT NULL DEFAULT FALSE,
    usd_bias        TEXT    DEFAULT 'NEUTRAL',
    news_blackout   BOOLEAN NOT NULL DEFAULT FALSE,
    error           TEXT,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS forex_portfolio (
    id                   INTEGER PRIMARY KEY,
    bot_id               TEXT NOT NULL DEFAULT 'navigator',
    starting_balance_usd DOUBLE PRECISION NOT NULL DEFAULT 100000,
    cash_usd             DOUBLE PRECISION NOT NULL DEFAULT 100000,
    positions            JSONB NOT NULL DEFAULT '{}',
    hwm_usd              DOUBLE PRECISION NOT NULL DEFAULT 100000,
    vault_total_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_sweep_date      TEXT
);

CREATE TABLE IF NOT EXISTS forex_trades (
    id          BIGSERIAL PRIMARY KEY,
    bot_id      TEXT             NOT NULL DEFAULT 'navigator',
    pair        TEXT             NOT NULL,
    direction   TEXT             NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price  DOUBLE PRECISION,
    sl_price    DOUBLE PRECISION,
    tp_price    DOUBLE PRECISION,
    units       DOUBLE PRECISION NOT NULL DEFAULT 0,
    llm_thesis  TEXT,
    status      TEXT             NOT NULL DEFAULT 'open',
    entry_time  TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    exit_time   TIMESTAMPTZ,
    pnl_pips    DOUBLE PRECISION,
    pnl_usd     DOUBLE PRECISION,
    paper       BOOLEAN          NOT NULL DEFAULT TRUE,
    final_trailing_sl DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_forex_trades_entry_time ON forex_trades (entry_time DESC);
"""


def _get_dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


def _is_available() -> bool:
    return _PG_AVAILABLE and bool(_get_dsn())


@contextmanager
def _conn() -> "Generator[psycopg2.extensions.connection, None, None]":
    conn = psycopg2.connect(_get_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


BOT_ID = "navigator"
DB_ID = 10


def ensure_schema() -> None:
    if not _is_available():
        logger.debug("DB | ensure_schema skipped (PostgreSQL unavailable)")
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_FOREX_SCHEMA)
                try:
                    cur.execute("""
                        ALTER TABLE forex_trades
                        ADD COLUMN IF NOT EXISTS final_trailing_sl DOUBLE PRECISION
                    """)
                except Exception:
                    pass
        logger.info("DB | Forex schema verified")
    except Exception as exc:
        logger.error(f"DB | Forex schema bootstrap failed: {exc}")


def upsert_heartbeat(
    status: str,
    cycle_count: int,
    equity_usd: float,
    position_count: int,
    paper_trading: bool,
    bot_paused: bool,
    usd_bias: str = "NEUTRAL",
    news_blackout: bool = False,
    error: str | None = None,
) -> bool:
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forex_heartbeat
                        (id, bot_id, status, cycle_count, equity_usd, position_count,
                         paper_trading, bot_paused, usd_bias, news_blackout, error, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        bot_id          = EXCLUDED.bot_id,
                        status          = EXCLUDED.status,
                        cycle_count     = EXCLUDED.cycle_count,
                        equity_usd      = EXCLUDED.equity_usd,
                        position_count  = EXCLUDED.position_count,
                        paper_trading   = EXCLUDED.paper_trading,
                        bot_paused      = EXCLUDED.bot_paused,
                        usd_bias        = EXCLUDED.usd_bias,
                        news_blackout   = EXCLUDED.news_blackout,
                        error           = EXCLUDED.error,
                        last_updated    = NOW()
                    """,
                    (DB_ID, BOT_ID, status, cycle_count, equity_usd, position_count,
                     paper_trading, bot_paused, usd_bias, news_blackout, error),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | upsert_heartbeat failed: {exc}")
        return False


def load_heartbeat() -> dict | None:
    if not _is_available():
        return None
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM forex_heartbeat WHERE id = %s", (DB_ID,))
                row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("last_updated"):
            d["last_updated"] = d["last_updated"].isoformat()
        return d
    except Exception as exc:
        logger.warning(f"DB | load_heartbeat failed: {exc}")
        return None


def load_portfolio() -> dict | None:
    if not _is_available():
        return None
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT starting_balance_usd, cash_usd, positions, hwm_usd, vault_total_usd, last_sweep_date FROM forex_portfolio WHERE id = %s",
                    (DB_ID,)
                )
                row = cur.fetchone()
        if not row:
            return None
        starting, cash, positions_raw, hwm, vault, last_sweep = row
        if isinstance(positions_raw, str):
            positions_raw = json.loads(positions_raw)
        return {
            "starting_balance_usd": starting,
            "cash_usd": cash,
            "positions": positions_raw or {},
            "hwm_usd": hwm,
            "vault_total_usd": vault,
            "last_sweep_date": last_sweep,
        }
    except Exception as exc:
        logger.warning(f"DB | load_portfolio failed: {exc}")
        return None


def save_portfolio(
    cash_usd: float,
    positions: dict,
    starting_balance_usd: float | None = None,
    hwm_usd: float | None = None,
    vault_total_usd: float | None = None,
    last_sweep_date: str | None = None,
) -> bool:
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forex_portfolio (id, bot_id, starting_balance_usd, cash_usd, positions, hwm_usd, vault_total_usd, last_sweep_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        bot_id               = EXCLUDED.bot_id,
                        starting_balance_usd = EXCLUDED.starting_balance_usd,
                        cash_usd             = EXCLUDED.cash_usd,
                        positions            = EXCLUDED.positions,
                        hwm_usd              = EXCLUDED.hwm_usd,
                        vault_total_usd      = EXCLUDED.vault_total_usd,
                        last_sweep_date      = EXCLUDED.last_sweep_date
                    """,
                    (
                        DB_ID, BOT_ID,
                        starting_balance_usd or 100_000,
                        cash_usd,
                        json.dumps(positions, default=str),
                        hwm_usd or 100_000,
                        vault_total_usd or 0,
                        last_sweep_date,
                    ),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | save_portfolio failed: {exc}")
        return False


def insert_trade(trade: dict) -> bool:
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forex_trades
                        (bot_id, pair, direction, entry_price, exit_price, sl_price, tp_price,
                         units, llm_thesis, status, entry_time, exit_time, pnl_pips, pnl_usd, paper)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (
                        BOT_ID,
                        trade.get("pair"),
                        trade.get("direction"),
                        trade.get("entry_price", 0),
                        trade.get("exit_price"),
                        trade.get("sl_price"),
                        trade.get("tp_price"),
                        trade.get("units", 0),
                        trade.get("llm_thesis"),
                        trade.get("status", "open"),
                        trade.get("entry_time"),
                        trade.get("exit_time"),
                        trade.get("pnl_pips"),
                        trade.get("pnl_usd"),
                    ),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | insert_trade failed: {exc}")
        return False


def update_trade_close(trade_id: int, exit_price: float, pnl_pips: float, pnl_usd: float,
                       final_trailing_sl: float | None = None) -> bool:
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE forex_trades SET
                        exit_price = %s,
                        pnl_pips   = %s,
                        pnl_usd    = %s,
                        final_trailing_sl = %s,
                        status     = 'closed',
                        exit_time  = NOW()
                    WHERE id = %s
                    """,
                    (exit_price, pnl_pips, pnl_usd, final_trailing_sl, trade_id),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | update_trade_close failed: {exc}")
        return False


def load_open_trades() -> list[dict]:
    if not _is_available():
        return []
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forex_trades WHERE bot_id = %s AND status = 'open' ORDER BY entry_time DESC",
                    (BOT_ID,),
                )
                rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for k in ("entry_time", "exit_time"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.warning(f"DB | load_open_trades failed: {exc}")
        return []


def load_recent_trades(limit: int = 50) -> list[dict]:
    if not _is_available():
        return []
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forex_trades WHERE bot_id = %s ORDER BY entry_time DESC LIMIT %s",
                    (BOT_ID, limit),
                )
                rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for k in ("entry_time", "exit_time"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.warning(f"DB | load_recent_trades failed: {exc}")
        return []


def load_losing_trades(limit: int = 5) -> list[dict]:
    if not _is_available():
        return []
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT pair, direction, llm_thesis, pnl_pips, pnl_usd
                    FROM forex_trades
                    WHERE bot_id = %s AND status = 'closed' AND pnl_usd < 0
                    ORDER BY exit_time DESC LIMIT %s
                    """,
                    (BOT_ID, limit),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning(f"DB | load_losing_trades failed: {exc}")
        return []


def load_vault_history() -> list[dict]:
    if not _is_available():
        return []
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM forex_vault WHERE bot_id = %s ORDER BY sweep_date DESC LIMIT 52
                    """,
                    (BOT_ID,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def ensure_vault_table() -> None:
    if not _is_available():
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS forex_vault (
                        id          BIGSERIAL PRIMARY KEY,
                        bot_id      TEXT NOT NULL DEFAULT 'navigator',
                        sweep_date  TEXT NOT NULL,
                        amount      DOUBLE PRECISION NOT NULL,
                        running_total DOUBLE PRECISION NOT NULL,
                        equity_at_sweep DOUBLE PRECISION NOT NULL DEFAULT 0
                    )
                """)
    except Exception as exc:
        logger.warning(f"DB | ensure_vault_table failed: {exc}")


def insert_vault_sweep(sweep_date: str, amount: float, running_total: float, equity: float) -> bool:
    if not _is_available():
        return False
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forex_vault (bot_id, sweep_date, amount, running_total, equity_at_sweep)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (BOT_ID, sweep_date, amount, running_total, equity),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | insert_vault_sweep failed: {exc}")
        return False
