"""
Trade Journal — SQLite Database
---------------------------------
Uses Python's built-in sqlite3 to maintain a local trade_journal.db.
No external database required — entirely free infrastructure.

Schema:
  trades (
      trade_id         TEXT PRIMARY KEY,
      date             TEXT NOT NULL,
      ticker           TEXT NOT NULL,
      asset_class      TEXT NOT NULL,
      conviction_score REAL NOT NULL,
      original_thesis  TEXT NOT NULL,
      pnl_percentage   REAL,
      status           TEXT NOT NULL       -- Active | Closed_Win | Closed_Loss
      intended_price   REAL,               -- price at moment of order placement
      actual_fill_price REAL               -- actual filled price from Alpaca
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


def _migrate_add_price_columns(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(trades)")
    existing = {row[1] for row in cursor.fetchall()}

    if "intended_price" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN intended_price REAL")
        logger.info("Migration | Added 'intended_price' column to trades table")

    if "actual_fill_price" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN actual_fill_price REAL")
        logger.info("Migration | Added 'actual_fill_price' column to trades table")


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id          TEXT PRIMARY KEY,
                date              TEXT NOT NULL,
                ticker            TEXT NOT NULL,
                asset_class       TEXT NOT NULL,
                conviction_score  REAL NOT NULL,
                original_thesis   TEXT NOT NULL,
                pnl_percentage    REAL,
                status            TEXT NOT NULL DEFAULT 'Active',
                intended_price    REAL,
                actual_fill_price REAL
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
        _migrate_add_price_columns(conn)

    from execution.profit_sweep import init_vault_db
    init_vault_db()

    logger.info(f"Trade journal initialised at: {DB_PATH}")


def log_trade(
    trade_id: str,
    ticker: str,
    asset_class: str,
    conviction_score: float,
    original_thesis: str,
    trade_date: str | None = None,
    intended_price: float | None = None,
) -> None:
    entry_date = trade_date or date.today().isoformat()
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO trades
                (trade_id, date, ticker, asset_class, conviction_score,
                 original_thesis, pnl_percentage, status, intended_price)
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'Active', ?)
        """, (trade_id, entry_date, ticker, asset_class, conviction_score,
              original_thesis, intended_price))
    price_info = f" intended=${intended_price:.4f}" if intended_price else ""
    logger.debug(f"Trade journal | Logged {ticker} [{asset_class}] conv={conviction_score:.2f}{price_info}")


def update_trade_fill_price(trade_id: str, actual_fill_price: float) -> None:
    with _get_conn() as conn:
        cursor = conn.execute("""
            UPDATE trades SET actual_fill_price = ? WHERE trade_id = ?
        """, (actual_fill_price, trade_id))
        if cursor.rowcount > 0:
            logger.debug(f"Trade journal | Fill price updated: trade_id={trade_id} fill=${actual_fill_price:.4f}")


def update_trade_outcome(trade_id: str, pnl_percentage: float) -> None:
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
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis, pnl_percentage,
                   intended_price, actual_fill_price
            FROM   trades
            WHERE  status = 'Closed_Loss'
            ORDER  BY date DESC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    results = []
    for row in rows:
        d = dict(row)
        ip = d.get("intended_price")
        fp = d.get("actual_fill_price")
        if ip and fp and ip > 0:
            d["slippage_pct"] = (fp - ip) / ip * 100
        else:
            d["slippage_pct"] = None
        results.append(d)
    return results


def get_recent_wins(limit: int = 5) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis, pnl_percentage,
                   intended_price, actual_fill_price
            FROM   trades
            WHERE  status = 'Closed_Win'
            ORDER  BY date DESC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    results = []
    for row in rows:
        d = dict(row)
        ip = d.get("intended_price")
        fp = d.get("actual_fill_price")
        if ip and fp and ip > 0:
            d["slippage_pct"] = (fp - ip) / ip * 100
        else:
            d["slippage_pct"] = None
        results.append(d)
    return results


def get_all_active_trades() -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis,
                   intended_price, actual_fill_price
            FROM   trades
            WHERE  status = 'Active'
            ORDER  BY date DESC
        """)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_all_trades(limit: int = 200) -> list[dict]:
    with _get_conn() as conn:
        cursor = conn.execute("""
            SELECT trade_id, date, ticker, asset_class,
                   conviction_score, original_thesis,
                   pnl_percentage, status,
                   intended_price, actual_fill_price
            FROM   trades
            ORDER  BY date DESC
            LIMIT  ?
        """, (limit,))
        rows = cursor.fetchall()
    results = []
    for row in rows:
        d = dict(row)
        ip = d.get("intended_price")
        fp = d.get("actual_fill_price")
        if ip and fp and ip > 0:
            d["slippage_pct"] = (fp - ip) / ip * 100
        else:
            d["slippage_pct"] = None
        results.append(d)
    return results


def get_journal_summary() -> dict:
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


def get_slippage_stats() -> dict:
    with _get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                              AS total_with_slippage,
                AVG(ABS((actual_fill_price - intended_price) / intended_price * 100))
                                                                      AS avg_slippage_pct,
                MAX(ABS((actual_fill_price - intended_price) / intended_price * 100))
                                                                      AS max_slippage_pct
            FROM trades
            WHERE intended_price IS NOT NULL
              AND actual_fill_price IS NOT NULL
              AND intended_price > 0
              AND status != 'Active'
        """).fetchone()

        worst_row = conn.execute("""
            SELECT ticker,
                   ABS((actual_fill_price - intended_price) / intended_price * 100) AS slip_pct
            FROM trades
            WHERE intended_price IS NOT NULL
              AND actual_fill_price IS NOT NULL
              AND intended_price > 0
              AND status != 'Active'
            ORDER BY slip_pct DESC
            LIMIT 5
        """).fetchall()
    result = dict(row) if row else {"total_with_slippage": 0, "avg_slippage_pct": None, "max_slippage_pct": None}
    result["worst_slippage_tickers"] = [dict(r) for r in worst_row]
    return result


def save_performance_snapshot(
    snap_date: str,
    equity: float,
    daily_pnl_pct: float,
    cumulative_pnl_pct: float,
    win_rate: float,
    trades_placed: int,
) -> None:
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
        conviction_row = conn.execute("""
            SELECT AVG(conviction_score) AS avg_conviction
            FROM   trades
            WHERE  status IN ('Closed_Win', 'Closed_Loss')
        """).fetchone()
    result = dict(row) if row else {}
    if latest:
        result["latest_equity"] = latest["equity"]
        result["total_return_pct"] = latest["cumulative_pnl_pct"]
        result["latest_date"] = latest["date"]
    result["avg_conviction"] = conviction_row["avg_conviction"] if conviction_row else None
    return result
