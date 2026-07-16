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

ATR_MULTIPLIER:           float = 2.0   # canonical = algo_scanner.ATR_MULTIPLIER (2.0); Storm Mode 2.5 reverted
LEVERAGED_ATR_MULTIPLIER: float = 2.0   # Tighter multiplier for leveraged ETFs (no leveraged tickers currently held by Oracle)
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

        # Wilder's smoothed ATR — seed with SMA of first period, then EMA-smooth
        atr = sum(tr_list[:ATR_PERIOD]) / ATR_PERIOD
        for tr in tr_list[ATR_PERIOD:]:
            atr = (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
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


# ── Pre-submission stop-price validation ───────────────────────────────────

def _safe_stop_price(
    ticker: str,
    intended_stop: float,
    atr: Optional[float],
    atr_mult: float,
    side: str = "long",
) -> tuple[float, str]:
    """
    Validate *intended_stop* against the live Alpaca price and return a stop
    that is guaranteed to be accepted by the broker.

    Returns (stop_price, status) where status is one of:
      'ok'         — intended_stop is valid relative to current price, submit as-is
      'reanchored' — stop was at/above current price; recomputed from live price
                     using the same ATR multiplier (or 2% fallback if ATR=None)
      'no_price'   — Alpaca price unavailable; caller MUST defer, not submit blind

    Root-cause guard for the Jun-9 mass-exit: ATR=None → 2% fallback anchored to
    FILL price → by placement time price had already dropped below that stop →
    Alpaca rejected ("stop price must be below current price") → stop_order_id=NULL
    → position ran naked until deleted EOD reconciler fired.

    ATR/fallback distances (2.0×ATR / 2%) are UNCHANGED — this only shifts the
    anchor point from fill to live price when the fill-anchored stop is invalid.
    """
    try:
        from execution.broker import get_latest_price
        current_price: Optional[float] = get_latest_price(ticker)
    except Exception as exc:
        logger.warning(f"Ratchet | {ticker}: live-price fetch failed: {exc}")
        current_price = None

    if current_price is None:
        return intended_stop, "no_price"

    if side == "long":
        if intended_stop < current_price:
            return intended_stop, "ok"
        # Stop is at or above current price — Alpaca will reject it.
        # Reanchor: compute the same ATR distance below the LIVE price instead.
        live_stop = compute_initial_stop(current_price, atr, atr_mult, side="long")
        logger.warning(
            f"Ratchet | {ticker} [LONG]: intended stop ${intended_stop:.2f} ≥ "
            f"current ${current_price:.2f} — reanchored to live price "
            f"→ ${live_stop:.2f}  [Jun-9 rejection guard]"
        )
        return live_stop, "reanchored"
    else:
        # Short: stop is ABOVE current price
        if intended_stop > current_price:
            return intended_stop, "ok"
        live_stop = compute_initial_stop(current_price, atr, atr_mult, side="short")
        logger.warning(
            f"Ratchet | {ticker} [SHORT]: intended stop ${intended_stop:.2f} ≤ "
            f"current ${current_price:.2f} — reanchored to live price → ${live_stop:.2f}"
        )
        return live_stop, "reanchored"


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
                last_updated   DATE NOT NULL,
                stop_order_id  TEXT
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
        cur.execute("""
            ALTER TABLE ratchet_stops
            ADD COLUMN IF NOT EXISTS stop_order_id TEXT
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
                last_updated   TEXT NOT NULL,
                stop_order_id  TEXT
            )
        """)
        for col_ddl in [
            "ALTER TABLE ratchet_stops ADD COLUMN atr_multiplier REAL NOT NULL DEFAULT 2.0",
            "ALTER TABLE ratchet_stops ADD COLUMN side TEXT NOT NULL DEFAULT 'long'",
            "ALTER TABLE ratchet_stops ADD COLUMN stop_order_id TEXT",
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
    stop_order_id: str | None = None,
) -> None:
    today = date.today().isoformat()
    try:
        from db.postgres import get_conn, is_pg_available, record_position_entry
        if is_pg_available():
            with get_conn() as conn:
                _ensure_table_pg(conn)
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ratchet_stops (symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated, stop_order_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol) DO UPDATE SET
                            stop_price     = EXCLUDED.stop_price,
                            fill_price     = EXCLUDED.fill_price,
                            atr            = EXCLUDED.atr,
                            atr_multiplier = EXCLUDED.atr_multiplier,
                            side           = EXCLUDED.side,
                            last_updated   = EXCLUDED.last_updated,
                            stop_order_id  = EXCLUDED.stop_order_id
                    """, (symbol, stop_price, fill_price, atr, atr_multiplier, side, today, stop_order_id))
                conn.commit()
            # Record immutable entry timestamp (ON CONFLICT DO NOTHING keeps the FIRST open time)
            record_position_entry(symbol, entry_price=fill_price)
            logger.debug(f"Ratchet | Saved stop for {symbol}: ${stop_price:.4f} mult={atr_multiplier}× side={side} (pg)")
            return
    except Exception as exc:
        logger.warning(f"Ratchet | PG save failed for {symbol}: {exc} — falling back to SQLite")

    _save_stop_sqlite(symbol, stop_price, fill_price, atr, atr_multiplier, side, today, stop_order_id)


def _save_stop_sqlite(symbol, stop_price, fill_price, atr, atr_multiplier, side, today, stop_order_id=None) -> None:
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).parent.parent / "trade_journal.db"
    _ensure_table_sqlite(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO ratchet_stops (symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated, stop_order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                stop_price     = excluded.stop_price,
                fill_price     = excluded.fill_price,
                atr            = excluded.atr,
                atr_multiplier = excluded.atr_multiplier,
                side           = excluded.side,
                last_updated   = excluded.last_updated,
                stop_order_id  = excluded.stop_order_id
        """, (symbol, stop_price, fill_price, atr, atr_multiplier, side, today, stop_order_id))
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
                        "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated, stop_order_id "
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
                    "stop_order_id":  row[7],
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
            "SELECT symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated, stop_order_id "
            "FROM ratchet_stops WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if row:
        d = dict(row)
        d.setdefault("side", "long")
        d.setdefault("stop_order_id", None)
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
        # ── Pre-submission guard (STEP 2) ────────────────────────────────────────
        # Validate stop vs live Alpaca price BEFORE submitting.
        # Prevents the Jun-9 scenario: ATR=None → 2% fallback anchored to fill →
        # by placement time price had dropped → Alpaca rejected → naked position.
        # Only applies to longs (short stops are above price, already safe for broker).
        if side == "long":
            safe_price, price_status = _safe_stop_price(
                ticker, stop_price, atr, atr_mult, side="long"
            )
            if price_status == "no_price":
                # Can't validate — do NOT submit blind. Sweep retries next cycle.
                logger.error(
                    f"Ratchet | {ticker} [LONG]: Alpaca price unavailable — "
                    f"cannot validate stop ${stop_price:.2f}. "
                    f"Position UNPROTECTED; sweep will retry next cycle."
                )
                try:
                    from core.degradation_tracker import record_degradation
                    record_degradation(
                        component="oracle_stop",
                        severity="high",
                        error_type="stop_placement_no_price",
                        message=f"{ticker}: no live Alpaca price — stop deferred, position unprotected",
                    )
                except Exception:
                    pass
                return {
                    "stop_price":     stop_price,
                    "atr":            atr_used,
                    "atr_multiplier": atr_mult,
                    "side":           side,
                    "order":          None,
                    "needs_retry":    True,
                }
            if price_status == "reanchored":
                # DB record was saved with fill-price anchor above; overwrite with
                # live-price anchor now that we know the fill anchor is stale.
                stop_price = safe_price
                save_stop(ticker, stop_price, fill_price, atr_used, atr_mult, side=side)

        try:
            if side == "short":
                from execution.broker import place_short_stop_order
                result = place_short_stop_order(ticker, int(qty), stop_price)
            else:
                from execution.broker import place_stop_order
                result = place_stop_order(ticker, qty, stop_price)
            order_id = result.get("id")
            logger.info(
                f"Ratchet | GTC stop placed for {ticker} [{side}]: "
                f"{order_id} @ ${stop_price:.4f}"
            )
            save_stop(ticker, stop_price, fill_price, atr_used, atr_mult, side=side, stop_order_id=order_id)
            return {
                "stop_price":     stop_price,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "side":           side,
                "order":          result,
            }
        except Exception as exc:
            logger.error(
                f"Ratchet | {ticker} [{side.upper()}]: GTC stop FAILED — "
                f"{exc} — position UNPROTECTED, sweep will retry next cycle."
            )
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="oracle_stop",
                    severity="high",
                    error_type="stop_placement_failed",
                    message=f"{ticker}: GTC stop placement FAILED — position UNPROTECTED, retry next cycle",
                    detail=str(exc)[:500],
                )
            except Exception:
                pass
            # B-1 fix: direct Discord alert — fires even if degradation tracker is down.
            try:
                from notifications.discord import notify_capital_risk
                notify_capital_risk(
                    f"🔴 {ticker}: stop placement FAILED — naked until next cycle",
                    symbol=ticker,
                )
            except Exception:
                pass
            return {
                "stop_price":     stop_price,
                "atr":            atr_used,
                "atr_multiplier": atr_mult,
                "side":           side,
                "order":          None,
                "needs_retry":    True,
            }

    return {
        "stop_price":     stop_price,
        "atr":            atr_used,
        "atr_multiplier": atr_mult,
        "side":           side,
        "order":          None,
        "dry_run":        True,
    }


# ── Per-cycle naked-stop sweep (STEP 3) ────────────────────────────────────

def sweep_naked_positions(dry_run: bool = False) -> dict:
    """
    Per-cycle safety sweep — permanent replacement for the deleted EOD reconciler.

    Called by pipeline.py on every 15-minute intraday cycle.  Checks every open
    Oracle long position against live Alpaca open orders.  Any long with no
    active GTC stop-sell gets a new stop placed via the _safe_stop_price path.

    This means a naked position can persist for at most ONE cycle (≤ 15 min).

    Logic per naked position:
      1. Read ratchet_stops record (stop_price, fill_price, ATR).
      2. Validate/reanchor stop vs live price (_safe_stop_price).
      3. Place GTC stop if price is available; defer + degrade if not.

    Returns dict: {placed: [...], deferred: [...], skipped: [...], errors: [...]}
    """
    import math as _math
    from execution.broker import get_positions, get_open_orders

    results: dict = {"placed": [], "deferred": [], "skipped": [], "errors": []}

    try:
        live_positions = get_positions()
        open_orders    = get_open_orders()
    except Exception as exc:
        logger.error(f"StopSweep | Cannot fetch broker data: {exc}")
        return results

    # Symbols that already have a live GTC stop-sell at the broker
    covered: set[str] = {
        o["symbol"]
        for o in open_orders
        if o.get("side") == "sell"
        and o.get("status") in ("new", "accepted", "pending_new")
    }

    naked_found = 0
    for pos in live_positions:
        symbol = pos.get("symbol", "")
        side   = pos.get("side", "long")
        qty    = float(pos.get("qty", 0))

        # Only sweep long positions (short stop-buys are different mechanics)
        if side != "long":
            results["skipped"].append({"symbol": symbol, "reason": "short_not_swept"})
            continue

        if symbol in covered:
            results["skipped"].append({"symbol": symbol, "reason": "has_broker_stop"})
            continue

        # Position is naked — no live GTC stop-sell at broker
        naked_found += 1
        stop_qty = _math.floor(abs(qty))
        if stop_qty < 1:
            logger.debug(f"StopSweep | {symbol}: sub-1-share, cannot place broker stop")
            results["skipped"].append({"symbol": symbol, "reason": "sub_1_share"})
            continue

        ratchet = get_stop(symbol)
        if ratchet is None:
            logger.warning(
                f"StopSweep | {symbol}: naked long with NO ratchet_stops record — "
                f"cannot compute safe stop"
            )
            results["errors"].append({"symbol": symbol, "error": "no_ratchet_record"})
            continue

        db_stop    = ratchet["stop_price"]
        fill_price = ratchet["fill_price"]
        atr_raw    = ratchet.get("atr") or 0.0
        atr_opt: Optional[float] = atr_raw if atr_raw > 0 else None
        atr_mult   = ratchet.get("atr_multiplier", ATR_MULTIPLIER)

        # Validate/reanchor stop vs live price
        safe_stop, price_status = _safe_stop_price(
            symbol, db_stop, atr_opt, atr_mult, side="long"
        )

        if price_status == "no_price":
            logger.error(
                f"StopSweep | {symbol}: naked long — Alpaca price unavailable, "
                f"deferring stop to next cycle."
            )
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="oracle_stop",
                    severity="high",
                    error_type="stop_sweep_no_price",
                    message=f"{symbol}: naked long — no Alpaca price, stop deferred to next cycle",
                )
            except Exception:
                pass
            results["deferred"].append({"symbol": symbol, "reason": "no_price"})
            continue

        if price_status == "reanchored":
            logger.warning(
                f"StopSweep | {symbol}: DB stop ${db_stop:.2f} invalid vs live price, "
                f"reanchored to ${safe_stop:.2f} — updating DB"
            )
            save_stop(
                symbol, safe_stop, fill_price, atr_raw, atr_mult,
                side="long", stop_order_id=None,
            )

        logger.warning(
            f"StopSweep | {symbol}: NAKED long — placing GTC stop "
            f"qty={stop_qty} @ ${safe_stop:.2f}"
            + (" [DRY RUN]" if dry_run else "")
        )

        if dry_run:
            results["placed"].append({
                "symbol":       symbol,
                "stop_price":   safe_stop,
                "qty":          stop_qty,
                "price_status": price_status,
                "dry_run":      True,
            })
            continue

        try:
            from execution.broker import place_stop_order
            order    = place_stop_order(symbol, stop_qty, safe_stop)
            order_id = order.get("id")
            save_stop(
                symbol, safe_stop, fill_price, atr_raw, atr_mult,
                side="long", stop_order_id=order_id,
            )
            logger.info(
                f"StopSweep | ✓ {symbol}: GTC stop placed "
                f"qty={stop_qty} stop=${safe_stop:.2f} order_id={order_id}"
            )
            results["placed"].append({
                "symbol":       symbol,
                "stop_price":   safe_stop,
                "qty":          stop_qty,
                "order_id":     order_id,
                "price_status": price_status,
            })
        except Exception as exc:
            logger.error(
                f"StopSweep | ✗ {symbol}: GTC stop FAILED "
                f"(qty={stop_qty} stop=${safe_stop:.2f}): {exc} — still naked, retry next cycle"
            )
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="oracle_stop",
                    severity="high",
                    error_type="stop_sweep_placement_failed",
                    message=f"{symbol}: stop sweep GTC placement FAILED — still naked, retry next cycle",
                    detail=str(exc)[:500],
                )
            except Exception:
                pass
            # B-2 fix: escalated alert — naked AND sweep also failed.
            try:
                from notifications.discord import notify_capital_risk
                notify_capital_risk(
                    f"🔴 {symbol}: sweep stop placement FAILED — naked, sweep ALSO failed",
                    symbol=symbol,
                )
            except Exception:
                pass
            results["errors"].append({"symbol": symbol, "error": str(exc)})

    if naked_found:
        logger.warning(
            f"StopSweep | Cycle complete — naked found={naked_found}: "
            f"placed={len(results['placed'])} deferred={len(results['deferred'])} "
            f"errors={len(results['errors'])}"
        )
    else:
        logger.debug("StopSweep | All open long positions have live broker stops ✓")

    return results


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
            from execution.broker import cancel_order
            old_order_id = existing.get("stop_order_id")
            if old_order_id:
                cancel_order(old_order_id)
            else:
                logger.warning(
                    f"Ratchet | No stop_order_id on record for {ticker} — skipping cancel (will not cancel other positions' stops)"
                )
            if side == "short":
                from execution.broker import place_short_stop_order
                result = place_short_stop_order(ticker, int(qty), new_stop)
            else:
                from execution.broker import place_stop_order
                result = place_stop_order(ticker, qty, new_stop)
            new_order_id = result.get("id")
            save_stop(ticker, new_stop, existing["fill_price"], atr_used, atr_mult, side=side, stop_order_id=new_order_id)
            logger.info(
                f"Ratchet | {ticker} [{side}] stop ratcheted "
                f"${existing['stop_price']:.4f} → ${new_stop:.4f} "
                f"| mult={atr_mult}× | new order {new_order_id}"
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
