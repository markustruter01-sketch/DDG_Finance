"""
ATR Ratchet Trailing Stop — Module 4
--------------------------------------
v4.4 — Short Side Support + Leveraged Risk 1.5× ATR Override

Replaces the static 2%-below-fill GTC stop with a volatility-aware
trailing stop that ONLY moves in the trade's favour.

Ratchet Mechanism — LONG (default)
------------------------------------
  Initial stop = fill_price − (ATR_MULTIPLIER × ATR)
  Ratchet: update only when new_stop > existing_stop (ratchet up).

Ratchet Mechanism — SHORT (side="short")
-----------------------------------------
  Initial stop = fill_price + (ATR_MULTIPLIER × ATR)   ← above fill
  Ratchet: update only when new_stop < existing_stop (ratchet down).
  This protects a short: if price rises above the stop-buy, the loss is capped.

Leveraged Risk Override (v4.3)
------------------------------
  TQQQ, SOXL, UPRO use 1.5× multiplier instead of 2.0×.

Persistence
-----------
  ratchet_stops table (PostgreSQL primary, SQLite fallback).

Schema
------
  ratchet_stops (
      symbol        TEXT PRIMARY KEY,
      stop_price    REAL NOT NULL,
      fill_price    REAL NOT NULL,
      atr           REAL NOT NULL,
      atr_multiplier REAL NOT NULL DEFAULT 2.0,
      side          TEXT NOT NULL DEFAULT 'long',
      last_updated  TEXT NOT NULL    -- ISO date
  )
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
from loguru import logger

ATR_MULTIPLIER:           float = 2.5   # Standard multiplier for all tickers  [STORM MODE: 2.0→2.5 Wide-Lung ATR]
LEVERAGED_ATR_MULTIPLIER: float = 2.0   # Tighter multiplier for leveraged ETFs  [STORM MODE: 1.5→2.0]
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
    side: str = "long",
) -> float:
    if side == "short":
        # For shorts: stop is ABOVE fill price (stop-buy to cap loss)
        if atr is not None:
            stop = fill_price + atr_multiplier * atr
        else:
            stop = fill_price * (1.0 + FALLBACK_STOP_PCT)
        return max(stop, 0.01)
    else:
        # For longs: stop is BELOW fill price
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
    side: str = "long",
) -> float:
    """
    Compute a new stop for the given side.

    LONG:  Stop moves UP when price rises (ratchet never widens downward).
    SHORT: Stop moves DOWN when price falls (ratchet never widens upward).
    """
    new_stop = compute_initial_stop(current_price, atr, atr_multiplier, side=side)

    if side == "short":
        # Short: we want stop to ratchet DOWN (in our favour as price falls)
        if new_stop < existing_stop:
            logger.debug(
                f"Ratchet | SHORT stop ratcheted DOWN: ${existing_stop:.4f} → ${new_stop:.4f}"
            )
            return new_stop
        logger.debug(
            f"Ratchet | SHORT ratchet held — new_stop=${new_stop:.4f} ≥ existing=${existing_stop:.4f}"
        )
        return existing_stop
    else:
        # Long: we want stop to ratchet UP
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
                side           TEXT NOT NULL DEFAULT 'long',
                last_updated   DATE NOT NULL
            )
        """)
        # Safe schema migrations for upgrades from older schema versions
        cur.execute("""
            ALTER TABLE ratchet_stops
            ADD COLUMN IF NOT EXISTS atr_multiplier DOUBLE PRECISION NOT NULL DEFAULT 2.0
        """)
        cur.execute("""
            ALTER TABLE ratchet_stops
            ADD COLUMN IF NOT EXISTS side TEXT NOT NULL DEFAULT 'long'
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
                side           TEXT NOT NULL DEFAULT 'long',
                last_updated   TEXT NOT NULL
            )
        """)
        for col_ddl in [
            "ALTER TABLE ratchet_stops ADD COLUMN atr_multiplier REAL NOT NULL DEFAULT 2.0",
            "ALTER TABLE ratchet_stops ADD COLUMN side TEXT NOT NULL DEFAULT 'long'",
        ]:
            try:
                conn.execute(col_ddl)
            except Exception:
                pass  # Column already exists
        conn.commit()


def save_stop(
    symbol: str,
    stop_price: float,
    fill_price: float,
    atr: float,
    atr_multiplier: float = ATR_MULTIPLIER,
    side: str = "long",
) -> None:
    today = date.today().isoformat()
    try:
        from db.postgres import get_conn, is_pg_available, record_position_entry
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ratchet_stops (symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol) DO UPDATE SET
                            stop_price     = EXCLUDED.stop_price,
                            fill_price     = EXCLUDED.fill_price,
                            atr            = EXCLUDED.atr,
                            atr_multiplier = EXCLUDED.atr_multiplier,
                            side           = EXCLUDED.side,
                            last_updated   = EXCLUDED.last_updated
                    """, (symbol, stop_price, fill_price, atr, atr_multiplier, side, today))
                conn.commit()
            # Record immutable entry timestamp (ON CONFLICT DO NOTHING keeps the FIRST open time)
            record_position_entry(symbol, entry_price=fill_price)
            logger.debug(f"Ratchet | Saved stop for {symbol}: ${stop_price:.4f} mult={atr_multiplier}× side={side} (pg)")
            return
    except Exception as exc:
        logger.warning(f"Ratchet | PG save failed for {symbol}: {exc} — falling back to SQLite")

    _save_stop_sqlite(symbol, stop_price, fill_price, atr, atr_multiplier, side, today)


def _save_stop_sqlite(symbol, stop_price, fill_price, atr, atr_multiplier, side, today) -> None:
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).parent.parent / "trade_journal.db"
    _ensure_table_sqlite(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO ratchet_stops (symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                stop_price     = excluded.stop_price,
                fill_price     = excluded.fill_price,
                atr            = excluded.atr,
                atr_multiplier = excluded.atr_multiplier,
                side           = excluded.side,
                last_updated   = excluded.last_updated
        """, (symbol, stop_price, fill_price, atr, atr_multiplier, side, today))
        conn.commit()
    logger.debug(f"Ratchet | Saved stop for {symbol}: ${stop_price:.4f} mult={atr_multiplier}× side={side} (sqlite)")


def get_stop(symbol: str) -> Optional[dict]:
    """Return the persisted ratchet stop for *symbol*, or None if not tracked."""
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated "
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
                    "side":           row[5] if row[5] else "long",
                    "last_updated":   str(row[6]),
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
            "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated "
            "FROM ratchet_stops WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if row:
        d = dict(row)
        d.setdefault("side", "long")
        return d
    return None


def load_all_stops() -> dict[str, dict]:
    result: dict[str, dict] = {}
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated "
                        "FROM ratchet_stops"
                    )
                    for row in cur.fetchall():
                        result[row[0]] = {
                            "symbol":         row[0],
                            "stop_price":     row[1],
                            "fill_price":     row[2],
                            "atr":            row[3],
                            "atr_multiplier": row[4],
                            "side":           row[5] if row[5] else "long",
                            "last_updated":   str(row[6]),
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
                    "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated "
                    "FROM ratchet_stops"
                ):
                    d = dict(row)
                    d.setdefault("side", "long")
                    result[d["symbol"]] = d
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
    side: str = "long",
) -> Optional[dict]:
    """
    Called immediately after a new position is filled.
    Computes ATR, sets initial stop, persists it, and places a GTC stop order.

    For longs: stop is below fill, ratchets up.
    For shorts: stop is above fill (stop-buy to cap loss), ratchets down.

    Leveraged ETFs (TQQQ, SOXL, UPRO) automatically use LEVERAGED_ATR_MULTIPLIER (1.5×).

    Returns the stop dict or None on failure.
    """
    atr_mult   = _resolve_atr_multiplier(ticker)
    atr        = compute_atr(ticker)
    stop_price = compute_initial_stop(fill_price, atr, atr_mult, side=side)
    atr_used   = atr if atr is not None else 0.0

    label = f"{atr_mult}×ATR" if atr else f"{FALLBACK_STOP_PCT:.0%} fallback"
    is_letf = ticker in LEVERAGED_RISK_TICKERS
    logger.info(
        f"Ratchet | {ticker} [{side.upper()}] initial stop=${stop_price:.4f} "
        f"(fill=${fill_price:.4f}, {label}={atr_used:.4f})"
        + (" [LETF 1.5× tighter stop]" if is_letf else "")
    )

    save_stop(ticker, stop_price, fill_price, atr_used, atr_mult, side=side)

    if not dry_run:
        try:
            if side == "short":
                from execution.broker import place_short_stop_order
                result = place_short_stop_order(ticker, int(qty), stop_price)
            else:
                from execution.broker import place_stop_order
                result = place_stop_order(ticker, qty, stop_price)
            logger.info(f"Ratchet | GTC stop placed for {ticker} [{side}]: {result['id']}")
            return {
                "stop_price":     stop_price,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "side":           side,
                "order":          result,
            }
        except Exception as exc:
            logger.error(f"Ratchet | Failed to place stop order for {ticker} [{side}]: {exc}")
            return {
                "stop_price":     stop_price,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "side":           side,
                "order":          None,
            }

    return {
        "stop_price":     stop_price,
        "atr":            atr_used,
        "atr_multiplier": atr_mult,
        "side":           side,
        "order":          None,
        "dry_run":        True,
    }


def maybe_ratchet(ticker: str, current_price: float, qty: float, dry_run: bool = False) -> Optional[dict]:
    """
    Called on every cycle for active positions.
    Ratchets the stop in the trade's favour, then cancels the old GTC stop and
    places a new one at the better price.

    Side ("long"/"short") is restored from the persisted stop record.
    For longs: ratchets UP.  For shorts: ratchets DOWN.

    Returns updated stop dict, or None if no ratchet was needed.
    """
    existing = get_stop(ticker)
    if existing is None:
        logger.debug(f"Ratchet | No tracked stop for {ticker} — skipping ratchet")
        return None

    atr_mult = existing.get("atr_multiplier", _resolve_atr_multiplier(ticker))
    side     = existing.get("side", "long")

    atr      = compute_atr(ticker)
    new_stop = ratchet_stop(current_price, atr, existing["stop_price"], atr_mult, side=side)

    # Check if we actually improved the stop
    if side == "short":
        improved = new_stop < existing["stop_price"]
    else:
        improved = new_stop > existing["stop_price"]

    if not improved:
        return None  # no change needed

    atr_used = atr if atr is not None else existing.get("atr", 0.0)
    save_stop(ticker, new_stop, existing["fill_price"], atr_used, atr_mult, side=side)

    if not dry_run:
        try:
            from execution.broker import cancel_all_orders
            cancel_all_orders()   # cancel existing stop for this ticker
            if side == "short":
                from execution.broker import place_short_stop_order
                result = place_short_stop_order(ticker, int(qty), new_stop)
            else:
                from execution.broker import place_stop_order
                result = place_stop_order(ticker, qty, new_stop)
            logger.info(
                f"Ratchet | {ticker} [{side}] stop ratcheted "
                f"${existing['stop_price']:.4f} → ${new_stop:.4f} "
                f"| mult={atr_mult}× | new order {result['id']}"
            )
            return {
                "stop_price":     new_stop,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "side":           side,
                "order":          result,
            }
        except Exception as exc:
            logger.error(f"Ratchet | Failed to ratchet stop for {ticker} [{side}]: {exc}")

    return {
        "stop_price":     new_stop,
        "atr":            atr_used,
        "atr_multiplier": atr_mult,
        "side":           side,
        "order":          None,
        "dry_run":        True,
    }
