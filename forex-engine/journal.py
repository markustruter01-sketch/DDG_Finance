"""
journal.py — SQLite trade journal for RAG loop and analytics.
Mirrors forex_trades from PostgreSQL into a local SQLite file for fast queries.
"""

import os
import sqlite3
from datetime import datetime, timezone

from loguru import logger

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_DB_PATH = os.path.join(_ENGINE_DIR, "forex_journal.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    ticket_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    pair        TEXT NOT NULL,
    direction   TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price  REAL,
    sl_price    REAL,
    tp_price    REAL,
    units       REAL NOT NULL DEFAULT 0,
    llm_thesis  TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    entry_time  TEXT,
    exit_time   TEXT,
    pnl_pips    REAL,
    pnl_usd     REAL,
    usd_bias    TEXT,
    rsi_at_entry REAL,
    atr_at_entry REAL,
    final_trailing_sl REAL
);

CREATE TABLE IF NOT EXISTS withdrawable_vault (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_date  TEXT NOT NULL,
    sweep_amount REAL NOT NULL,
    equity_at_sweep REAL NOT NULL,
    hwm_at_sweep REAL NOT NULL,
    vault_total REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
"""

_journal_init = False


def _get_conn() -> sqlite3.Connection:
    global _journal_init
    conn = sqlite3.connect(JOURNAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    if not _journal_init:
        conn.executescript(_SCHEMA)
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN final_trailing_sl REAL")
            conn.commit()
        except Exception:
            pass
        _journal_init = True
    return conn


def log_trade_open(
    pair: str, direction: str, entry_price: float, sl_price: float, tp_price: float,
    units: float, llm_thesis: str = "", usd_bias: str = "NEUTRAL",
    rsi_at_entry: float = 0.0, atr_at_entry: float = 0.0,
) -> int | None:
    try:
        conn = _get_conn()
        cur = conn.execute(
            """INSERT INTO trades (pair, direction, entry_price, sl_price, tp_price, units,
               llm_thesis, status, entry_time, usd_bias, rsi_at_entry, atr_at_entry)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (pair, direction, entry_price, sl_price, tp_price, units, llm_thesis,
             datetime.now(tz=timezone.utc).isoformat(), usd_bias, rsi_at_entry, atr_at_entry),
        )
        conn.commit()
        ticket_id = cur.lastrowid
        conn.close()
        return ticket_id
    except Exception as exc:
        logger.warning(f"Journal | log_trade_open failed: {exc}")
        return None


def log_trade_close(
    pair: str, exit_price: float, pnl_pips: float, pnl_usd: float,
    final_trailing_sl: float | None = None,
) -> bool:
    try:
        conn = _get_conn()
        conn.execute(
            """UPDATE trades SET exit_price = ?, pnl_pips = ?, pnl_usd = ?,
               final_trailing_sl = ?,
               status = 'closed', exit_time = ? WHERE pair = ? AND status = 'open'""",
            (exit_price, pnl_pips, pnl_usd, final_trailing_sl,
             datetime.now(tz=timezone.utc).isoformat(), pair),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        logger.warning(f"Journal | log_trade_close failed: {exc}")
        return False


def log_vault_sweep(
    sweep_amount: float, equity_at_sweep: float, hwm_at_sweep: float, vault_total: float,
) -> bool:
    try:
        conn = _get_conn()
        now = datetime.now(tz=timezone.utc)
        conn.execute(
            """INSERT INTO withdrawable_vault (sweep_date, sweep_amount, equity_at_sweep,
               hwm_at_sweep, vault_total, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (now.strftime("%Y-%m-%d"), sweep_amount, equity_at_sweep,
             hwm_at_sweep, vault_total, now.isoformat()),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        logger.warning(f"Journal | log_vault_sweep failed: {exc}")
        return False


def get_vault_history(limit: int = 20) -> list[dict]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM withdrawable_vault ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_recent_losers(limit: int = 5) -> list[dict]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT pair, direction, llm_thesis, pnl_pips, pnl_usd, usd_bias
               FROM trades WHERE status = 'closed' AND pnl_usd < 0
               ORDER BY exit_time DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_journal_entries(limit: int = 50) -> list[dict]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_journal_stats() -> dict:
    try:
        conn = _get_conn()
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl_usd < 0 THEN 1 ELSE 0 END) as losses,
                COALESCE(SUM(pnl_usd), 0) as total_pnl,
                COALESCE(AVG(pnl_pips), 0) as avg_pips
               FROM trades WHERE status = 'closed'"""
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0, "avg_pips": 0}
    except Exception:
        return {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0, "avg_pips": 0}
