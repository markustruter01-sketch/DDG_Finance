"""
Trade Journal — SQLite Database
---------------------------------
Uses Python's built-in sqlite3 to maintain a local trade_journal.db.
No external database required — entirely free infrastructure.

Schema:
  trades (
      trade_id        TEXT PRIMARY KEY,
      date            TEXT NOT NULL,
      ticker          TEXT NOT NULL,
      asset_class     TEXT NOT NULL,
      conviction_score REAL NOT NULL,
      original_thesis TEXT NOT NULL,
      pnl_percentage  REAL,
      status          TEXT NOT NULL       -- Active | Closed_Win | Closed_Loss
  )

  performance_snapshots (
      date               TEXT PRIMARY KEY,
      equity             REAL NOT NULL,
      daily_pnl_pct      REAL NOT NULL,
      cumulative_pnl_pct REAL NOT NULL,
      win_rate           REAL NOT NULL,
      trades_placed      INTEGER NOT NULL
  )
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator

from loguru import logger

DB_PATH = Path(__file__).parent.parent / "trade_journal.db"


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


def init_db() -> None:
    """
    Create the trade_journal.db and all tables if they don't already exist.
    Safe to call on every startup.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id         TEXT PRIMARY KEY,
                date             TEXT NOT NULL,
                ticker           TEXT NOT NULL,
                asset_class      TEXT NOT NULL,
                conviction_score REAL NOT NULL,
                original_thesis  TEXT NOT NULL,
                pnl_percentage   REAL,
                status           TEXT NOT NULL DEFAULT 'Active'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_status
            ON trades (status, date DESC)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_snapshots (
                date               TEXT PRIMARY KEY,
                equity             REAL NOT NULL,
                daily_pnl_pct      REAL NOT NULL,
                cumulative_pnl_pct REAL NOT NULL,
                win_rate           REAL NOT NULL,
                trades_placed      INTEGER NOT NULL DEFAULT 0
            )
        """)
    logger.info(f"Trade journal initialised at: {DB_PATH}")


def log_trade(
    trade_id: str,
    ticker: str,
    asset_class: str,
    conviction_score: float,
    original_thesis: str,
    trade_date: str | None = None,
) -> None:
    """
    Insert a new trade record with status='Active'.
    """
    entry_date = trade_date or date.today().isoformat()
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO trades
                (trade_id, date, ticker, asset_class, conviction_score,
                 original_thesis, pnl_percentage, status)
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'Active')
        """, (trade_id, entry_date, ticker, asset_class, conviction_score, original_thesis))
    logger.debug(f"Trade journal | Logged {ticker} [{asset_class}] conv={conviction_score:.2f}")


def update_trade_outcome(trade_id: str, pnl_percentage: float) -> None:
    """
    Close a trade and record its P&L. Automatically sets status to
    'Closed_Win' or 'Closed_Loss' based on the sign of pnl_percentage.
    """
    status = "Closed_Win" if pnl_percentage >= 0 else "Closed_Loss"
    with _get_conn() as conn:
        cursor = conn.execute("""
            UPDATE trades
            SET pnl_percentage = ?,
                status         = ?
            WHERE trade_id = ?
              AND status    = 'Active'
        """, (pnl_percentage, status, trade_id))
        if cursor.rowcount == 0:
            logger.warning(
                f"Trade journal | No active trade found for id={trade_id} "
                f"(already closed or unknown)"
            )
        else:
            logger.info(
                f"Trade journal | Closed trade_id={trade_id} → {status} "
                f"({pnl_percentage:+.2f}%)"
            )


def get_recent_losses(limit: int = 5) -> list[dict]:
    """
    Return the N most recent Closed_Loss trades, ordered by date descending.
    Used by the feedback injection function to build the learning prompt.
    """
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis, pnl_percentage
            FROM   trades
            WHERE  status = 'Closed_Loss'
            ORDER  BY date DESC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_recent_wins(limit: int = 5) -> list[dict]:
    """
    Return the N most recent Closed_Win trades, ordered by date descending.
    Used by the feedback injection function to build the 'what worked' block.
    """
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis, pnl_percentage
            FROM   trades
            WHERE  status = 'Closed_Win'
            ORDER  BY date DESC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_all_active_trades() -> list[dict]:
    """Return all trades currently marked Active."""
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis
            FROM   trades
            WHERE  status = 'Active'
            ORDER  BY date DESC
        """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_all_trades(limit: int = 200) -> list[dict]:
    """Return all trades ordered by date descending (for the /journal API)."""
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis,
                   pnl_percentage, status
            FROM   trades
            ORDER  BY date DESC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_journal_summary() -> dict:
    """Return aggregate stats for logging/monitoring."""
    with _get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                          AS total,
                SUM(CASE WHEN status = 'Active'      THEN 1 END) AS active,
                SUM(CASE WHEN status = 'Closed_Win'  THEN 1 END) AS wins,
                SUM(CASE WHEN status = 'Closed_Loss' THEN 1 END) AS losses,
                AVG(CASE WHEN status != 'Active'
                         THEN pnl_percentage END)                AS avg_pnl
            FROM trades
        """).fetchone()
    return dict(row)


def save_performance_snapshot(
    snap_date: str,
    equity: float,
    daily_pnl_pct: float,
    cumulative_pnl_pct: float,
    win_rate: float,
    trades_placed: int,
) -> None:
    """
    Upsert a daily performance snapshot (called at end of each post-mortem).
    """
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO performance_snapshots
                (date, equity, daily_pnl_pct, cumulative_pnl_pct, win_rate, trades_placed)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                equity             = excluded.equity,
                daily_pnl_pct      = excluded.daily_pnl_pct,
                cumulative_pnl_pct = excluded.cumulative_pnl_pct,
                win_rate           = excluded.win_rate,
                trades_placed      = excluded.trades_placed
        """, (snap_date, equity, daily_pnl_pct, cumulative_pnl_pct, win_rate, trades_placed))
    logger.info(
        f"Performance snapshot saved | {snap_date} "
        f"equity=${equity:,.2f} daily={daily_pnl_pct:+.2f}% "
        f"cum={cumulative_pnl_pct:+.2f}% wr={win_rate:.1%}"
    )


def get_performance_snapshots(limit: int = 90) -> list[dict]:
    """Return up to N daily performance snapshots, oldest first (for charting)."""
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT date, equity, daily_pnl_pct, cumulative_pnl_pct,
                   win_rate, trades_placed
            FROM   performance_snapshots
            ORDER  BY date ASC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_performance_summary() -> dict:
    """Return aggregate performance statistics across all snapshots."""
    with _get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                    AS total_days,
                SUM(trades_placed)          AS total_trades,
                MAX(daily_pnl_pct)          AS best_day_pct,
                MIN(daily_pnl_pct)          AS worst_day_pct,
                AVG(win_rate)               AS avg_win_rate,
                MAX(cumulative_pnl_pct)     AS max_cumulative_pnl_pct,
                MIN(cumulative_pnl_pct)     AS min_cumulative_pnl_pct
            FROM performance_snapshots
        """).fetchone()
        latest = conn.execute("""
            SELECT equity, cumulative_pnl_pct, date
            FROM   performance_snapshots
            ORDER  BY date DESC
            LIMIT  1
        """).fetchone()
    result = dict(row) if row else {}
    if latest:
        result["latest_equity"] = latest["equity"]
        result["total_return_pct"] = latest["cumulative_pnl_pct"]
        result["latest_date"] = latest["date"]
    return result
