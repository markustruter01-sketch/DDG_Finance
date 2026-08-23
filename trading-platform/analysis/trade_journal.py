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
from typing import Generator, Optional

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
                trade_id            TEXT PRIMARY KEY,
                date                TEXT NOT NULL,
                ticker              TEXT NOT NULL,
                asset_class         TEXT NOT NULL,
                conviction_score    REAL NOT NULL,
                original_thesis     TEXT NOT NULL,
                pnl_percentage      REAL,
                status              TEXT NOT NULL DEFAULT 'Active',
                intended_price      REAL,
                actual_fill_price   REAL,
                regime_at_entry     TEXT,
                time_in_trade_hours REAL,
                exit_reason         TEXT,
                realized_pnl        REAL,
                slippage_pct        REAL,
                closed_at           TEXT
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
        # Phase 1: execution_post_mortems (SQLite fallback)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_post_mortems (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                ts                    TEXT NOT NULL DEFAULT (datetime('now')),
                ticker                TEXT NOT NULL,
                regime                TEXT NOT NULL,
                asset_class           TEXT,
                exit_reason           TEXT,
                pnl_pct               REAL,
                time_in_trade_hours   REAL,
                hardcoded_lesson_text TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pm_ts ON execution_post_mortems (ts DESC)
        """)
        _migrate_price_columns_sqlite(conn)


def _migrate_price_columns_sqlite(conn: sqlite3.Connection) -> None:
    cursor = conn.execute("PRAGMA table_info(trades)")
    existing = {row[1] for row in cursor.fetchall()}
    if "intended_price" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN intended_price REAL")
    if "actual_fill_price" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN actual_fill_price REAL")
    # Phase 1 RAG columns
    if "regime_at_entry" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN regime_at_entry TEXT")
    if "time_in_trade_hours" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN time_in_trade_hours REAL")
    if "exit_reason" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN exit_reason TEXT")
    if "realized_pnl" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN realized_pnl REAL")
    if "slippage_pct" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN slippage_pct REAL")
    if "closed_at" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN closed_at TEXT")
    if "qty" not in existing:
        conn.execute("ALTER TABLE trades ADD COLUMN qty REAL")


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
    regime_at_entry: str | None = None,
    qty: float | None = None,
) -> None:
    """
    Record a new trade entry.  `regime_at_entry` is stored for contextual
    retrieval in Phase 3 (RAG-lite prompt injection).  All other callers that
    omit this field continue to work unchanged.
    """
    entry_date = trade_date or date.today().isoformat()

    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trades
                        (trade_id, date, ticker, asset_class, conviction_score,
                         original_thesis, pnl_percentage, status, intended_price,
                         regime_at_entry, qty)
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, 'Active', %s, %s, %s)
                    ON CONFLICT (trade_id) DO NOTHING
                """, (trade_id, entry_date, ticker, asset_class,
                      conviction_score, original_thesis, intended_price,
                      regime_at_entry, qty))
    else:
        with _sqlite_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO trades
                    (trade_id, date, ticker, asset_class, conviction_score,
                     original_thesis, pnl_percentage, status, intended_price,
                     regime_at_entry, qty)
                VALUES (?, ?, ?, ?, ?, ?, NULL, 'Active', ?, ?, ?)
            """, (trade_id, entry_date, ticker, asset_class,
                  conviction_score, original_thesis, intended_price,
                  regime_at_entry, qty))

    price_info = f" intended=${intended_price:.4f}" if intended_price else ""
    regime_info = f" regime={regime_at_entry}" if regime_at_entry else ""
    qty_info = f" qty={qty}" if qty else ""
    logger.debug(f"Trade journal | Logged {ticker} [{asset_class}] conv={conviction_score:.2f}{price_info}{regime_info}{qty_info}")


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


# ── update_trade_qty ───────────────────────────────────────────────────────

def update_trade_qty(trade_id: str, qty: float) -> None:
    """Update the qty field once the Alpaca order fill is confirmed."""
    if not qty:
        return
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trades SET qty = %s WHERE trade_id = %s AND qty IS NULL",
                    (qty, trade_id),
                )
                updated = cur.rowcount
        if updated > 0:
            logger.debug(f"Trade journal | qty updated: {trade_id} qty={qty}")
    else:
        with _sqlite_conn() as conn:
            cursor = conn.execute(
                "UPDATE trades SET qty = ? WHERE trade_id = ? AND qty IS NULL",
                (qty, trade_id),
            )
            if cursor.rowcount > 0:
                logger.debug(f"Trade journal | qty updated: {trade_id} qty={qty}")


# ── update_trade_outcome ───────────────────────────────────────────────────

def update_trade_outcome(
    trade_id: str,
    pnl_percentage: float,
    realized_pnl: float | None = None,
) -> None:
    # pnl_percentage sign determines win/loss — real dollar P&L is in realized_pnl.
    # When cost_basis is unavailable from Alpaca, pnl_percentage is ±1.0 sentinel.
    status = "Closed_Win" if pnl_percentage >= 0 else "Closed_Loss"

    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE trades
                    SET pnl_percentage = %s,
                        status         = %s,
                        realized_pnl   = COALESCE(%s, realized_pnl),
                        closed_at      = NOW()
                    WHERE trade_id = %s AND status = 'Active'
                """, (pnl_percentage, status, realized_pnl, trade_id))
                updated = cur.rowcount
        if updated == 0:
            logger.warning(f"Trade journal | No active trade found for id={trade_id}")
        else:
            logger.info(f"Trade journal | Closed {trade_id} → {status} ({pnl_percentage:+.2f}%)")
    else:
        with _sqlite_conn() as conn:
            cursor = conn.execute("""
                UPDATE trades
                SET pnl_percentage = ?,
                    status         = ?,
                    realized_pnl   = COALESCE(?, realized_pnl)
                WHERE trade_id = ? AND status = 'Active'
            """, (pnl_percentage, status, realized_pnl, trade_id))
            if cursor.rowcount == 0:
                logger.warning(f"Trade journal | No active trade for id={trade_id}")
            else:
                logger.info(f"Trade journal | Closed {trade_id} → {status} ({pnl_percentage:+.2f}%)")


# ── close_trade ────────────────────────────────────────────────────────────

def close_trade(
    trade_id: str,
    pnl_percentage: float,
    realized_pnl: float | None = None,
    exit_reason: str | None = None,
    time_in_trade_hours: float | None = None,
    close_price: float | None = None,
    bot_id: str | None = None,
) -> None:
    """
    Comprehensive trade closure.  Records all RAG-phase fields alongside the
    existing pnl_percentage / status update.

    Parameters
    ----------
    trade_id            : must match the trade_id used in log_trade()
    pnl_percentage      : realized P&L as a percentage (positive = win)
    realized_pnl        : dollar amount of realized P&L (optional)
    exit_reason         : 'ratchet_stop' | 'time_exit' | 'algo_cover' |
                          'target_hit' | 'manual' | 'short_scanner_exit'
    time_in_trade_hours : hours the position was held (computed by caller)
    close_price         : fill price at close — used to compute slippage_pct
                          relative to intended_price stored at entry
    """
    # pnl_percentage sign determines win/loss — real dollar P&L is in realized_pnl.
    # When cost_basis is unavailable from Alpaca, pnl_percentage is ±1.0 sentinel.
    status = "Closed_Win" if pnl_percentage >= 0 else "Closed_Loss"

    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Fetch intended_price for slippage computation
                cur.execute(
                    "SELECT intended_price, asset_class FROM trades WHERE trade_id = %s",
                    (trade_id,),
                )
                row = cur.fetchone()
                intended = row[0] if row else None
                asset_class = row[1] if row else None
                slip = None
                if intended and close_price and intended > 0:
                    slip = (close_price - intended) / intended * 100

                cur.execute("""
                    UPDATE trades
                    SET pnl_percentage      = %s,
                        status              = %s,
                        exit_reason         = %s,
                        realized_pnl        = %s,
                        time_in_trade_hours = %s,
                        actual_fill_price   = COALESCE(%s, actual_fill_price),
                        slippage_pct        = %s,
                        closed_at           = NOW()
                    WHERE trade_id = %s AND status = 'Active'
                """, (pnl_percentage, status, exit_reason, realized_pnl,
                      time_in_trade_hours, close_price, slip, trade_id))
                updated = cur.rowcount
        if updated == 0:
            logger.warning(f"Trade journal | close_trade: no active trade for id={trade_id}")
        else:
            logger.info(
                f"Trade journal | Closed {trade_id} → {status} "
                f"({pnl_percentage:+.2f}%) via {exit_reason or 'unknown'}"
            )
            resolved_bot = bot_id or {
                "momentum_equity": "oracle",
                "momentum_etf": "spy_qqq_trend",
            }.get(asset_class)
            if resolved_bot and realized_pnl is not None:
                try:
                    from execution.per_bot_vault import record_profitable_close
                    record_profitable_close(
                        bot_id=resolved_bot,
                        source_trade_id=trade_id,
                        realized_profit=float(realized_pnl),
                    )
                except Exception as exc:
                    logger.error(f"Trade journal | per-bot vault hook failed for {trade_id}: {exc}")
    else:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT intended_price, asset_class FROM trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()
            intended = row["intended_price"] if row else None
            asset_class = row["asset_class"] if row else None
            slip = None
            if intended and close_price and intended > 0:
                slip = (close_price - intended) / intended * 100
            cursor = conn.execute("""
                UPDATE trades
                SET pnl_percentage      = ?,
                    status              = ?,
                    exit_reason         = ?,
                    realized_pnl        = ?,
                    time_in_trade_hours = ?,
                    actual_fill_price   = COALESCE(?, actual_fill_price),
                    slippage_pct        = ?
                WHERE trade_id = ? AND status = 'Active'
            """, (pnl_percentage, status, exit_reason, realized_pnl,
                  time_in_trade_hours, close_price, slip, trade_id))
            if cursor.rowcount == 0:
                logger.warning(f"Trade journal | close_trade: no active trade for id={trade_id}")
            else:
                logger.info(
                    f"Trade journal | Closed {trade_id} → {status} "
                    f"({pnl_percentage:+.2f}%) via {exit_reason or 'unknown'}"
                )
                resolved_bot = bot_id or {
                    "momentum_equity": "oracle",
                    "momentum_etf": "spy_qqq_trend",
                }.get(asset_class)
                if resolved_bot and realized_pnl is not None:
                    try:
                        from execution.per_bot_vault import record_profitable_close
                        record_profitable_close(
                            bot_id=resolved_bot,
                            source_trade_id=trade_id,
                            realized_profit=float(realized_pnl),
                        )
                    except Exception as exc:
                        logger.error(f"Trade journal | per-bot vault hook failed for {trade_id}: {exc}")


# ── log_post_mortem ────────────────────────────────────────────────────────

def log_post_mortem(
    ticker: str,
    regime: str,
    hardcoded_lesson_text: str,
    asset_class: str | None = None,
    exit_reason: str | None = None,
    pnl_pct: float | None = None,
    time_in_trade_hours: float | None = None,
) -> None:
    """
    Write a deterministic Python-generated lesson to execution_post_mortems.
    Phase 2 will call this immediately after every close_trade().
    Phase 3 will query it to build context-aware LLM prompts.
    Phase 4 will promote recurring entries to permanent system-prompt rules.
    """
    if _use_pg():
        from db.postgres import insert_post_mortem
        insert_post_mortem(
            ticker=ticker,
            regime=regime,
            hardcoded_lesson_text=hardcoded_lesson_text,
            asset_class=asset_class,
            exit_reason=exit_reason,
            pnl_pct=pnl_pct,
            time_in_trade_hours=time_in_trade_hours,
        )
    else:
        with _sqlite_conn() as conn:
            conn.execute("""
                INSERT INTO execution_post_mortems
                    (ticker, regime, asset_class, exit_reason,
                     pnl_pct, time_in_trade_hours, hardcoded_lesson_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ticker, regime, asset_class, exit_reason,
                  pnl_pct, time_in_trade_hours, hardcoded_lesson_text))
        logger.debug(
            f"Trade journal | Post-mortem (SQLite): {ticker} [{regime}] "
            f"— {hardcoded_lesson_text[:80]}"
        )


def get_post_mortems(
    regime: str | None = None,
    ticker: str | None = None,
    asset_class: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Retrieve execution post-mortems with optional regime / ticker / asset_class
    filters.  Used by Phase 3 for context-aware prompt injection.
    """
    if _use_pg():
        from db.postgres import get_post_mortems as _pg_get
        return _pg_get(regime=regime, ticker=ticker, asset_class=asset_class, limit=limit)

    # SQLite fallback
    conditions, params = [], []
    if regime:
        conditions.append("regime = ?")
        params.append(regime)
    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker)
    if asset_class:
        conditions.append("asset_class = ?")
        params.append(asset_class)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    cols = ("id", "ts", "ticker", "regime", "asset_class", "exit_reason",
            "pnl_pct", "time_in_trade_hours", "hardcoded_lesson_text")
    with _sqlite_conn() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM execution_post_mortems "
            f"{where} ORDER BY ts DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(zip(cols, tuple(r))) for r in rows]


# ── Queries ────────────────────────────────────────────────────────────────

def _slippage(d: dict) -> dict:
    ip, fp = d.get("intended_price"), d.get("actual_fill_price")
    d["slippage_pct"] = (fp - ip) / ip * 100 if (ip and fp and ip > 0) else None
    return d


def get_recent_losses(limit: int = 5) -> list[dict]:
    return _query_trades("Closed_Loss", limit)


def get_recent_wins(limit: int = 5) -> list[dict]:
    return _query_trades("Closed_Win", limit)


# ── Phase 3: Contextual (regime-matched) queries ────────────────────────────

_CONTEXTUAL_COLS = (
    "trade_id", "date", "ticker", "asset_class", "conviction_score",
    "original_thesis", "pnl_percentage", "intended_price", "actual_fill_price",
    "regime_at_entry", "exit_reason", "time_in_trade_hours",
)


def _contextual_query(
    status: str,
    regime: str,
    priority_asset_class: str | None,
    limit: int,
) -> list[dict]:
    """
    Query trades WHERE status = status AND regime_at_entry = regime.
    If priority_asset_class is given, those rows sort first.
    Returns an empty list if no regime-matched rows exist (caller handles fallback).
    """
    cols = _CONTEXTUAL_COLS
    pri = priority_asset_class or ""

    if _use_pg():
        from db.postgres import get_conn
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT {', '.join(cols)}
                        FROM   trades
                        WHERE  status = %s AND regime_at_entry = %s
                        ORDER  BY
                            CASE WHEN asset_class = %s THEN 0 ELSE 1 END,
                            date DESC
                        LIMIT  %s
                    """, (status, regime, pri, limit))
                    rows = cur.fetchall()
            return [_slippage(dict(zip(cols, r))) for r in rows]
        except Exception as exc:
            logger.warning(f"Trade journal | contextual query failed: {exc}")
            return []
    else:
        try:
            with _sqlite_conn() as conn:
                rows = conn.execute(f"""
                    SELECT {', '.join(cols)}
                    FROM trades
                    WHERE status = ? AND regime_at_entry = ?
                    ORDER BY
                        CASE WHEN asset_class = ? THEN 0 ELSE 1 END,
                        date DESC
                    LIMIT ?
                """, (status, regime, pri, limit)).fetchall()
            return [_slippage(dict(r)) for r in rows]
        except Exception as exc:
            logger.warning(f"Trade journal | contextual query (SQLite) failed: {exc}")
            return []


def get_contextual_losses(
    regime: str,
    priority_asset_class: str | None = None,
    limit: int = 5,
) -> tuple[list[dict], bool]:
    """
    Return (rows, regime_matched) where rows are losses with regime_at_entry = regime.
    If no regime-matched rows exist, falls back to plain FIFO and sets regime_matched=False.
    Each row has all _CONTEXTUAL_COLS plus slippage_pct.
    """
    rows = _contextual_query("Closed_Loss", regime, priority_asset_class, limit)
    if rows:
        return rows, True
    return _query_trades("Closed_Loss", limit), False


def get_contextual_wins(
    regime: str,
    priority_asset_class: str | None = None,
    limit: int = 3,
) -> tuple[list[dict], bool]:
    """
    Return (rows, regime_matched) where rows are wins with regime_at_entry = regime.
    If no regime-matched rows exist, falls back to plain FIFO and sets regime_matched=False.
    """
    rows = _contextual_query("Closed_Win", regime, priority_asset_class, limit)
    if rows:
        return rows, True
    return _query_trades("Closed_Win", limit), False


def get_recent_trades_combined(limit: int = 20) -> list[dict]:
    """Last N closed trades (wins + losses combined) ordered by date DESC.
    Used by the /journal/recent endpoint for streak computation and Kill Board."""
    cols = ("trade_id", "date", "ticker", "pnl_percentage", "status",
            "realized_pnl", "exit_reason")
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(cols)}
                    FROM   trades
                    WHERE  status IN ('Closed_Win', 'Closed_Loss', 'Closed')
                    ORDER  BY date DESC
                    LIMIT  %s
                """, (limit,))
                rows = cur.fetchall()
        raw = [dict(zip(cols, r)) for r in rows]
    else:
        with _sqlite_conn() as conn:
            rows = conn.execute(f"""
                SELECT {', '.join(cols)}
                FROM trades WHERE status IN ('Closed_Win', 'Closed_Loss', 'Closed')
                ORDER BY date DESC LIMIT ?
            """, (limit,)).fetchall()
        raw = [dict(r) for r in rows]

    # Normalise to the contract expected by the dashboard:
    # symbol / pnl_pct / pnl_usd / exit_reason / closed_at
    result = []
    for r in raw:
        status = r["status"]
        pnl = r["pnl_percentage"]
        if status == "Closed":
            if pnl is not None:
                status = "Closed_Win" if pnl > 0 else "Closed_Loss"
            else:
                continue
        result.append({
            "trade_id":    r["trade_id"],
            "symbol":      r["ticker"],
            "pnl_pct":     pnl,
            "pnl_usd":     r.get("realized_pnl"),
            "exit_reason": r.get("exit_reason"),
            "closed_at":   str(r["date"]),
            "status":      status,
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
            "original_thesis", "intended_price", "actual_fill_price", "qty")
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
                       original_thesis, intended_price, actual_fill_price, qty
                FROM trades WHERE status = 'Active' ORDER BY date DESC
            """).fetchall()
        return [dict(r) for r in rows]


def find_active_trade_by_ticker(ticker: str) -> Optional[str]:
    """
    Fallback for execute_exits() when trade_id is missing.
    Returns the trade_id of the most recently opened Active trade for this ticker.
    Returns None if no Active trade exists for this ticker.
    """
    try:
        if _use_pg():
            from db.postgres import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT trade_id FROM trades
                        WHERE ticker = %s AND status = 'Active'
                        ORDER BY date DESC, trade_id DESC
                        LIMIT 1
                    """, (ticker,))
                    row = cur.fetchone()
                    return row[0] if row else None
        else:
            with _sqlite_conn() as conn:
                row = conn.execute("""
                    SELECT trade_id FROM trades
                    WHERE ticker = ? AND status = 'Active'
                    ORDER BY date DESC, trade_id DESC
                    LIMIT 1
                """, (ticker,)).fetchone()
                return row[0] if row else None
    except Exception as exc:
        logger.error(f"find_active_trade_by_ticker({ticker}) failed: {exc}")
        return None


def delete_trade(trade_id: str) -> bool:
    """
    Delete a trade row entirely. Used for rollback when Alpaca cancels/rejects
    an order before fill, preventing phantom-Active rows from accumulating.
    Returns True if a row was deleted, False otherwise.
    """
    try:
        if _use_pg():
            from db.postgres import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM trades WHERE trade_id = %s", (trade_id,))
                    return cur.rowcount > 0
        else:
            with _sqlite_conn() as conn:
                cur = conn.execute("DELETE FROM trades WHERE trade_id = ?", (trade_id,))
                conn.commit()
                return cur.rowcount > 0
    except Exception as exc:
        logger.error(f"delete_trade({trade_id}) failed: {exc}")
        return False


def get_all_trades(limit: int = 200) -> list[dict]:
    cols = ("trade_id", "date", "ticker", "asset_class", "conviction_score",
            "original_thesis", "pnl_percentage", "status",
            "intended_price", "actual_fill_price",
            "realized_pnl", "exit_reason")
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
    """
    Returns aggregated trade stats.
    Includes best_trade_usd / best_trade_symbol and worst_trade_usd / worst_trade_symbol
    so the dashboard can display server-computed extremes without client-side reduce() calls.
    """
    if _use_pg():
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*)                                           AS total,
                        SUM(CASE WHEN status = 'Active'      THEN 1 END)  AS active,
                        SUM(CASE WHEN status = 'Closed_Win' OR (status = 'Closed' AND pnl_percentage > 0) THEN 1 END) AS wins,
                        SUM(CASE WHEN status = 'Closed_Loss' OR (status = 'Closed' AND pnl_percentage <= 0) THEN 1 END) AS losses,
                        AVG(CASE WHEN status != 'Active' THEN pnl_percentage END) AS avg_pnl
                    FROM trades
                """)
                row = cur.fetchone()
                keys = ("total", "active", "wins", "losses", "avg_pnl")
                result = dict(zip(keys, row))

                # Best and worst trade by realized_pnl (all-time, closed trades only)
                cur.execute("""
                    SELECT ticker, realized_pnl FROM trades
                    WHERE status LIKE 'Closed_%' AND realized_pnl IS NOT NULL
                    ORDER BY realized_pnl DESC LIMIT 1
                """)
                best_row = cur.fetchone()
                cur.execute("""
                    SELECT ticker, realized_pnl FROM trades
                    WHERE status LIKE 'Closed_%' AND realized_pnl IS NOT NULL
                    ORDER BY realized_pnl ASC LIMIT 1
                """)
                worst_row = cur.fetchone()
                result["best_trade_symbol"] = best_row[0]  if best_row  else None
                result["best_trade_usd"]    = float(best_row[1])  if best_row  else None
                result["worst_trade_symbol"]= worst_row[0] if worst_row else None
                result["worst_trade_usd"]   = float(worst_row[1]) if worst_row else None

                # Null P&L audit — closed trades with no realized dollar amount
                cur.execute("""
                    SELECT COUNT(*) FROM trades
                    WHERE status LIKE 'Closed_%' AND realized_pnl IS NULL
                """)
                _nc = cur.fetchone()
                cur.execute("""
                    SELECT trade_id FROM trades
                    WHERE status LIKE 'Closed_%' AND realized_pnl IS NULL
                    ORDER BY date DESC LIMIT 20
                """)
                result["null_pnl_count"]     = int(_nc[0]) if _nc else 0
                result["null_pnl_trade_ids"] = [r[0] for r in cur.fetchall()]
        return result
    else:
        with _sqlite_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN status='Active' THEN 1 END) AS active,
                    SUM(CASE WHEN status='Closed_Win' OR (status='Closed' AND pnl_percentage > 0) THEN 1 END) AS wins,
                    SUM(CASE WHEN status='Closed_Loss' OR (status='Closed' AND pnl_percentage <= 0) THEN 1 END) AS losses,
                    AVG(CASE WHEN status!='Active' THEN pnl_percentage END) AS avg_pnl
                FROM trades
            """).fetchone()
            result = dict(row)
            best_row = conn.execute(
                "SELECT ticker, realized_pnl FROM trades WHERE status LIKE 'Closed_%' AND realized_pnl IS NOT NULL ORDER BY realized_pnl DESC LIMIT 1"
            ).fetchone()
            worst_row = conn.execute(
                "SELECT ticker, realized_pnl FROM trades WHERE status LIKE 'Closed_%' AND realized_pnl IS NOT NULL ORDER BY realized_pnl ASC LIMIT 1"
            ).fetchone()
            result["best_trade_symbol"]  = best_row[0]        if best_row  else None
            result["best_trade_usd"]     = float(best_row[1]) if best_row  else None
            result["worst_trade_symbol"] = worst_row[0]        if worst_row else None
            result["worst_trade_usd"]    = float(worst_row[1]) if worst_row else None
            # Null P&L audit (SQLite path)
            result["null_pnl_count"] = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status LIKE 'Closed_%' AND realized_pnl IS NULL"
            ).fetchone()[0] or 0
            _null_ids = conn.execute(
                "SELECT trade_id FROM trades WHERE status LIKE 'Closed_%' AND realized_pnl IS NULL ORDER BY date DESC LIMIT 20"
            ).fetchall()
            result["null_pnl_trade_ids"] = [r[0] for r in _null_ids]
        return result


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
