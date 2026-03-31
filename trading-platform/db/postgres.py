"""
PostgreSQL Connection Layer
-----------------------------
Provides a thread-safe connection pool backed by Replit's managed
PostgreSQL database.  All schema definitions live here so that every
module (trade_journal, profit_sweep, ratchet_stop) can share tables.

Environment variables (set automatically by Replit):
  DATABASE_URL  — postgres://user:pass@host:port/dbname
  PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE  (individual vars)

Fallback: if PostgreSQL is unreachable, is_pg_available() returns False
and callers transparently fall back to SQLite.  This preserves local
development compatibility.

Tables managed here
-------------------
  trades
  performance_snapshots
  vault_ledger
  ratchet_stops
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from loguru import logger

try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False
    logger.warning("DB | psycopg2 not installed — PostgreSQL unavailable, using SQLite fallback")


# ── Connection pool ────────────────────────────────────────────────────────

_pool: "pg_pool.ThreadedConnectionPool | None" = None
_pg_ok: bool = False


def _get_dsn() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST")
    if host:
        return (
            f"postgresql://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
            f"@{host}:{os.environ.get('PGPORT', 5432)}/{os.environ['PGDATABASE']}"
        )
    return None


def _init_pool() -> None:
    global _pool, _pg_ok
    if not _PSYCOPG2_AVAILABLE:
        return
    dsn = _get_dsn()
    if dsn is None:
        logger.warning("DB | No DATABASE_URL found — using SQLite fallback")
        return
    try:
        _pool = pg_pool.ThreadedConnectionPool(minconn=1, maxconn=8, dsn=dsn)
        _pg_ok = True
        logger.info("DB | PostgreSQL connection pool initialised (min=1, max=8)")
    except Exception as exc:
        logger.error(f"DB | Failed to create PostgreSQL pool: {exc} — falling back to SQLite")
        _pg_ok = False


# Initialise on import
_init_pool()


def is_pg_available() -> bool:
    return _pg_ok and _pool is not None


@contextmanager
def get_conn() -> "Generator[psycopg2.extensions.connection, None, None]":
    """
    Yield a psycopg2 connection from the pool.
    Commits on success, rolls back on exception, returns conn to pool on exit.
    Raises RuntimeError if PostgreSQL is not available.
    """
    if not is_pg_available():
        raise RuntimeError("PostgreSQL is not available")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ── Schema bootstrap ───────────────────────────────────────────────────────

_SCHEMA_SQL = """
-- Trade journal
CREATE TABLE IF NOT EXISTS trades (
    trade_id          TEXT PRIMARY KEY,
    date              DATE NOT NULL,
    ticker            TEXT NOT NULL,
    asset_class       TEXT NOT NULL,
    conviction_score  DOUBLE PRECISION NOT NULL,
    original_thesis   TEXT NOT NULL,
    pnl_percentage    DOUBLE PRECISION,
    status            TEXT NOT NULL DEFAULT 'Active',
    intended_price    DOUBLE PRECISION,
    actual_fill_price DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_trades_status_date ON trades (status, date DESC);

-- Performance snapshots
CREATE TABLE IF NOT EXISTS performance_snapshots (
    date               DATE PRIMARY KEY,
    equity             DOUBLE PRECISION NOT NULL,
    daily_pnl_pct      DOUBLE PRECISION NOT NULL,
    cumulative_pnl_pct DOUBLE PRECISION NOT NULL,
    win_rate           DOUBLE PRECISION NOT NULL,
    trades_placed      INTEGER NOT NULL DEFAULT 0
);

-- Vault ledger (single row, id = 1)
CREATE TABLE IF NOT EXISTS vault_ledger (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    hwm                   DOUBLE PRECISION NOT NULL,
    total_vaulted_usd     DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_sweeps          INTEGER NOT NULL DEFAULT 0,
    vault_symbol          TEXT NOT NULL DEFAULT 'JEPQ',
    last_sweep_date       DATE,
    last_sweep_amount     DOUBLE PRECISION,
    da_adjustment         DOUBLE PRECISION NOT NULL DEFAULT 0
);

-- Ratchet stops
CREATE TABLE IF NOT EXISTS ratchet_stops (
    symbol        TEXT PRIMARY KEY,
    stop_price    DOUBLE PRECISION NOT NULL,
    fill_price    DOUBLE PRECISION NOT NULL,
    atr           DOUBLE PRECISION NOT NULL,
    last_updated  DATE NOT NULL
);

-- Position entry timestamps (immutable — written once per symbol when first opened,
-- never updated on ratchet/stop changes; used by 5-day 3× inverse ETF forced-exit)
CREATE TABLE IF NOT EXISTS position_entry_times (
    symbol       TEXT PRIMARY KEY,
    entry_ts     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_price  DOUBLE PRECISION
);

-- Equity snapshots (time-series portfolio value for equity curve chart)
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alpaca_equity  DOUBLE PRECISION NOT NULL,
    kraken_equity  DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_equity   DOUBLE PRECISION NOT NULL,
    regime         TEXT,
    source         TEXT NOT NULL DEFAULT 'pipeline'
);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_ts ON equity_snapshots (ts DESC);

-- ── AlgoEdge SaaS users ────────────────────────────────────────────────────
-- One row per registered SaaS user.
-- Stripe IDs are stored here; all subscription state is sourced from Stripe.
--
-- active_license_tier values:
--   NULL      → free / no active subscription
--   'tier1'   → Crypto Engine  ($19.96/4-weeks)  — Kraken access only
--   'tier2'   → Equities Engine ($39.96/4-weeks) — Alpaca access only
--   'tier3'   → Combined Hub   ($51.96/4-weeks)  — Kraken + Alpaca access
CREATE TABLE IF NOT EXISTS saas_users (
    id                    TEXT PRIMARY KEY,            -- Replit user ID or UUID
    email                 TEXT NOT NULL UNIQUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stripe_customer_id    TEXT,                        -- cus_...
    stripe_subscription_id TEXT,                       -- sub_...
    active_license_tier   TEXT CHECK (
        active_license_tier IN ('tier1', 'tier2', 'tier3')
    ),
    billing_cycle_end     TIMESTAMPTZ,                 -- next renewal date from Stripe
    tier_granted_at       TIMESTAMPTZ,                 -- when tier was last activated
    is_active             BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_saas_users_email       ON saas_users (email);
CREATE INDEX IF NOT EXISTS idx_saas_users_stripe_cust ON saas_users (stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_saas_users_tier        ON saas_users (active_license_tier);

-- ── System Degradation Log ─────────────────────────────────────────────────
-- Persistent record of every detected system failure or degradation event.
-- Written by the auto-heal monitor, HTTP middleware, and manual captures.
CREATE TABLE IF NOT EXISTS system_degradations (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    component    TEXT NOT NULL,   -- platform_core | data_pipeline | kraken_api | groq | alpaca | http
    severity     TEXT NOT NULL,   -- critical | error | warning
    error_type   TEXT NOT NULL,   -- stale | analysis_failed | rate_limit | 500 | connection | etc.
    message      TEXT NOT NULL,
    detail       TEXT,            -- extra context (stack trace excerpt, endpoint, etc.)
    resolved_at  TIMESTAMPTZ      -- filled in when a subsequent heal cycle succeeds
);
CREATE INDEX IF NOT EXISTS idx_sys_deg_ts        ON system_degradations (ts DESC);
CREATE INDEX IF NOT EXISTS idx_sys_deg_component ON system_degradations (component, ts DESC);

-- ── LLM Learning Journal ───────────────────────────────────────────────────
-- Consolidated insights extracted from every LLM analysis output.
-- Similar insights are merged (Jaccard ≥ 0.4); confirmed_count grows each time.
-- Top entries by confidence_score are injected back into future LLM prompts.
CREATE TABLE IF NOT EXISTS llm_learnings (
    id               BIGSERIAL PRIMARY KEY,
    insight_text     TEXT NOT NULL,
    regime           TEXT NOT NULL,          -- Bull / Bear / Sideways / Crypto
    category         TEXT NOT NULL,          -- macro / momentum / risk / position / crypto
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_count  INTEGER NOT NULL DEFAULT 1,
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.33
);
CREATE INDEX IF NOT EXISTS idx_llm_learnings_confidence ON llm_learnings (confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_llm_learnings_regime     ON llm_learnings (regime);

-- ── Execution Post-Mortems ──────────────────────────────────────────────────
-- Python-generated deterministic lessons written at the moment each trade
-- closes.  Phase 2 populates rows here; Phase 3 injects them into prompts;
-- Phase 4 promotes recurring lessons to permanent system-prompt rules.
CREATE TABLE IF NOT EXISTS execution_post_mortems (
    id                    BIGSERIAL PRIMARY KEY,
    ts                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ticker                TEXT NOT NULL,
    regime                TEXT NOT NULL,
    asset_class           TEXT,
    exit_reason           TEXT,
    pnl_pct               DOUBLE PRECISION,
    time_in_trade_hours   DOUBLE PRECISION,
    hardcoded_lesson_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_post_mortems_ts     ON execution_post_mortems (ts DESC);
CREATE INDEX IF NOT EXISTS idx_post_mortems_regime ON execution_post_mortems (regime, ticker);
"""

# Safe column migrations — run after CREATE TABLE IF NOT EXISTS so the base
# tables always exist first.  Each statement is idempotent (ADD COLUMN IF NOT EXISTS).
_MIGRATION_SQL = """
ALTER TABLE trades ADD COLUMN IF NOT EXISTS regime_at_entry      TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS time_in_trade_hours  DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_reason          TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS realized_pnl         DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS slippage_pct         DOUBLE PRECISION;
"""


def ensure_schema() -> None:
    """
    Create all tables if they don't already exist, then run safe column
    migrations.  Fully idempotent — safe to call on every startup.
    """
    if not is_pg_available():
        logger.debug("DB | ensure_schema skipped (PostgreSQL unavailable)")
        return
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
        logger.info("DB | PostgreSQL schema verified / created")
    except Exception as exc:
        logger.error(f"DB | Schema bootstrap failed: {exc}")
        return

    # Phase 1 RAG migrations: add new columns to trades table.
    # Each ALTER is idempotent via ADD COLUMN IF NOT EXISTS.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for stmt in _MIGRATION_SQL.strip().splitlines():
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
        logger.info("DB | Trade journal column migrations applied")
    except Exception as exc:
        logger.error(f"DB | Migration failed (non-fatal): {exc}")


def insert_post_mortem(
    ticker: str,
    regime: str,
    hardcoded_lesson_text: str,
    asset_class: str | None = None,
    exit_reason: str | None = None,
    pnl_pct: float | None = None,
    time_in_trade_hours: float | None = None,
) -> bool:
    """
    Insert a deterministic post-mortem lesson into execution_post_mortems.
    Called by Phase 2 (post-mortem logger) after every trade close.
    Returns True on success.
    """
    if not is_pg_available():
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution_post_mortems
                        (ticker, regime, asset_class, exit_reason,
                         pnl_pct, time_in_trade_hours, hardcoded_lesson_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (ticker, regime, asset_class, exit_reason,
                     pnl_pct, time_in_trade_hours, hardcoded_lesson_text),
                )
        logger.debug(f"DB | Post-mortem logged: {ticker} [{regime}] — {hardcoded_lesson_text[:80]}")
        return True
    except Exception as exc:
        logger.error(f"DB | insert_post_mortem failed: {exc}")
        return False


def get_post_mortems(
    regime: str | None = None,
    ticker: str | None = None,
    asset_class: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Query execution_post_mortems with optional filters.
    Used by Phase 3 (context-aware prompt injection) and Phase 4 (rollup).
    """
    if not is_pg_available():
        return []
    conditions = []
    params: list = []
    if regime:
        conditions.append("regime = %s")
        params.append(regime)
    if ticker:
        conditions.append("ticker = %s")
        params.append(ticker)
    if asset_class:
        conditions.append("asset_class = %s")
        params.append(asset_class)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    try:
        cols = ("id", "ts", "ticker", "regime", "asset_class", "exit_reason",
                "pnl_pct", "time_in_trade_hours", "hardcoded_lesson_text")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {', '.join(cols)}
                    FROM   execution_post_mortems
                    {where}
                    ORDER  BY ts DESC
                    LIMIT  %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["ts"] = d["ts"].isoformat() if d["ts"] else None
            result.append(d)
        return result
    except Exception as exc:
        logger.error(f"DB | get_post_mortems failed: {exc}")
        return []


# ── Equity snapshots ───────────────────────────────────────────────────────

def insert_equity_snapshot(
    alpaca_equity: float,
    kraken_equity: float = 0.0,
    regime: str | None = None,
    source: str = "pipeline",
) -> bool:
    """
    Insert a portfolio equity snapshot for the equity curve chart.
    Returns True on success, False if PostgreSQL is unavailable or write fails.
    """
    if not is_pg_available():
        return False
    total = alpaca_equity + kraken_equity
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO equity_snapshots
                        (alpaca_equity, kraken_equity, total_equity, regime, source)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (alpaca_equity, kraken_equity, total, regime, source),
                )
        logger.debug(
            f"DB | Equity snapshot: alpaca={alpaca_equity:.2f} kraken={kraken_equity:.2f} "
            f"total={total:.2f} regime={regime} source={source}"
        )
        return True
    except Exception as exc:
        logger.error(f"DB | insert_equity_snapshot failed: {exc}")
        return False


def get_equity_curve(limit: int = 500) -> list[dict]:
    """
    Return the last `limit` equity snapshots sorted ascending by timestamp
    (oldest first, so charts render left-to-right in chronological order).
    """
    if not is_pg_available():
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, ts AT TIME ZONE 'UTC' AS ts,
                           alpaca_equity, kraken_equity, total_equity, regime, source
                    FROM equity_snapshots
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        cols = ["id", "ts", "alpaca_equity", "kraken_equity", "total_equity", "regime", "source"]
        result = []
        for row in reversed(rows):  # reverse to get ascending order
            d = dict(zip(cols, row))
            d["ts"] = d["ts"].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.error(f"DB | get_equity_curve failed: {exc}")
        return []


def record_position_entry(symbol: str, entry_price: float | None = None) -> None:
    """
    Persist an immutable entry timestamp for *symbol*.
    Uses INSERT ... ON CONFLICT DO NOTHING so only the FIRST call records
    the timestamp — subsequent ratchet updates never overwrite it.
    Call this once when a new position is opened (bear_hedge buy or algo short).
    """
    if not is_pg_available():
        return  # SQLite fallback: skip (time-exit will gracefully return 0 days)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO position_entry_times (symbol, entry_price)
                    VALUES (%s, %s)
                    ON CONFLICT (symbol) DO NOTHING
                    """,
                    (symbol, entry_price),
                )
    except Exception as exc:
        logger.warning(f"DB | record_position_entry failed for {symbol}: {exc}")


def get_position_entry_times() -> dict[str, str]:
    """
    Returns {symbol: entry_ts_iso_string} for all symbols in position_entry_times.
    entry_ts is a TIMESTAMPTZ stored as UTC; returned as ISO-8601 string.
    """
    if not is_pg_available():
        return {}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT symbol, entry_ts AT TIME ZONE 'UTC' FROM position_entry_times")
                return {row[0]: row[1].isoformat() for row in cur.fetchall()}
    except Exception as exc:
        logger.warning(f"DB | get_position_entry_times failed: {exc}")
        return {}


def delete_position_entry(symbol: str) -> None:
    """Remove entry timestamp when a position is fully closed."""
    if not is_pg_available():
        return
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM position_entry_times WHERE symbol = %s", (symbol,))
    except Exception as exc:
        logger.warning(f"DB | delete_position_entry failed for {symbol}: {exc}")
