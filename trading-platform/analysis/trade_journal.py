"""
Trade Journal — PostgreSQL (primary) / SQLite (fallback)
---------------------------------------------------------
v2: migrated from SQLite-only to dual-backend.

PostgreSQL is used when DATABASE_URL is set (Replit managed DB).
SQLite at trade_journal.db is used as a local development fallback.

All public functions maintain the same signatures as v1 so the rest
of the codebase requires no changes.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Generator

from loguru import logger

# ── Database selection ─────────────────────────────────────────────────────

SQLITE_DB_PATH = Path(__file__).parent.parent / "trade_journal.db"


def _use_pg() -> bool:
    from db.postgres import is_pg_available
    return is_pg_available()


# ── SQLite connection helper (fallback) ────────────────────────────────────

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


# ── Schema init ────────────────────────────────────────────────────────────

def _init_sqlite() -> None:
    with _sqlite_conn() as conn:
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
        _migrate_price_columns_sqlite(conn)


def _migrate_price_columns_sqlite(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(trades)")
    existing = {row[1] for row in cursor.fetchall()}
    if "intended_price" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN intended_price REAL")
    if "actual_fill_price" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN actual_fill_price REAL")


def init_db() -> None:
    if _use_pg():
        from db.postgres import ensure_schema
        ensure_schema()
        logger.info("Trade journal | Using PostgreSQL backend")
    else:
        _init_sqlite()
        logger.info(f"Trade journal | Using SQLite fallback at {SQLITE_DB_PATH}")

    from execution.profit_sweep import init_vault_db
    init_vault_db()
    logger.info("Trade journal initialised")


# ── log_trade ──────────────────────────────────────────────────────────────

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

    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trades
                        (trade_id, date, ticker, asset_class, conviction_score,
                         original_thesis, pnl_percentage, status, intended_price)
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, 'Active', %s)
                    ON CONFLICT (trade_id) DO NOTHING
                """, (trade_id, entry_date, ticker, asset_class,
                      conviction_score, original_thesis, intended_price))
    else:
        with _sqlite_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO trades
                    (trade_id, date, ticker, asset_class, conviction_score,
                     original_thesis, pnl_percentage, status, intended_price)
                VALUES (?, ?, ?, ?, ?, ?, NULL, 'Active', ?)
            """, (trade_id, entry_date, ticker, asset_class,
                  conviction_score, original_thesis, intended_price))

    price_info = f" intended=${intended_price:.4f}" if intended_price else ""
    logger.debug(f"Trade journal | Logged {ticker} [{asset_class}] conv={conviction_score:.2f}{price_info}")


# ── update_trade_fill_price ────────────────────────────────────────────────

def update_trade_fill_price(trade_id: str, actual_fill_price: float) -> None:
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trades SET actual_fill_price = %s WHERE trade_id = %s",
                    (actual_fill_price, trade_id),
                )
                updated = cur.rowcount
        if updated > 0:
            logger.debug(f"Trade journal | Fill price updated: {trade_id} fill=${actual_fill_price:.4f}")
    else:
        with _sqlite_conn() as conn:
            cursor = conn.execute(
                "UPDATE trades SET actual_fill_price = ? WHERE trade_id = ?",
                (actual_fill_price, trade_id),
            )
            if cursor.rowcount > 0:
                logger.debug(f"Trade journal | Fill price updated: {trade_id} fill=${actual_fill_price:.4f}")


# ── update_trade_outcome ───────────────────────────────────────────────────

def update_trade_outcome(trade_id: str, pnl_percentage: float) -> None:
    status = "Closed_Win" if pnl_percentage >= 0 else "Closed_Loss"

    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE trades
                    SET pnl_percentage = %s, status = %s
                    WHERE trade_id = %s AND status = 'Active'
                """, (pnl_percentage, status, trade_id))
                updated = cur.rowcount
        if updated == 0:
            logger.warning(f"Trade journal | No active trade found for id={trade_id}")
        else:
            logger.info(f"Trade journal | Closed {trade_id} → {status} ({pnl_percentage:+.2f}%)")
    else:
        with _sqlite_conn() as conn:
            cursor = conn.execute("""
                UPDATE trades
                SET pnl_percentage = ?, status = ?
                WHERE trade_id = ? AND status = 'Active'
            """, (pnl_percentage, status, trade_id))
            if cursor.rowcount == 0:
                logger.warning(f"Trade journal | No active trade for id={trade_id}")
            else:
                logger.info(f"Trade journal | Closed {trade_id} → {status} ({pnl_percentage:+.2f}%)")


# ── Queries ────────────────────────────────────────────────────────────────

def _slippage(d: dict) -> dict:
    ip, fp = d.get("intended_price"), d.get("actual_fill_price")
    d["slippage_pct"] = (fp - ip) / ip * 100 if (ip and fp and ip > 0) else None
    return d


def get_recent_losses(limit: int = 5) -> list[dict]:
    return _query_trades("Closed_Loss", limit)


def get_recent_wins(limit: int = 5) -> list[dict]:
    return _query_trades("Closed_Win", limit)


def get_recent_trades_combined(limit: int = 20) -> list[dict]:
    """Last N closed trades (wins + losses combined) ordered by date DESC.
    Used by the /journal/recent endpoint for streak computation and Kill Board."""
    cols = ("trade_id", "date", "ticker", "pnl_percentage", "status")
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(cols)}
                    FROM   trades
                    WHERE  status IN ('Closed_Win', 'Closed_Loss')
                    ORDER  BY date DESC
                    LIMIT  %s
                """, (limit,))
                rows = cur.fetchall()
        raw = [dict(zip(cols, r)) for r in rows]
    else:
        with _sqlite_conn() as conn:
            rows = conn.execute(f"""
                SELECT {', '.join(cols)}
                FROM trades WHERE status IN ('Closed_Win', 'Closed_Loss')
                ORDER BY date DESC LIMIT ?
            """, (limit,)).fetchall()
        raw = [dict(r) for r in rows]

    # Normalise to the contract expected by the dashboard:
    # symbol / pnl_pct / pnl_usd / exit_reason / closed_at
    result = []
    for r in raw:
        result.append({
            "trade_id":    r["trade_id"],
            "symbol":      r["ticker"],
            "pnl_pct":     r["pnl_percentage"],
            "pnl_usd":     None,          # not stored in Alpaca journal (no position size)
            "exit_reason": None,          # not stored in Alpaca journal schema
            "closed_at":   str(r["date"]),
            "status":      r["status"],
        })
    return result


def _query_trades(status: str, limit: int) -> list[dict]:
    cols = ("trade_id", "date", "ticker", "asset_class", "conviction_score",
            "original_thesis", "pnl_percentage", "intended_price", "actual_fill_price")
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(cols)}
                    FROM   trades
                    WHERE  status = %s
                    ORDER  BY date DESC
                    LIMIT  %s
                """, (status, limit))
                rows = cur.fetchall()
        return [_slippage(dict(zip(cols, r))) for r in rows]
    else:
        with _sqlite_conn() as conn:
            rows = conn.execute(f"""
                SELECT {', '.join(cols)}
                FROM trades WHERE status = ?
                ORDER BY date DESC LIMIT ?
            """, (status, limit)).fetchall()
        return [_slippage(dict(r)) for r in rows]


def get_all_active_trades() -> list[dict]:
    cols = ("trade_id", "date", "ticker", "asset_class", "conviction_score",
            "original_thesis", "intended_price", "actual_fill_price")
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(cols)} FROM trades
                    WHERE status = 'Active' ORDER BY date DESC
                """)
                rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    else:
        with _sqlite_conn() as conn:
            rows = conn.execute("""
                SELECT trade_id, date, ticker, asset_class, conviction_score,
                       original_thesis, intended_price, actual_fill_price
                FROM trades WHERE status = 'Active' ORDER BY date DESC
            """).fetchall()
        return [dict(r) for r in rows]


def get_all_trades(limit: int = 200) -> list[dict]:
    cols = ("trade_id", "date", "ticker", "asset_class", "conviction_score",
            "original_thesis", "pnl_percentage", "status",
            "intended_price", "actual_fill_price")
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(cols)} FROM trades
                    ORDER BY date DESC LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
        return [_slippage(dict(zip(cols, r))) for r in rows]
    else:
        with _sqlite_conn() as conn:
            rows = conn.execute(f"""
                SELECT {', '.join(cols)} FROM trades ORDER BY date DESC LIMIT ?
            """, (limit,)).fetchall()
        return [_slippage(dict(r)) for r in rows]


def get_journal_summary() -> dict:
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*)                                           AS total,
                        SUM(CASE WHEN status = 'Active'      THEN 1 END)  AS active,
                        SUM(CASE WHEN status = 'Closed_Win'  THEN 1 END)  AS wins,
                        SUM(CASE WHEN status = 'Closed_Loss' THEN 1 END)  AS losses,
                        AVG(CASE WHEN status != 'Active' THEN pnl_percentage END) AS avg_pnl
                    FROM trades
                """)
                row = cur.fetchone()
        keys = ("total", "active", "wins", "losses", "avg_pnl")
        return dict(zip(keys, row))
    else:
        with _sqlite_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN status='Active' THEN 1 END) AS active,
                    SUM(CASE WHEN status='Closed_Win' THEN 1 END) AS wins,
                    SUM(CASE WHEN status='Closed_Loss' THEN 1 END) AS losses,
                    AVG(CASE WHEN status!='Active' THEN pnl_percentage END) AS avg_pnl
                FROM trades
            """).fetchone()
        return dict(row)


def get_slippage_stats() -> dict:
    base_q = """
        WHERE intended_price IS NOT NULL
          AND actual_fill_price IS NOT NULL
          AND intended_price > 0
          AND status != 'Active'
    """
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT COUNT(*),
                        AVG(ABS((actual_fill_price-intended_price)/intended_price*100)),
                        MAX(ABS((actual_fill_price-intended_price)/intended_price*100))
                    FROM trades {base_q}
                """)
                agg = cur.fetchone()
                cur.execute(f"""
                    SELECT ticker,
                        ABS((actual_fill_price-intended_price)/intended_price*100) AS slip
                    FROM trades {base_q}
                    ORDER BY slip DESC LIMIT 5
                """)
                worst = cur.fetchall()
        result = {
            "total_with_slippage": agg[0] or 0,
            "avg_slippage_pct":    agg[1],
            "max_slippage_pct":    agg[2],
            "worst_slippage_tickers": [{"ticker": r[0], "slip_pct": r[1]} for r in worst],
        }
    else:
        with _sqlite_conn() as conn:
            agg = conn.execute(f"""
                SELECT COUNT(*),
                    AVG(ABS((actual_fill_price-intended_price)/intended_price*100)),
                    MAX(ABS((actual_fill_price-intended_price)/intended_price*100))
                FROM trades {base_q}
            """).fetchone()
            worst = conn.execute(f"""
                SELECT ticker,
                    ABS((actual_fill_price-intended_price)/intended_price*100) AS slip_pct
                FROM trades {base_q}
                ORDER BY slip_pct DESC LIMIT 5
            """).fetchall()
        result = {
            "total_with_slippage": agg[0] or 0,
            "avg_slippage_pct":    agg[1],
            "max_slippage_pct":    agg[2],
            "worst_slippage_tickers": [dict(r) for r in worst],
        }
    return result


# ── Performance snapshots ──────────────────────────────────────────────────

def save_performance_snapshot(
    snap_date: str,
    equity: float,
    daily_pnl_pct: float,
    cumulative_pnl_pct: float,
    win_rate: float,
    trades_placed: int,
) -> None:
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO performance_snapshots
                        (date, equity, daily_pnl_pct, cumulative_pnl_pct,
                         win_rate, trades_placed)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        equity             = EXCLUDED.equity,
                        daily_pnl_pct      = EXCLUDED.daily_pnl_pct,
                        cumulative_pnl_pct = EXCLUDED.cumulative_pnl_pct,
                        win_rate           = EXCLUDED.win_rate,
                        trades_placed      = EXCLUDED.trades_placed
                """, (snap_date, equity, daily_pnl_pct, cumulative_pnl_pct,
                      win_rate, trades_placed))
    else:
        with _sqlite_conn() as conn:
            conn.execute("""
                INSERT INTO performance_snapshots
                    (date, equity, daily_pnl_pct, cumulative_pnl_pct, win_rate, trades_placed)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    equity=excluded.equity, daily_pnl_pct=excluded.daily_pnl_pct,
                    cumulative_pnl_pct=excluded.cumulative_pnl_pct,
                    win_rate=excluded.win_rate, trades_placed=excluded.trades_placed
            """, (snap_date, equity, daily_pnl_pct, cumulative_pnl_pct,
                  win_rate, trades_placed))

    logger.info(
        f"Performance snapshot saved | {snap_date} equity=${equity:,.2f} "
        f"daily={daily_pnl_pct:+.2f}% cum={cumulative_pnl_pct:+.2f}% wr={win_rate:.1%}"
    )


def get_performance_snapshots(limit: int = 90) -> list[dict]:
    cols = ("date", "equity", "daily_pnl_pct", "cumulative_pnl_pct",
            "win_rate", "trades_placed")
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(cols)} FROM performance_snapshots
                    ORDER BY date ASC LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    else:
        with _sqlite_conn() as conn:
            rows = conn.execute(f"""
                SELECT {', '.join(cols)} FROM performance_snapshots
                ORDER BY date ASC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_performance_summary() -> dict:
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*), SUM(trades_placed), MAX(daily_pnl_pct),
                           MIN(daily_pnl_pct), AVG(win_rate),
                           MAX(cumulative_pnl_pct), MIN(cumulative_pnl_pct)
                    FROM performance_snapshots
                """)
                agg = cur.fetchone()
                cur.execute("""
                    SELECT equity, cumulative_pnl_pct, date
                    FROM performance_snapshots ORDER BY date DESC LIMIT 1
                """)
                latest = cur.fetchone()
                cur.execute("""
                    SELECT AVG(conviction_score)
                    FROM trades WHERE status IN ('Closed_Win','Closed_Loss')
                """)
                conv = cur.fetchone()
        keys = ("total_days", "total_trades", "best_day_pct", "worst_day_pct",
                "avg_win_rate", "max_cumulative_pnl_pct", "min_cumulative_pnl_pct")
        result = dict(zip(keys, agg)) if agg else {}
        if latest:
            result["latest_equity"]    = latest[0]
            result["total_return_pct"] = latest[1]
            result["latest_date"]      = str(latest[2])
        result["avg_conviction"] = conv[0] if conv else None
    else:
        with _sqlite_conn() as conn:
            agg = conn.execute("""
                SELECT COUNT(*), SUM(trades_placed), MAX(daily_pnl_pct),
                       MIN(daily_pnl_pct), AVG(win_rate),
                       MAX(cumulative_pnl_pct), MIN(cumulative_pnl_pct)
                FROM performance_snapshots
            """).fetchone()
            latest = conn.execute("""
                SELECT equity, cumulative_pnl_pct, date
                FROM performance_snapshots ORDER BY date DESC LIMIT 1
            """).fetchone()
            conv = conn.execute("""
                SELECT AVG(conviction_score) FROM trades
                WHERE status IN ('Closed_Win','Closed_Loss')
            """).fetchone()
        result = dict(agg) if agg else {}
        if latest:
            result["latest_equity"]    = latest["equity"]
            result["total_return_pct"] = latest["cumulative_pnl_pct"]
            result["latest_date"]      = latest["date"]
        result["avg_conviction"] = conv[0] if conv else None
    return result
