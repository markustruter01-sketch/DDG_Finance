"""
db_utils.py — Kraken Current Database Interface
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.insert(0, _TRADING_PLATFORM)

DB_ID = 8
BOT_ID = "kraken-current"


def _get_conn():
    from db.postgres import get_conn
    return get_conn()


def _query(sql: str, params: tuple = (), fetch: bool = True):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch:
                    return cur.fetchall()
                return None
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | query failed: {e}")
        return [] if fetch else None


def ensure_kraken_current_tables():
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                # Idempotent migration: force_refresh column on shared kraken_heartbeat table
                cur.execute("""
                    ALTER TABLE kraken_heartbeat
                    ADD COLUMN IF NOT EXISTS force_refresh BOOLEAN NOT NULL DEFAULT FALSE;
                """)
                cur.execute("""
                CREATE TABLE IF NOT EXISTS kraken_current_positions (
                    position_id     TEXT PRIMARY KEY,
                    bot_id          TEXT NOT NULL DEFAULT 'kraken-current',
                    symbol          TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    entry_price     DOUBLE PRECISION NOT NULL,
                    current_price   DOUBLE PRECISION,
                    stop_level      DOUBLE PRECISION,
                    best_price      DOUBLE PRECISION,
                    trailing_active BOOLEAN NOT NULL DEFAULT FALSE,
                    trail_immediate BOOLEAN NOT NULL DEFAULT FALSE,
                    size_usd        DOUBLE PRECISION,
                    units           DOUBLE PRECISION,
                    stop_distance   DOUBLE PRECISION,
                    ema_fast        DOUBLE PRECISION,
                    ema_slow        DOUBLE PRECISION,
                    adx             DOUBLE PRECISION,
                    fees_paid       DOUBLE PRECISION,
                    opened_at       TIMESTAMPTZ,
                    regime_at_entry TEXT,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_kc_positions_bot_id
                    ON kraken_current_positions (bot_id);
                """)
                cur.execute("""
                CREATE TABLE IF NOT EXISTS kraken_current_trades (
                    id              BIGSERIAL PRIMARY KEY,
                    symbol          TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    entry_price     DOUBLE PRECISION NOT NULL,
                    exit_price      DOUBLE PRECISION,
                    units           DOUBLE PRECISION NOT NULL,
                    pnl             DOUBLE PRECISION,
                    holding_days    DOUBLE PRECISION,
                    reason          TEXT,
                    ema_fast        DOUBLE PRECISION,
                    ema_slow        DOUBLE PRECISION,
                    adx_entry       DOUBLE PRECISION,
                    closed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    bot_id          TEXT NOT NULL DEFAULT 'kraken-current'
                );
                CREATE INDEX IF NOT EXISTS idx_kc_trades_closed_at
                    ON kraken_current_trades (closed_at DESC);

                CREATE TABLE IF NOT EXISTS kraken_current_portfolio (
                    id              INTEGER PRIMARY KEY DEFAULT 8,
                    bot_id          TEXT NOT NULL DEFAULT 'kraken-current',
                    equity_usd      DOUBLE PRECISION NOT NULL DEFAULT 100000,
                    cash_usd        DOUBLE PRECISION NOT NULL DEFAULT 100000,
                    open_positions  INTEGER NOT NULL DEFAULT 0,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                INSERT INTO kraken_current_portfolio (id, bot_id, equity_usd, cash_usd)
                VALUES (8, 'kraken-current', 100000, 100000)
                ON CONFLICT (id) DO NOTHING;

                CREATE TABLE IF NOT EXISTS kraken_current_signal_scan (
                    id              BIGSERIAL PRIMARY KEY,
                    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    symbol          TEXT NOT NULL,
                    ema_fast        DOUBLE PRECISION,
                    ema_slow        DOUBLE PRECISION,
                    adx             DOUBLE PRECISION,
                    hurst           DOUBLE PRECISION,
                    direction       TEXT,
                    passed          BOOLEAN NOT NULL DEFAULT FALSE,
                    block_reason    TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_kc_signal_scan_at
                    ON kraken_current_signal_scan (scanned_at DESC);
                """)
        logger.info("KrakenCurrent DB | Tables ready")
    except Exception as e:
        logger.error(f"KrakenCurrent DB | ensure_tables failed: {e}")


def write_heartbeat(equity: float, positions: int, cycle: int, status: str = "running", paused: bool = False, error: Optional[str] = None):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kraken_heartbeat (id, bot_id, status, cycle_count, equity_usd, position_count, paper_trading, bot_paused, error, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        bot_id = EXCLUDED.bot_id,
                        status = EXCLUDED.status,
                        cycle_count = EXCLUDED.cycle_count,
                        equity_usd = EXCLUDED.equity_usd,
                        position_count = EXCLUDED.position_count,
                        bot_paused = EXCLUDED.bot_paused,
                        error = EXCLUDED.error,
                        last_updated = NOW()
                """, (DB_ID, BOT_ID, status, cycle, equity, positions, paused, error))
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | heartbeat failed: {e}")


def check_and_clear_force_refresh() -> bool:
    """Check if force_refresh flag is set for this bot. If yes, clear it and return True."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT force_refresh FROM kraken_heartbeat WHERE id = %s",
                    (DB_ID,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    cur.execute(
                        "UPDATE kraken_heartbeat SET force_refresh = FALSE WHERE id = %s",
                        (DB_ID,)
                    )
                    logger.info(f"KrakenCurrent | force_refresh flag cleared — re-initialising params")
                    return True
        return False
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | check_and_clear_force_refresh failed: {e}")
        return False


def write_portfolio(equity: float, cash: float, positions: int):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kraken_current_portfolio
                    SET equity_usd = %s, cash_usd = %s, open_positions = %s, updated_at = NOW()
                    WHERE id = 8
                """, (equity, cash, positions))
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | portfolio write failed: {e}")


def record_trade(trade: dict):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kraken_current_trades
                        (symbol, direction, entry_price, exit_price, units, pnl_usd, holding_days, reason, ema_fast, ema_slow, adx_entry, closed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    trade.get("symbol"), trade.get("direction"), trade.get("entry_price"),
                    trade.get("exit_price"), trade.get("units"), trade.get("pnl"),
                    trade.get("holding_days"), trade.get("reason"),
                    trade.get("ema_fast"), trade.get("ema_slow"), trade.get("adx"),
                ))
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | trade record failed: {e}")


def record_signal_scan(scan_results: list[dict]):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                for r in scan_results:
                    cur.execute("""
                        INSERT INTO kraken_current_signal_scan
                            (symbol, ema_fast, ema_slow, adx, hurst, direction, passed, block_reason)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        r.get("symbol"), r.get("ema_fast"), r.get("ema_slow"),
                        r.get("adx"), r.get("hurst"), r.get("direction"),
                        r.get("passed", False), r.get("block_reason"),
                    ))
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | signal_scan record failed: {e}")


def get_latest_signal_scan() -> list[dict]:
    rows = _query("""
        SELECT DISTINCT ON (symbol) symbol, ema_fast, ema_slow, adx, hurst, direction, passed, block_reason, scanned_at
        FROM kraken_current_signal_scan
        ORDER BY symbol, scanned_at DESC
    """)
    if not rows:
        return []
    cols = ["symbol", "ema_fast", "ema_slow", "adx", "hurst", "direction", "passed", "block_reason", "scanned_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_kraken_current_equity() -> float:
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT equity_usd FROM kraken_current_portfolio WHERE id = 8")
                row = cur.fetchone()
                return float(row[0]) if row else 100_000.0
    except Exception:
        return 100_000.0


def upsert_positions(positions: dict, current_prices: dict | None = None, regime: str | None = None):
    """Upsert all open positions to DB and remove any stale rows for this bot.

    regime_at_entry is written on first INSERT only; subsequent updates preserve
    the original value so entry-time context is never overwritten.
    """
    if current_prices is None:
        current_prices = {}
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                active_ids: list[str] = []
                for symbol, pos in positions.items():
                    d = pos.to_dict() if hasattr(pos, "to_dict") else pos
                    pos_id = f"{BOT_ID}_{symbol}"
                    active_ids.append(pos_id)
                    cur.execute("""
                        INSERT INTO kraken_current_positions (
                            position_id, bot_id, symbol, direction,
                            entry_price, current_price, stop_level, best_price,
                            trailing_active, trail_immediate, size_usd, units,
                            stop_distance, ema_fast, ema_slow, adx, fees_paid,
                            opened_at, regime_at_entry, updated_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, NOW()
                        )
                        ON CONFLICT (position_id) DO UPDATE SET
                            direction       = EXCLUDED.direction,
                            current_price   = EXCLUDED.current_price,
                            stop_level      = EXCLUDED.stop_level,
                            best_price      = EXCLUDED.best_price,
                            trailing_active = EXCLUDED.trailing_active,
                            trail_immediate = EXCLUDED.trail_immediate,
                            size_usd        = EXCLUDED.size_usd,
                            units           = EXCLUDED.units,
                            stop_distance   = EXCLUDED.stop_distance,
                            ema_fast        = EXCLUDED.ema_fast,
                            ema_slow        = EXCLUDED.ema_slow,
                            adx             = EXCLUDED.adx,
                            fees_paid       = EXCLUDED.fees_paid,
                            updated_at      = NOW()
                    """, (
                        pos_id, BOT_ID, symbol, d.get("direction"),
                        d.get("entry_price"), current_prices.get(symbol),
                        d.get("stop_level"), d.get("best_price"),
                        bool(d.get("trailing_active", False)),
                        bool(d.get("trail_immediate", False)),
                        d.get("position_value"), d.get("units"),
                        d.get("stop_distance"), d.get("ema_fast"),
                        d.get("ema_slow"), d.get("adx"), d.get("fees_paid"),
                        d.get("opened_at"), regime,
                    ))
                # Remove rows for positions that are no longer open
                if active_ids:
                    cur.execute(
                        "DELETE FROM kraken_current_positions WHERE bot_id = %s AND position_id != ALL(%s)",
                        (BOT_ID, active_ids),
                    )
                else:
                    cur.execute(
                        "DELETE FROM kraken_current_positions WHERE bot_id = %s",
                        (BOT_ID,),
                    )
        logger.debug(f"KrakenCurrent DB | upserted {len(positions)} position(s)")
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | upsert_positions failed: {e}")


def load_positions_from_db() -> list[dict]:
    """Load all open positions for this bot from the DB.
    Returns a list of dicts compatible with TrendPosition.from_dict()."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, direction, entry_price, stop_level, best_price,
                           trailing_active, trail_immediate, size_usd, units,
                           stop_distance, ema_fast, ema_slow, adx, fees_paid, opened_at
                    FROM kraken_current_positions
                    WHERE bot_id = %s
                    ORDER BY opened_at ASC
                """, (BOT_ID,))
                rows = cur.fetchall()
        result = []
        for row in rows:
            (symbol, direction, entry_price, stop_level, best_price,
             trailing_active, trail_immediate, size_usd, units,
             stop_distance, ema_fast, ema_slow, adx, fees_paid, opened_at) = row
            result.append({
                "symbol": symbol,
                "direction": direction,
                "entry_price": float(entry_price) if entry_price is not None else 0.0,
                "stop_level": float(stop_level) if stop_level is not None else 0.0,
                "best_price": float(best_price) if best_price is not None else float(entry_price or 0),
                "trailing_active": bool(trailing_active),
                "trail_immediate": bool(trail_immediate),
                "position_value": float(size_usd) if size_usd is not None else 0.0,
                "units": float(units) if units is not None else 0.0,
                "stop_distance": float(stop_distance) if stop_distance is not None else 0.0,
                "ema_fast": float(ema_fast) if ema_fast is not None else 0.0,
                "ema_slow": float(ema_slow) if ema_slow is not None else 0.0,
                "adx": float(adx) if adx is not None else 0.0,
                "fees_paid": float(fees_paid) if fees_paid is not None else 0.0,
                "opened_at": opened_at.isoformat() if opened_at is not None else datetime.now(timezone.utc).isoformat(),
            })
        return result
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | load_positions_from_db failed: {e}")
        return []


def delete_position(position_id: str):
    """Delete a single position row from the DB by its position_id."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM kraken_current_positions WHERE position_id = %s",
                    (position_id,),
                )
        logger.debug(f"KrakenCurrent DB | deleted position {position_id}")
    except Exception as e:
        logger.warning(f"KrakenCurrent DB | delete_position failed: {e}")
