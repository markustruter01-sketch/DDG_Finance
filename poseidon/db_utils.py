"""
db_utils.py — Poseidon Database Interface
Writes heartbeat, portfolio state, trades, and pair params to PostgreSQL
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.insert(0, _TRADING_PLATFORM)

DB_ID = 7  # poseidon is bot id 7
BOT_ID = "poseidon"


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
        logger.warning(f"Poseidon DB | query failed: {e}")
        return [] if fetch else None


def ensure_poseidon_tables():
    """Create Poseidon-specific tables if they don't exist."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS poseidon_pair_params (
                    id              BIGSERIAL PRIMARY KEY,
                    pair_set_id     INTEGER NOT NULL,
                    asset_a         TEXT NOT NULL,
                    asset_b         TEXT NOT NULL,
                    hedge_ratio     DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    hedge_ratio_30d_avg DOUBLE PRECISION,
                    last_calculated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    spread_mean     DOUBLE PRECISION,
                    spread_std      DOUBLE PRECISION,
                    hurst           DOUBLE PRECISION,
                    adf_pvalue      DOUBLE PRECISION,
                    is_tradeable    BOOLEAN NOT NULL DEFAULT FALSE,
                    notes           TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_poseidon_pair_params_id
                    ON poseidon_pair_params (pair_set_id);

                CREATE TABLE IF NOT EXISTS poseidon_trades (
                    id              BIGSERIAL PRIMARY KEY,
                    pair_set_id     INTEGER NOT NULL,
                    asset_a         TEXT NOT NULL,
                    asset_b         TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    leg_a_entry     DOUBLE PRECISION NOT NULL,
                    leg_b_entry     DOUBLE PRECISION NOT NULL,
                    leg_a_exit      DOUBLE PRECISION,
                    leg_b_exit      DOUBLE PRECISION,
                    leg_a_pnl       DOUBLE PRECISION,
                    leg_b_pnl       DOUBLE PRECISION,
                    net_pnl         DOUBLE PRECISION,
                    entry_zscore    DOUBLE PRECISION,
                    holding_hours   DOUBLE PRECISION,
                    reason          TEXT,
                    closed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    bot_id          TEXT NOT NULL DEFAULT 'poseidon'
                );
                CREATE INDEX IF NOT EXISTS idx_poseidon_trades_closed_at
                    ON poseidon_trades (closed_at DESC);

                CREATE TABLE IF NOT EXISTS poseidon_portfolio (
                    id              INTEGER PRIMARY KEY DEFAULT 7,
                    bot_id          TEXT NOT NULL DEFAULT 'poseidon',
                    equity_usd      DOUBLE PRECISION NOT NULL DEFAULT 100000,
                    cash_usd        DOUBLE PRECISION NOT NULL DEFAULT 100000,
                    open_positions  INTEGER NOT NULL DEFAULT 0,
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                INSERT INTO poseidon_portfolio (id, bot_id, equity_usd, cash_usd)
                VALUES (7, 'poseidon', 100000, 100000)
                ON CONFLICT (id) DO NOTHING;
                """)
        logger.info("Poseidon DB | Tables ready")
    except Exception as e:
        logger.error(f"Poseidon DB | ensure_tables failed: {e}")


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
        logger.warning(f"Poseidon DB | heartbeat failed: {e}")


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
                    logger.info(f"Poseidon | force_refresh flag cleared — re-initialising params")
                    return True
        return False
    except Exception as e:
        logger.warning(f"Poseidon DB | check_and_clear_force_refresh failed: {e}")
        return False


def write_portfolio(equity: float, cash: float, positions: int):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE poseidon_portfolio
                    SET equity_usd = %s, cash_usd = %s, open_positions = %s, updated_at = NOW()
                    WHERE id = 7
                """, (equity, cash, positions))
    except Exception as e:
        logger.warning(f"Poseidon DB | portfolio write failed: {e}")


def upsert_pair_params(pair_set_id: int, asset_a: str, asset_b: str, hedge_ratio: float,
                       hedge_ratio_30d_avg: Optional[float], spread_mean: float, spread_std: float,
                       hurst: float, adf_pvalue: float, is_tradeable: bool, notes: str = ""):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO poseidon_pair_params
                        (pair_set_id, asset_a, asset_b, hedge_ratio, hedge_ratio_30d_avg,
                         last_calculated, spread_mean, spread_std, hurst, adf_pvalue, is_tradeable, notes)
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (pair_set_id) DO UPDATE SET
                        hedge_ratio = EXCLUDED.hedge_ratio,
                        hedge_ratio_30d_avg = EXCLUDED.hedge_ratio_30d_avg,
                        last_calculated = NOW(),
                        spread_mean = EXCLUDED.spread_mean,
                        spread_std = EXCLUDED.spread_std,
                        hurst = EXCLUDED.hurst,
                        adf_pvalue = EXCLUDED.adf_pvalue,
                        is_tradeable = EXCLUDED.is_tradeable,
                        notes = EXCLUDED.notes
                """, (pair_set_id, asset_a, asset_b, hedge_ratio, hedge_ratio_30d_avg,
                      spread_mean, spread_std, hurst, adf_pvalue, is_tradeable, notes))
        logger.debug(f"Poseidon DB | Pair {pair_set_id} params upserted: H={hurst:.3f} ADF={adf_pvalue:.3f} tradeable={is_tradeable}")
    except Exception as e:
        logger.warning(f"Poseidon DB | pair_params upsert failed: {e}")


def record_trade(trade: dict):
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO poseidon_trades
                        (pair_set_id, asset_a, asset_b, direction, leg_a_entry, leg_b_entry,
                         leg_a_exit, leg_b_exit, leg_a_pnl, leg_b_pnl, net_pnl, entry_zscore,
                         holding_hours, reason, closed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    trade.get("pair_set_id"), trade.get("asset_a"), trade.get("asset_b"),
                    trade.get("direction"), trade.get("leg_a_entry"), trade.get("leg_b_entry"),
                    trade.get("leg_a_exit"), trade.get("leg_b_exit"), trade.get("leg_a_pnl"),
                    trade.get("leg_b_pnl"), trade.get("net_pnl"), trade.get("entry_zscore"),
                    trade.get("holding_hours"), trade.get("reason"),
                ))
    except Exception as e:
        logger.warning(f"Poseidon DB | trade record failed: {e}")


def get_pair_params(pair_set_id: int) -> Optional[dict]:
    rows = _query(
        "SELECT pair_set_id, asset_a, asset_b, hedge_ratio, hedge_ratio_30d_avg, hurst, adf_pvalue, is_tradeable FROM poseidon_pair_params WHERE pair_set_id = %s",
        (pair_set_id,)
    )
    if rows:
        cols = ["pair_set_id", "asset_a", "asset_b", "hedge_ratio", "hedge_ratio_30d_avg", "hurst", "adf_pvalue", "is_tradeable"]
        return dict(zip(cols, rows[0]))
    return None


def get_all_pair_params() -> list[dict]:
    rows = _query("""
        SELECT pair_set_id, asset_a, asset_b, hedge_ratio, hedge_ratio_30d_avg,
               last_calculated, spread_mean, spread_std, hurst, adf_pvalue, is_tradeable, notes
        FROM poseidon_pair_params ORDER BY pair_set_id
    """)
    cols = ["pair_set_id", "asset_a", "asset_b", "hedge_ratio", "hedge_ratio_30d_avg",
            "last_calculated", "spread_mean", "spread_std", "hurst", "adf_pvalue", "is_tradeable", "notes"]
    return [dict(zip(cols, r)) for r in rows]


def get_poseidon_equity() -> float:
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT equity_usd FROM poseidon_portfolio WHERE id = 7")
                row = cur.fetchone()
                return float(row[0]) if row else 100_000.0
    except Exception:
        return 100_000.0
