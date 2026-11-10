"""
Trade Journal — PostgreSQL
--------------------------
All trade journal state is persisted in PostgreSQL. Database failures are
propagated so live trading cannot silently report success without durable state.
"""

from datetime import date
from typing import Optional

from loguru import logger

# ── Schema init ────────────────────────────────────────────────────────────


def init_db() -> None:
    from db.postgres import session_read_only
    if session_read_only():
        # Replit workspace guard (.replit [userenv.development] PGOPTIONS): no startup DDL on live data.
        logger.warning("Trade journal | read-only session: schema and vault setup skipped")
        return
    try:
        from db.postgres import ensure_schema
        ensure_schema()
    except Exception as exc:
        logger.critical(f"Trade journal | PostgreSQL schema initialization failed: {exc}")
        raise
    logger.info("Trade journal | Using PostgreSQL backend")

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

    price_info = f" intended=${intended_price:.4f}" if intended_price else ""
    regime_info = f" regime={regime_at_entry}" if regime_at_entry else ""
    qty_info = f" qty={qty}" if qty else ""
    logger.debug(f"Trade journal | Logged {ticker} [{asset_class}] conv={conviction_score:.2f}{price_info}{regime_info}{qty_info}")


# ── update_trade_fill_price ────────────────────────────────────────────────

def update_trade_fill_price(trade_id: str, actual_fill_price: float) -> None:
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


# ── update_trade_qty ───────────────────────────────────────────────────────

def update_trade_qty(trade_id: str, qty: float) -> None:
    """Update the qty field once the Alpaca order fill is confirmed."""
    if not qty:
        return
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


# ── update_trade_outcome ───────────────────────────────────────────────────

def update_trade_outcome(
    trade_id: str,
    pnl_percentage: float,
    realized_pnl: float | None = None,
) -> None:
    # pnl_percentage sign determines win/loss — real dollar P&L is in realized_pnl.
    # When cost_basis is unavailable from Alpaca, pnl_percentage is ±1.0 sentinel.
    status = "Closed_Win" if pnl_percentage >= 0 else "Closed_Loss"

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
        # VAULT-V2 retired the per-trade vault skim; the vault now takes 10% of
        # each account's monthly new high on equity (execution/per_bot_vault.py).


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
    from db.postgres import get_post_mortems as _pg_get
    return _pg_get(regime=regime, ticker=ticker, asset_class=asset_class, limit=limit)


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
        logger.critical(f"Trade journal | contextual query failed: {exc}")
        raise


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


def get_all_active_trades() -> list[dict]:
    cols = ("trade_id", "date", "ticker", "asset_class", "conviction_score",
            "original_thesis", "intended_price", "actual_fill_price", "qty")
    from db.postgres import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT {', '.join(cols)} FROM trades
                WHERE status = 'Active' ORDER BY date DESC
            """)
            rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def find_active_trade_by_ticker(ticker: str) -> Optional[str]:
    """
    Fallback for execute_exits() when trade_id is missing.
    Returns the trade_id of the most recently opened Active trade for this ticker.
    Returns None if no Active trade exists for this ticker.
    """
    try:
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
    except Exception as exc:
        logger.critical(f"find_active_trade_by_ticker({ticker}) failed: {exc}")
        raise


def delete_trade(trade_id: str) -> bool:
    """
    Delete a trade row entirely. Used for rollback when Alpaca cancels/rejects
    an order before fill, preventing phantom-Active rows from accumulating.
    Returns True if a row was deleted, False otherwise.
    """
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM trades WHERE trade_id = %s", (trade_id,))
                return cur.rowcount > 0
    except Exception as exc:
        logger.critical(f"delete_trade({trade_id}) failed: {exc}")
        raise


def get_all_trades(limit: int = 200) -> list[dict]:
    cols = ("trade_id", "date", "ticker", "asset_class", "conviction_score",
            "original_thesis", "pnl_percentage", "status",
            "intended_price", "actual_fill_price",
            "realized_pnl", "exit_reason")
    from db.postgres import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT {', '.join(cols)} FROM trades
                ORDER BY date DESC LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
    return [_slippage(dict(zip(cols, r))) for r in rows]


def get_journal_summary() -> dict:
    """
    Returns aggregated trade stats.
    Includes best_trade_usd / best_trade_symbol and worst_trade_usd / worst_trade_symbol
    so the dashboard can display server-computed extremes without client-side reduce() calls.
    """
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


def get_slippage_stats() -> dict:
    base_q = """
        WHERE intended_price IS NOT NULL
          AND actual_fill_price IS NOT NULL
          AND intended_price > 0
          AND status != 'Active'
    """
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

    logger.info(
        f"Performance snapshot saved | {snap_date} equity=${equity:,.2f} "
        f"daily={daily_pnl_pct:+.2f}% cum={cumulative_pnl_pct:+.2f}% wr={win_rate:.1%}"
    )


def get_performance_snapshots(limit: int = 90, *, latest: bool = False) -> list[dict]:
    cols = ("date", "equity", "daily_pnl_pct", "cumulative_pnl_pct",
            "win_rate", "trades_placed")
    from db.postgres import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            if latest:
                cur.execute(f"""
                    SELECT {', '.join(cols)}
                    FROM (
                        SELECT {', '.join(cols)} FROM performance_snapshots
                        ORDER BY date DESC LIMIT %s
                    ) recent
                    ORDER BY date ASC
                """, (limit,))
            else:
                cur.execute(f"""
                    SELECT {', '.join(cols)} FROM performance_snapshots
                    ORDER BY date ASC LIMIT %s
                """, (limit,))
            rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def get_performance_summary() -> dict:
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
    return result