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
