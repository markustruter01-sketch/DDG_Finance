"""
ATR Ratchet Trailing Stop — Module 4
--------------------------------------
v4.3 — Leveraged Risk 1.5× ATR Override

Replaces the static 2%-below-fill GTC stop with a volatility-aware
trailing stop that ONLY moves in the trade's favour (up for longs).

Ratchet Mechanism
-----------------
  1. At fill time, compute ATR(14) for the symbol using the last 30 days
     of daily close prices (via yfinance).
  2. Initial stop = fill_price − (ATR_MULTIPLIER × ATR).
  3. On every subsequent cycle, if current_price − (ATR_MULTIPLIER × ATR)
     > stored stop → update stop (ratchet up).
  4. If the calculated stop would DECREASE (volatility expansion or price
     drop) → KEEP the existing stop (the ratchet never widens).

Leveraged Risk Override (v4.3)
------------------------------
  Tickers in LEVERAGED_RISK_TICKERS (TQQQ, SOXL, UPRO) use a tighter
  ATR multiplier of 1.5× instead of the standard 2.0×.  This gives
  leveraged ETFs a tighter leash to survive intraday whipsaws while
  protecting against structural crashes.

  The multiplier is auto-detected from the ticker in both
  initialise_ratchet_stop() and maybe_ratchet(), so callers do not need
  to specify it explicitly.

Persistence
-----------
  Ratchet state is stored in the `ratchet_stops` table (PostgreSQL primary,
  SQLite fallback).  The executor reads this table before each cycle to
  cancel-and-replace stale stops that have been ratcheted upward.

Schema
------
  ratchet_stops (
      symbol        TEXT PRIMARY KEY,
      stop_price    REAL NOT NULL,
      fill_price    REAL NOT NULL,
      atr           REAL NOT NULL,
      atr_multiplier REAL NOT NULL DEFAULT 2.0,
      last_updated  TEXT NOT NULL    -- ISO date
  )
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
from loguru import logger

ATR_MULTIPLIER:           float = 2.0   # Standard multiplier for all tickers
LEVERAGED_ATR_MULTIPLIER: float = 1.5   # Tighter multiplier for leveraged ETFs
ATR_PERIOD:               int   = 14
ATR_LOOKBACK_DAYS:        int   = 30     # yfinance fetch window (extra buffer)
FALLBACK_STOP_PCT:        float = 0.02   # 2% static fallback if ATR unavailable

# Tickers that use LEVERAGED_ATR_MULTIPLIER
LEVERAGED_RISK_TICKERS: frozenset[str] = frozenset({"TQQQ", "SOXL", "UPRO"})


def _resolve_atr_multiplier(ticker: str) -> float:
    """
    Return the appropriate ATR multiplier for *ticker*.
    Leveraged ETFs get 1.5×; everything else gets the standard 2.0×.
    """
    multiplier = LEVERAGED_ATR_MULTIPLIER if ticker in LEVERAGED_RISK_TICKERS else ATR_MULTIPLIER
    return multiplier


# ── ATR computation ────────────────────────────────────────────────────────

def compute_atr(ticker: str) -> Optional[float]:
    """
    Compute ATR(14) for *ticker* using the most recent 30 days of daily data.
    Returns None if data is unavailable.
    """
    try:
        import yfinance as yf

        symbol = ticker.replace("/", "-")  # BTC/USD → BTC-USD for yfinance
        hist = yf.Ticker(symbol).history(period="30d", interval="1d", auto_adjust=True)
        if hist is None or len(hist) < ATR_PERIOD + 1:
            logger.warning(f"Ratchet | Insufficient data for ATR({ATR_PERIOD}) on {ticker}")
            return None

        high   = hist["High"].values
        low    = hist["Low"].values
        close  = hist["Close"].values

        tr_list = []
        for i in range(1, len(close)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i]  - close[i - 1]),
            )
            tr_list.append(tr)

        if len(tr_list) < ATR_PERIOD:
            return None

        # Wilder's smoothed ATR
        atr = float(np.mean(tr_list[-ATR_PERIOD:]))
        logger.debug(f"Ratchet | ATR({ATR_PERIOD}) for {ticker} = {atr:.4f}")
        return atr

    except Exception as exc:
        logger.warning(f"Ratchet | ATR computation failed for {ticker}: {exc}")
        return None


# ── Stop price helpers ─────────────────────────────────────────────────────

def compute_initial_stop(
    fill_price: float,
    atr: Optional[float],
    atr_multiplier: float = ATR_MULTIPLIER,
) -> float:
    if atr is not None:
        stop = fill_price - atr_multiplier * atr
    else:
        stop = fill_price * (1.0 - FALLBACK_STOP_PCT)
    return max(stop, 0.01)


def ratchet_stop(
    current_price: float,
    atr: Optional[float],
    existing_stop: float,
    atr_multiplier: float = ATR_MULTIPLIER,
) -> float:
    """
    Compute a new stop using current_price − atr_multiplier×ATR.
    If the new stop would be LOWER than existing_stop (ratchet never widens),
    return existing_stop unchanged.
    """
    new_stop = compute_initial_stop(current_price, atr, atr_multiplier)
    if new_stop > existing_stop:
        logger.debug(
            f"Ratchet | Stop ratcheted UP: ${existing_stop:.4f} → ${new_stop:.4f}"
        )
        return new_stop
    logger.debug(
        f"Ratchet | Ratchet held — new_stop=${new_stop:.4f} ≤ existing=${existing_stop:.4f}"
    )
    return existing_stop


# ── Persistence ────────────────────────────────────────────────────────────

def _ensure_table_pg(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ratchet_stops (
                symbol         TEXT PRIMARY KEY,
                stop_price     DOUBLE PRECISION NOT NULL,
                fill_price     DOUBLE PRECISION NOT NULL,
                atr            DOUBLE PRECISION NOT NULL,
                atr_multiplier DOUBLE PRECISION NOT NULL DEFAULT 2.0,
                last_updated   DATE NOT NULL
            )
        """)
        # Add atr_multiplier column if upgrading from older schema
        cur.execute("""
            ALTER TABLE ratchet_stops
            ADD COLUMN IF NOT EXISTS atr_multiplier DOUBLE PRECISION NOT NULL DEFAULT 2.0
        """)
    conn.commit()


def _ensure_table_sqlite(db_path) -> None:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ratchet_stops (
                symbol         TEXT PRIMARY KEY,
                stop_price     REAL NOT NULL,
                fill_price     REAL NOT NULL,
                atr            REAL NOT NULL,
                atr_multiplier REAL NOT NULL DEFAULT 2.0,
                last_updated   TEXT NOT NULL
            )
        """)
        # Add atr_multiplier column if upgrading from older schema
        try:
            conn.execute("ALTER TABLE ratchet_stops ADD COLUMN atr_multiplier REAL NOT NULL DEFAULT 2.0")
        except Exception:
            pass  # Column already exists
        conn.commit()


def save_stop(
    symbol: str,
    stop_price: float,
    fill_price: float,
    atr: float,
    atr_multiplier: float = ATR_MULTIPLIER,
) -> None:
    today = date.today().isoformat()
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ratchet_stops (symbol, stop_price, fill_price, atr, atr_multiplier, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol) DO UPDATE SET
                            stop_price     = EXCLUDED.stop_price,
                            fill_price     = EXCLUDED.fill_price,
                            atr            = EXCLUDED.atr,
                            atr_multiplier = EXCLUDED.atr_multiplier,
                            last_updated   = EXCLUDED.last_updated
                    """, (symbol, stop_price, fill_price, atr, atr_multiplier, today))
                conn.commit()
            logger.debug(f"Ratchet | Saved stop for {symbol}: ${stop_price:.4f} mult={atr_multiplier}× (pg)")
            return
    except Exception as exc:
        logger.warning(f"Ratchet | PG save failed for {symbol}: {exc} — falling back to SQLite")

    _save_stop_sqlite(symbol, stop_price, fill_price, atr, atr_multiplier, today)


def _save_stop_sqlite(symbol, stop_price, fill_price, atr, atr_multiplier, today) -> None:
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).parent.parent / "trade_journal.db"
    _ensure_table_sqlite(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO ratchet_stops (symbol, stop_price, fill_price, atr, atr_multiplier, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                stop_price     = excluded.stop_price,
                fill_price     = excluded.fill_price,
                atr            = excluded.atr,
                atr_multiplier = excluded.atr_multiplier,
                last_updated   = excluded.last_updated
        """, (symbol, stop_price, fill_price, atr, atr_multiplier, today))
        conn.commit()
    logger.debug(f"Ratchet | Saved stop for {symbol}: ${stop_price:.4f} mult={atr_multiplier}× (sqlite)")


def get_stop(symbol: str) -> Optional[dict]:
    """Return the persisted ratchet stop for *symbol*, or None if not tracked."""
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, last_updated "
                        "FROM ratchet_stops WHERE symbol = %s",
                        (symbol,),
                    )
                    row = cur.fetchone()
            if row:
                return {
                    "symbol":         row[0],
                    "stop_price":     row[1],
                    "fill_price":     row[2],
                    "atr":            row[3],
                    "atr_multiplier": row[4],
                    "last_updated":   str(row[5]),
                }
            return None
    except Exception as exc:
        logger.warning(f"Ratchet | PG get failed for {symbol}: {exc} — falling back to SQLite")

    return _get_stop_sqlite(symbol)


def _get_stop_sqlite(symbol: str) -> Optional[dict]:
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).parent.parent / "trade_journal.db"
    if not db_path.exists():
        return None
    _ensure_table_sqlite(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, last_updated "
            "FROM ratchet_stops WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    return dict(row) if row else None


def load_all_stops() -> dict[str, dict]:
    result: dict[str, dict] = {}
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, last_updated "
                        "FROM ratchet_stops"
                    )
                    for row in cur.fetchall():
                        result[row[0]] = {
                            "symbol":         row[0],
                            "stop_price":     row[1],
                            "fill_price":     row[2],
                            "atr":            row[3],
                            "atr_multiplier": row[4],
                            "last_updated":   str(row[5]),
                        }
            return result
    except Exception as exc:
        logger.warning(f"Ratchet | PG load_all failed: {exc}")
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent / "trade_journal.db"
        if db_path.exists():
            _ensure_table_sqlite(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute(
                    "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, last_updated "
                    "FROM ratchet_stops"
                ):
                    result[row["symbol"]] = dict(row)
    except Exception:
        pass
    return result


def delete_stop(symbol: str) -> None:
    """Remove ratchet stop when a position is closed."""
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM ratchet_stops WHERE symbol = %s", (symbol,))
                conn.commit()
            return
    except Exception as exc:
        logger.warning(f"Ratchet | PG delete failed for {symbol}: {exc}")

    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent / "trade_journal.db"
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM ratchet_stops WHERE symbol = ?", (symbol,))
                conn.commit()
    except Exception as exc:
        logger.warning(f"Ratchet | SQLite delete failed for {symbol}: {exc}")


# ── High-level helpers ─────────────────────────────────────────────────────

def initialise_ratchet_stop(
    ticker: str,
    fill_price: float,
    qty: float,
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Called immediately after a new position is filled.
    Computes ATR, sets initial stop, persists it, and places a GTC stop order.

    Leveraged ETFs (TQQQ, SOXL, UPRO) automatically use LEVERAGED_ATR_MULTIPLIER (1.5×)
    instead of the standard ATR_MULTIPLIER (2.0×).

    Returns the stop dict or None on failure.
    """
    atr_mult   = _resolve_atr_multiplier(ticker)
    atr        = compute_atr(ticker)
    stop_price = compute_initial_stop(fill_price, atr, atr_mult)
    atr_used   = atr if atr is not None else 0.0

    label = f"{atr_mult}×ATR" if atr else f"{FALLBACK_STOP_PCT:.0%} fallback"
    is_letf = ticker in LEVERAGED_RISK_TICKERS
    logger.info(
        f"Ratchet | {ticker} initial stop=${stop_price:.4f} "
        f"(fill=${fill_price:.4f}, {label}={atr_used:.4f})"
        + (" [LETF 1.5× tighter stop]" if is_letf else "")
    )

    save_stop(ticker, stop_price, fill_price, atr_used, atr_mult)

    if not dry_run:
        try:
            from execution.broker import place_stop_order
            result = place_stop_order(ticker, qty, stop_price)
            logger.info(f"Ratchet | GTC stop placed for {ticker}: {result['id']}")
            return {
                "stop_price":     stop_price,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "order":          result,
            }
        except Exception as exc:
            logger.error(f"Ratchet | Failed to place stop order for {ticker}: {exc}")
            return {
                "stop_price":     stop_price,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "order":          None,
            }

    return {
        "stop_price":     stop_price,
        "atr":            atr_used,
        "atr_multiplier": atr_mult,
        "order":          None,
        "dry_run":        True,
    }


def maybe_ratchet(ticker: str, current_price: float, qty: float, dry_run: bool = False) -> Optional[dict]:
    """
    Called on every cycle for active overheated positions.
    Ratchets the stop upward if current_price warrants it, then
    cancels the old GTC stop order and places a new one at the higher price.

    The ATR multiplier is restored from the persisted stop record, so leveraged
    ETFs automatically continue to use 1.5× for all subsequent ratchets.

    Returns updated stop dict, or None if no ratchet was needed.
    """
    existing = get_stop(ticker)
    if existing is None:
        logger.debug(f"Ratchet | No tracked stop for {ticker} — skipping ratchet")
        return None

    # Restore the multiplier that was used when the stop was initialised
    atr_mult = existing.get("atr_multiplier", _resolve_atr_multiplier(ticker))

    atr      = compute_atr(ticker)
    new_stop = ratchet_stop(current_price, atr, existing["stop_price"], atr_mult)

    if new_stop <= existing["stop_price"]:
        return None  # no change needed

    atr_used = atr if atr is not None else existing.get("atr", 0.0)
    save_stop(ticker, new_stop, existing["fill_price"], atr_used, atr_mult)

    if not dry_run:
        try:
            from execution.broker import place_stop_order, cancel_all_orders
            cancel_all_orders()   # cancel existing stop for this ticker
            result = place_stop_order(ticker, qty, new_stop)
            logger.info(
                f"Ratchet | {ticker} stop ratcheted "
                f"${existing['stop_price']:.4f} → ${new_stop:.4f} "
                f"| mult={atr_mult}× | new order {result['id']}"
            )
            return {
                "stop_price":     new_stop,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "order":          result,
            }
        except Exception as exc:
            logger.error(f"Ratchet | Failed to ratchet stop for {ticker}: {exc}")

    return {
        "stop_price":     new_stop,
        "atr":            atr_used,
        "atr_multiplier": atr_mult,
        "order":          None,
        "dry_run":        True,
    }
