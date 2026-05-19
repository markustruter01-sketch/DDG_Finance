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
        _pool = pg_pool.ThreadedConnectionPool(minconn=2, maxconn=20, dsn=dsn)
        _pg_ok = True
        logger.info("DB | PostgreSQL connection pool initialised (min=2, max=20)")
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

-- ── Phase 4: Permanent Hardcoded Rules ─────────────────────────────────────
-- Recurring failure patterns (>= 3 occurrences) are promoted to permanent
-- rules that are injected into EVERY LLM system prompt.  The rollup job
-- upserts rows here; prompt injection reads only active=TRUE rows.
CREATE TABLE IF NOT EXISTS hardcoded_rules (
    id            BIGSERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    regime        TEXT NOT NULL,
    asset_class   TEXT,
    exit_reason   TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 3,
    rule_text     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (ticker, regime, exit_reason)
);
CREATE INDEX IF NOT EXISTS idx_hardcoded_rules_active ON hardcoded_rules (active, regime);

-- ── Kraken Bot PostgreSQL State ────────────────────────────────────────────
-- Single-row heartbeat (id=1) upserted by the bot every cycle.
-- The auto-heal monitor reads last_updated here; no JSON file parsing needed.
CREATE TABLE IF NOT EXISTS kraken_heartbeat (
    id              INTEGER PRIMARY KEY,
    bot_id          TEXT             DEFAULT 'davy-jones',
    status          TEXT    NOT NULL DEFAULT 'not_started',
    cycle_count     INTEGER NOT NULL DEFAULT 0,
    equity_usd      DOUBLE PRECISION NOT NULL DEFAULT 0,
    position_count  INTEGER NOT NULL DEFAULT 0,
    paper_trading   BOOLEAN NOT NULL DEFAULT TRUE,
    bot_paused      BOOLEAN NOT NULL DEFAULT FALSE,
    circuit_breaker JSONB,
    error           TEXT,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-bot portfolio state, keyed by canonical bot_id.
CREATE TABLE IF NOT EXISTS kraken_portfolio (
    id                   INTEGER PRIMARY KEY,
    starting_balance_usd DOUBLE PRECISION NOT NULL DEFAULT 100000,
    cash_usd             DOUBLE PRECISION NOT NULL DEFAULT 100000,
    positions            JSONB NOT NULL DEFAULT '{}'
);

-- Append-only trade history for Davy Jones' Portfolio paper trades.
CREATE TABLE IF NOT EXISTS kraken_trades (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT             NOT NULL,
    side        TEXT             NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_price  DOUBLE PRECISION NOT NULL,
    pnl_pct     DOUBLE PRECISION NOT NULL,
    pnl_usd     DOUBLE PRECISION NOT NULL,
    fees_usd    DOUBLE PRECISION,
    reason      TEXT,
    closed_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    paper       BOOLEAN          NOT NULL DEFAULT TRUE,
    order_id    TEXT,
    bot_id      TEXT             DEFAULT 'davy-jones'
);
CREATE INDEX IF NOT EXISTS idx_kraken_trades_closed_at ON kraken_trades (closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_kraken_trades_bot_id ON kraken_trades (bot_id);
-- Audit fix H4: prevent duplicate inserts on retry. Partial index — only
-- enforced when order_id IS NOT NULL so legacy paper rows w/o order_id
-- remain valid.
-- Pre-index dedupe: collapse any pre-existing (bot_id, order_id) duplicates
-- (keep the lowest id) so unique-index creation can't fail on legacy data.
DELETE FROM kraken_trades a
 USING kraken_trades b
 WHERE a.order_id IS NOT NULL
   AND a.bot_id = b.bot_id
   AND a.order_id = b.order_id
   AND a.id > b.id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_kraken_trades_bot_order
    ON kraken_trades (bot_id, order_id) WHERE order_id IS NOT NULL;

-- Multi-bot adaptive params upserted by adaptive_params.py every adaptation cycle.
CREATE TABLE IF NOT EXISTS kraken_adaptive_params (
    id          INTEGER PRIMARY KEY,
    bot_id      TEXT,
    params      JSONB NOT NULL DEFAULT '{}',
    metrics     JSONB,
    reasons     JSONB,
    adapted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lookback_n  INTEGER NOT NULL DEFAULT 0
);

-- ── Oracle Scan Log ─────────────────────────────────────────────────────────
-- Persists a diagnostic row every time the Oracle momentum scan runs.
-- Each row captures how many tickers passed each filter stage so operators
-- can diagnose zero-signal cycles without trawling server logs.
CREATE TABLE IF NOT EXISTS oracle_scan_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    universe_loaded INTEGER NOT NULL DEFAULT 0,
    with_data       INTEGER NOT NULL DEFAULT 0,
    passed_score    INTEGER NOT NULL DEFAULT 0,
    passed_rsi      INTEGER NOT NULL DEFAULT 0,
    passed_ema      INTEGER NOT NULL DEFAULT 0,
    long_signals    INTEGER NOT NULL DEFAULT 0,
    short_signals   INTEGER NOT NULL DEFAULT 0,
    top5_long       JSONB,
    top5_short      JSONB,
    scan_note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_oracle_scan_log_ts ON oracle_scan_log (ts DESC);

-- Fleet Commander chat history (Gemini-powered fleet management).
CREATE TABLE IF NOT EXISTS fleet_commander_chat (
    id          TEXT PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'user',
    metadata    JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_fleet_chat_ts ON fleet_commander_chat (ts DESC);

-- Capital injections tracking (prevents injection events from appearing as P&L)
CREATE TABLE IF NOT EXISTS capital_injections (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pool        TEXT NOT NULL,
    amount_usd  DOUBLE PRECISION NOT NULL,
    reason      TEXT,
    bot_id      TEXT
);
-- Audit fix M4: speed up per-bot capital-injection lookups (bot reconciliation).
CREATE INDEX IF NOT EXISTS idx_capital_injections_bot
    ON capital_injections (bot_id, ts DESC);
-- Audit fix M4: support nightly retention sweep on historical_prices —
-- existing index is (pair, timeframe, timestamp); we need a (timeframe, ts)
-- index so DELETE WHERE timeframe='1h' AND timestamp<... doesn't full-scan.
CREATE INDEX IF NOT EXISTS idx_historical_prices_tf_ts
    ON historical_prices (timeframe, "timestamp");

-- VPIN rejection log (persistent record of VPIN-blocked entries)
CREATE TABLE IF NOT EXISTS vpin_rejections (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_id      TEXT NOT NULL,
    pair        TEXT NOT NULL,
    vpin_value  DOUBLE PRECISION NOT NULL,
    threshold   DOUBLE PRECISION NOT NULL,
    direction   TEXT NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_vpin_rejections_ts ON vpin_rejections (ts DESC);
CREATE INDEX IF NOT EXISTS idx_vpin_rejections_bot ON vpin_rejections (bot_id);

-- Oracle Profit Reserve ledger (non-invested cash buffer — 15% of winning trade profits)
CREATE TABLE IF NOT EXISTS oracle_profit_reserve (
    id                   BIGSERIAL PRIMARY KEY,
    ts                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    contribution_usd     DOUBLE PRECISION NOT NULL,
    trade_profit_usd     DOUBLE PRECISION NOT NULL,
    ticker               TEXT,
    cumulative_total_usd DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_oracle_profit_reserve_ts ON oracle_profit_reserve (ts DESC);

-- Stage 5: Walk-Forward Optimiser results (one row per bot per weekly run)
CREATE TABLE IF NOT EXISTS kraken_wfo_results (
    id                  BIGSERIAL PRIMARY KEY,
    bot_id              TEXT NOT NULL,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data_from           TIMESTAMPTZ,
    data_to             TIMESTAMPTZ,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    windows_analysed    INTEGER NOT NULL DEFAULT 0,
    overall_confidence  TEXT NOT NULL DEFAULT 'LOW',
    stability_score     INTEGER NOT NULL DEFAULT 0,
    rec_sl_pct          DOUBLE PRECISION,
    rec_tp_pct          DOUBLE PRECISION,
    rec_best_regime     TEXT,
    rec_worst_regime    TEXT,
    rec_focus_symbols   JSONB NOT NULL DEFAULT '[]',
    rec_avoid_symbols   JSONB NOT NULL DEFAULT '[]',
    window_results      JSONB NOT NULL DEFAULT '[]',
    regime_breakdown    JSONB NOT NULL DEFAULT '{}',
    oos_validation      JSONB NOT NULL DEFAULT '{}',
    summary             TEXT
);
CREATE INDEX IF NOT EXISTS idx_kraken_wfo_bot ON kraken_wfo_results (bot_id, run_at DESC);

-- Stage 4: Strategy Health Monitor snapshots (one row per bot per daily run)
CREATE TABLE IF NOT EXISTS kraken_health_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    bot_id          TEXT NOT NULL,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    overall_score   INTEGER NOT NULL,
    overall_status  TEXT NOT NULL,
    metrics         JSONB NOT NULL DEFAULT '{}',
    recommendations JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_kraken_health_bot ON kraken_health_snapshots (bot_id, checked_at DESC);

-- Stage 6 (True Backtester): Historical OHLCV price data
-- Pairs: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
-- Timeframes: 1d (daily, ~2 years from Kraken public API), 1h (hourly, ~30 days)
CREATE TABLE IF NOT EXISTS historical_prices (
    id          BIGSERIAL PRIMARY KEY,
    pair        TEXT             NOT NULL,
    timeframe   TEXT             NOT NULL DEFAULT '1d',
    "timestamp" TIMESTAMPTZ      NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_prices_uq
    ON historical_prices (pair, timeframe, "timestamp");
CREATE INDEX IF NOT EXISTS idx_historical_prices_pair_ts
    ON historical_prices (pair, timeframe, "timestamp" DESC);
CREATE TABLE IF NOT EXISTS fleet_halt (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    active      BOOLEAN NOT NULL DEFAULT FALSE,
    reason      TEXT,
    halted_at   TIMESTAMPTZ,
    halted_by   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO fleet_halt (id, active) VALUES (1, FALSE) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS review_flags (
    id          BIGSERIAL PRIMARY KEY,
    flag_key    TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    due_date    DATE NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'medium',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_flags_status ON review_flags (status, due_date);

-- ── Unified Bot State Table ────────────────────────────────────────────────
-- Single source of truth for pause state, heartbeat, and status across all bots.
-- Replaces: poseidon_control.json, kc_control.json, navigator_control.json,
--           BOT_PAUSED in config.py, per-bot rows in kraken_heartbeat.
-- Legacy tables are kept during migration; bots dual-write to both.
CREATE TABLE IF NOT EXISTS bots_state (
  bot_id         TEXT PRIMARY KEY,
  paused         BOOLEAN NOT NULL DEFAULT FALSE,
  pause_reason   TEXT DEFAULT '',
  paused_at      TIMESTAMPTZ,
  status         TEXT NOT NULL DEFAULT 'idle',
  equity_usd     DOUBLE PRECISION DEFAULT 0,
  cash_usd       DOUBLE PRECISION DEFAULT 0,
  open_positions INTEGER DEFAULT 0,
  last_heartbeat TIMESTAMPTZ,
  last_trade_at  TIMESTAMPTZ,
  error_message  TEXT DEFAULT '',
  metadata       JSONB DEFAULT '{}'::jsonb
);

-- ── Bot Portfolio Table ────────────────────────────────────────────────────
-- Canonical per-bot portfolio state: cash, equity, open positions.
-- Replaces scattered JSON state files and kraken_portfolio rows as source of truth.
-- bot_id uses canonical registry IDs (spy_qqq_trend, jerome_macro, etc.)
CREATE TABLE IF NOT EXISTS bot_portfolio (
  bot_id         TEXT PRIMARY KEY,
  starting_usd   DOUBLE PRECISION NOT NULL DEFAULT 100000,
  cash_usd       DOUBLE PRECISION NOT NULL DEFAULT 100000,
  equity_usd     DOUBLE PRECISION NOT NULL DEFAULT 100000,
  positions      JSONB NOT NULL DEFAULT '[]'::jsonb,
  last_updated   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_live_broker BOOLEAN NOT NULL DEFAULT FALSE,
  data_source    TEXT NOT NULL DEFAULT 'unknown'
);

INSERT INTO bot_portfolio (bot_id, starting_usd, cash_usd, equity_usd, positions, data_source, is_live_broker)
VALUES
  ('oracle',            100000, 100000, 100000, '[]'::jsonb, 'alpaca_api',   FALSE),
  ('spy_qqq_trend',     100000, 100000, 100000, '[]'::jsonb, 'alpaca_api',   FALSE),
  ('jerome_macro',      100000, 100000, 100000, '[]'::jsonb, 'alpaca_api',   FALSE),
  ('forex_gump',        100000, 100000, 100000, '[]'::jsonb, 'internal_sim', FALSE),
  ('depeg_hunter',      100000, 100000, 100000, '[]'::jsonb, 'internal_sim', FALSE),
  ('event_trader',      100000, 100000, 100000, '[]'::jsonb, 'internal_sim', FALSE),
  ('listing_pump',      100000, 100000, 100000, '[]'::jsonb, 'internal_sim', FALSE),
  ('memecoin_velocity', 100000, 100000, 100000, '[]'::jsonb, 'internal_sim', FALSE)
ON CONFLICT (bot_id) DO NOTHING;

-- Listing dedup table — persists seen exchange:asset keys across restarts
-- so crypto-signals doesn't re-inject the full CoinGecko catalogue on restart.
CREATE TABLE IF NOT EXISTS listing_dedup (
    key        TEXT PRIMARY KEY,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Safe column migrations — run after CREATE TABLE IF NOT EXISTS so the base
# tables always exist first.  Each statement is idempotent (ADD COLUMN IF NOT EXISTS).
_MIGRATION_SQL = """
ALTER TABLE trades ADD COLUMN IF NOT EXISTS regime_at_entry      TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS time_in_trade_hours  DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_reason          TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS realized_pnl         DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS slippage_pct         DOUBLE PRECISION;
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS options_equity        DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS forex_equity          DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS poseidon_equity       DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS kraken_current_equity DOUBLE PRECISION NOT NULL DEFAULT 0;
"""

# Data-only backfill: safe to run repeatedly (idempotent WHERE clause)
_BACKFILL_SQL = """
UPDATE trades
SET exit_reason = 'algo_cover'
WHERE exit_reason IS NULL
  AND status IN ('Closed_Win', 'Closed_Loss', 'Closed');
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

    # Backfill exit_reason for historical Oracle closed trades (idempotent)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_BACKFILL_SQL.strip())
                updated = cur.rowcount
        if updated:
            logger.info(f"DB | Backfilled exit_reason for {updated} historical Oracle trade(s)")
    except Exception as exc:
        logger.warning(f"DB | exit_reason backfill failed (non-fatal): {exc}")

    # Seed bots_state with canonical bot IDs and known pause states (idempotent)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bots_state (bot_id, paused, pause_reason, equity_usd, last_heartbeat)
                    VALUES
                      ('oracle',              FALSE, '', 0, NULL),
                      ('spy_qqq_trend',       FALSE, '', 0, NULL),
                      ('jerome_macro',        FALSE, '', 0, NULL),

                      ('forex_gump',          TRUE,  'Exit logic broken — 43 stuck open positions', 0, NULL),
                      ('poseidon_momentum',   TRUE,  '0% win rate over 6 trades — strategy broken', 0, NULL),
                      ('kraken_trend',        TRUE,  'Strategy broken — -$4,200 net, 34% WR over 32 trades', 0, NULL)
                    ON CONFLICT (bot_id) DO NOTHING;
                """)
        logger.info("DB | bots_state seed complete")
    except Exception as exc:
        logger.warning(f"DB | bots_state seed failed (non-fatal): {exc}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE kraken_trades ADD COLUMN IF NOT EXISTS bot_id TEXT DEFAULT 'davy-jones'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kraken_trades_bot_id ON kraken_trades (bot_id)")
                cur.execute("ALTER TABLE kraken_adaptive_params DROP CONSTRAINT IF EXISTS kraken_adaptive_params_id_check")
                cur.execute("ALTER TABLE kraken_adaptive_params ADD COLUMN IF NOT EXISTS bot_id TEXT")
                cur.execute("ALTER TABLE kraken_heartbeat ADD COLUMN IF NOT EXISTS bot_id TEXT DEFAULT 'davy-jones'")
                cur.execute("ALTER TABLE kraken_heartbeat DROP CONSTRAINT IF EXISTS kraken_heartbeat_id_check")
                cur.execute("ALTER TABLE kraken_portfolio DROP CONSTRAINT IF EXISTS kraken_portfolio_id_check")
        logger.info("DB | Kraken multi-bot migrations applied")
    except Exception as exc:
        logger.error(f"DB | Kraken multi-bot migration failed (non-fatal): {exc}")

    # One-time cleanup — remove retired bots from bot_portfolio.
    # These got re-inserted at some point despite earlier removal.
    # Strip in publish #2.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM bot_portfolio
                    WHERE bot_id IN ('poseidon_momentum', 'kraken_trend')
                """)
                _n = cur.rowcount
        if _n:
            logger.info(f"DB | removed {_n} retired bot_portfolio rows (re-cleanup)")
    except Exception as exc:
        logger.warning(f"DB | retired bot cleanup failed (non-fatal): {exc}")

    # Phase A — Unified accounting layer rebuild (2026-05-19), part 1: additive columns only.
    # Adds new columns alongside existing schema. Phase D updates writers/readers.
    # Phase E drops legacy columns (updated_at, metadata) and makes data_source NOT NULL.
    # Strip THIS block in publish #2 alongside the retired-bot cleanup at L616-629.
    try:
        with get_conn() as _bp_conn:
            with _bp_conn.cursor() as _bp_cur:
                _bp_cur.execute("""
                    ALTER TABLE bot_portfolio
                    ADD COLUMN IF NOT EXISTS is_live_broker BOOLEAN NOT NULL DEFAULT FALSE
                """)
                _bp_cur.execute("""
                    ALTER TABLE bot_portfolio
                    ADD COLUMN IF NOT EXISTS data_source TEXT
                """)
                _bp_cur.execute("""
                    ALTER TABLE bot_portfolio
                    ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ
                """)
                logger.info("DB | Phase A: added is_live_broker + data_source + last_updated columns")

                # Backfill data_source for the 8 bots based on Alpaca vs internal sim.
                # Safe to run repeatedly — only updates rows where data_source is NULL.
                _bp_cur.execute("""
                    UPDATE bot_portfolio SET data_source = 'alpaca_api'
                    WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                      AND data_source IS NULL
                """)
                _bp_cur.execute("""
                    UPDATE bot_portfolio SET data_source = 'internal_sim'
                    WHERE bot_id IN ('forex_gump', 'depeg_hunter', 'event_trader',
                                     'listing_pump', 'memecoin_velocity')
                      AND data_source IS NULL
                """)

                # Backfill last_updated from existing updated_at for any rows where it's NULL.
                _bp_cur.execute("""
                    UPDATE bot_portfolio SET last_updated = updated_at
                    WHERE last_updated IS NULL
                """)
                logger.info("DB | Phase A: backfilled data_source + last_updated")

                # Insert any missing wild bots that weren't in the original seed.
                # ON CONFLICT DO NOTHING — never overwrites existing rows.
                _bp_cur.execute("""
                    INSERT INTO bot_portfolio
                        (bot_id, starting_usd, cash_usd, positions, equity_usd, updated_at,
                         metadata, last_updated, is_live_broker, data_source)
                    VALUES
                        ('depeg_hunter',      100000, 100000, '[]'::jsonb, 100000, NOW(), '{}'::jsonb, NOW(), FALSE, 'internal_sim'),
                        ('event_trader',      100000, 100000, '[]'::jsonb, 100000, NOW(), '{}'::jsonb, NOW(), FALSE, 'internal_sim'),
                        ('listing_pump',      100000, 100000, '[]'::jsonb, 100000, NOW(), '{}'::jsonb, NOW(), FALSE, 'internal_sim'),
                        ('memecoin_velocity', 100000, 100000, '[]'::jsonb, 100000, NOW(), '{}'::jsonb, NOW(), FALSE, 'internal_sim')
                    ON CONFLICT (bot_id) DO NOTHING
                """)
                logger.info("DB | Phase A: ensured all 8 bots have rows")
    except Exception as _bp_exc:
        logger.error(f"DB | Phase A migration failed: {_bp_exc}")
        raise

    # Phase E2a — DROP COLUMN bot_portfolio.updated_at and bot_portfolio.metadata.
    # Both columns are dead post-E1 (zero writers, zero readers verified).
    # Strip THIS block in publish #2.
    try:
        with get_conn() as _e2_conn:
            with _e2_conn.cursor() as _e2_cur:
                _e2_cur.execute("ALTER TABLE bot_portfolio DROP COLUMN IF EXISTS updated_at")
                logger.info("DB | Phase E2a: dropped bot_portfolio.updated_at")
    except Exception as _e2_exc:
        logger.error(f"DB | Phase E2a updated_at drop failed: {_e2_exc}")
    try:
        with get_conn() as _e2_conn:
            with _e2_conn.cursor() as _e2_cur:
                _e2_cur.execute("ALTER TABLE bot_portfolio DROP COLUMN IF EXISTS metadata")
                logger.info("DB | Phase E2a: dropped bot_portfolio.metadata")
    except Exception as _e2_exc:
        logger.error(f"DB | Phase E2a metadata drop failed: {_e2_exc}")


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


# ── Phase 4: Permanent Hardcoded Rules ─────────────────────────────────────

def upsert_hardcoded_rule(
    ticker: str,
    regime: str,
    asset_class: str | None,
    exit_reason: str,
    failure_count: int,
    rule_text: str,
) -> bool:
    """
    Insert a new permanent rule or update failure_count + rule_text + updated_at
    if the (ticker, regime, exit_reason) key already exists.
    Returns True on success.
    """
    if not is_pg_available():
        return False
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hardcoded_rules
                        (ticker, regime, asset_class, exit_reason,
                         failure_count, rule_text)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, regime, exit_reason) DO UPDATE SET
                        failure_count = EXCLUDED.failure_count,
                        rule_text     = EXCLUDED.rule_text,
                        updated_at    = NOW(),
                        active        = TRUE
                    """,
                    (ticker, regime, asset_class, exit_reason,
                     failure_count, rule_text),
                )
        logger.debug(
            f"DB | Hardcoded rule upserted: {ticker} [{regime}/{exit_reason}] "
            f"count={failure_count}"
        )
        return True
    except Exception as exc:
        logger.error(f"DB | upsert_hardcoded_rule failed: {exc}")
        return False


def get_hardcoded_rules(regime: str | None = None) -> list[dict]:
    """
    Fetch active permanent rules, optionally filtered by regime.
    Returns rows ordered by failure_count DESC (most severe patterns first).
    """
    if not is_pg_available():
        return []
    try:
        conditions = ["active = TRUE"]
        params: list = []
        if regime:
            conditions.append("regime = %s")
            params.append(regime)
        where = "WHERE " + " AND ".join(conditions)
        params.append(100)  # hard limit: never inject more than 100 rules
        cols = ("id", "ticker", "regime", "asset_class", "exit_reason",
                "failure_count", "rule_text", "updated_at")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {', '.join(cols)}
                    FROM   hardcoded_rules
                    {where}
                    ORDER  BY failure_count DESC, updated_at DESC
                    LIMIT  %s
                    """,
                    params,
                )
                rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get("updated_at"):
                d["updated_at"] = d["updated_at"].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.error(f"DB | get_hardcoded_rules failed: {exc}")
        return []


def get_kraken_equity() -> float:
    """
    Return combined equity for the 3 original Kraken swing bots only
    (Davy Jones id=1, Blackbeard id=2, Calypso id=3).
    Poseidon (id=7) and Kraken Current (id=8) have their own dedicated
    equity columns in equity_snapshots — do NOT include them here or
    the total_equity will double-count them.
    """
    if not is_pg_available():
        return 0.0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(SUM(equity_usd), 0) FROM kraken_heartbeat "
                    "WHERE id IN (1, 2, 3)"
                )
                row = cur.fetchone()
                return float(row[0]) if row else 0.0
    except Exception as exc:
        logger.error(f"DB | get_kraken_equity failed: {exc}")
        return 0.0


# ── Equity snapshots ───────────────────────────────────────────────────────

def insert_equity_snapshot(
    alpaca_equity: float,
    kraken_equity: float = 0.0,
    regime: str | None = None,
    source: str = "pipeline",
    options_equity: float = 0.0,
    forex_equity: float = 0.0,
    poseidon_equity: float = 0.0,
    kraken_current_equity: float = 0.0,
) -> bool:
    """
    Insert a portfolio equity snapshot for the equity curve chart.
    Returns True on success, False if PostgreSQL is unavailable or write fails.
    """
    if not is_pg_available():
        return False
    total = alpaca_equity + kraken_equity + options_equity + forex_equity + poseidon_equity + kraken_current_equity
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO equity_snapshots
                        (alpaca_equity, kraken_equity, options_equity, forex_equity,
                         poseidon_equity, kraken_current_equity, total_equity, regime, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (alpaca_equity, kraken_equity, options_equity, forex_equity,
                     poseidon_equity, kraken_current_equity, total, regime, source),
                )
        logger.debug(
            f"DB | Equity snapshot: alpaca={alpaca_equity:.2f} kraken={kraken_equity:.2f} "
            f"options={options_equity:.2f} forex={forex_equity:.2f} "
            f"poseidon={poseidon_equity:.2f} kc={kraken_current_equity:.2f} "
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
                           alpaca_equity, kraken_equity,
                           COALESCE(options_equity, 0) AS options_equity,
                           COALESCE(forex_equity, 0) AS forex_equity,
                           COALESCE(poseidon_equity, 0) AS poseidon_equity,
                           COALESCE(kraken_current_equity, 0) AS kraken_current_equity,
                           total_equity, regime, source
                    FROM equity_snapshots
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        cols = ["id", "ts", "alpaca_equity", "kraken_equity", "options_equity", "forex_equity",
                "poseidon_equity", "kraken_current_equity", "total_equity", "regime", "source"]
        result = []
        for row in reversed(rows):
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


def add_oracle_profit_contribution(
    trade_profit_usd: float,
    ticker: str | None = None,
) -> float:
    """
    Add 15% of a winning Oracle trade's profit to the Oracle Profit Reserve.

    Parameters
    ----------
    trade_profit_usd : gross profit from the closed trade (must be > 0)
    ticker           : optional symbol of the closed trade (for audit trail)

    Returns
    -------
    float : the new cumulative total of the reserve (0.0 on error)
    """
    if trade_profit_usd <= 0:
        return 0.0
    contribution = round(trade_profit_usd * 0.15, 2)
    if not is_pg_available():
        logger.info(f"OraclePR | DB unavailable — skipping reserve contribution ${contribution:.2f}")
        return 0.0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(cumulative_total_usd), 0) FROM oracle_profit_reserve"
                )
                current_total = float(cur.fetchone()[0] or 0.0)
                new_total = round(current_total + contribution, 2)
                cur.execute(
                    """
                    INSERT INTO oracle_profit_reserve
                        (contribution_usd, trade_profit_usd, ticker, cumulative_total_usd)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (contribution, trade_profit_usd, ticker, new_total),
                )
        logger.info(
            f"OraclePR | +${contribution:.2f} (15% of ${trade_profit_usd:.2f} profit"
            f"{' on ' + ticker if ticker else ''}) → cumulative ${new_total:,.2f}"
        )
        return new_total
    except Exception as exc:
        logger.error(f"OraclePR | add_oracle_profit_contribution failed: {exc}")
        return 0.0


def get_oracle_profit_reserve() -> dict:
    """
    Return the current Oracle Profit Reserve balance.

    Returns
    -------
    dict with:
        "total_usd"         : float  — cumulative reserve
        "contributions"     : int    — number of contributions
        "last_contribution" : float  — most recent contribution amount
        "last_ts"           : str    — ISO timestamp of most recent entry
    """
    if not is_pg_available():
        return {"total_usd": 0.0, "contributions": 0, "last_contribution": 0.0, "last_ts": None}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(MAX(cumulative_total_usd), 0)   AS total_usd,
                        COUNT(*)                                  AS contributions,
                        COALESCE(
                            (SELECT contribution_usd FROM oracle_profit_reserve
                             ORDER BY ts DESC LIMIT 1), 0
                        )                                         AS last_contribution,
                        (SELECT ts AT TIME ZONE 'UTC' FROM oracle_profit_reserve
                         ORDER BY ts DESC LIMIT 1)               AS last_ts
                    FROM oracle_profit_reserve
                    """
                )
                row = cur.fetchone()
                if not row:
                    return {"total_usd": 0.0, "contributions": 0, "last_contribution": 0.0, "last_ts": None}
                return {
                    "total_usd":         round(float(row[0] or 0.0), 2),
                    "contributions":     int(row[1] or 0),
                    "last_contribution": round(float(row[2] or 0.0), 2),
                    "last_ts":           row[3].isoformat() if row[3] else None,
                }
    except Exception as exc:
        logger.error(f"OraclePR | get_oracle_profit_reserve failed: {exc}")
        return {"total_usd": 0.0, "contributions": 0, "last_contribution": 0.0, "last_ts": None}
