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
  alpaca_etf_positions
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


def _acquire_healthy_conn() -> "psycopg2.extensions.connection":
    """
    Pull a connection from the pool, validating it is genuinely alive.

    Two distinct failure modes require two distinct checks:

      1. conn.closed != 0 — psycopg2 has already marked this connection as
         closed on the client side (e.g. the pool returned one that exceeded
         minconn and was explicitly conn.close()'d).  Detectable immediately.

      2. conn.closed == 0 but the PostgreSQL server dropped it while it was
         idle between cycles (TCP keepalive / server idle-timeout).  psycopg2
         does NOT update conn.closed until it tries to send a query, so the
         only reliable way to detect this is a lightweight SELECT 1 ping.

    Stale connections are discarded with putconn(close=True) so the pool
    creates a fresh replacement.  Up to 3 attempts are made before raising.
    """
    for _ in range(3):
        conn = _pool.getconn()
        if conn.closed:
            try:
                _pool.putconn(conn, close=True)
            except Exception:
                pass
            continue
        try:
            with conn.cursor() as _cur:
                _cur.execute("SELECT 1")
            return conn
        except Exception:
            try:
                _pool.putconn(conn, close=True)
            except Exception:
                pass
    raise RuntimeError("DB | Could not acquire a live connection after 3 attempts")


@contextmanager
def get_conn() -> "Generator[psycopg2.extensions.connection, None, None]":
    """
    Yield a psycopg2 connection from the pool.
    Commits on success, rolls back on exception, returns conn to pool on exit.
    Raises RuntimeError if PostgreSQL is not available.

    Delegates connection acquisition to _acquire_healthy_conn() which handles
    both client-side and server-side stale-connection failure modes.
    """
    if not is_pg_available():
        raise RuntimeError("PostgreSQL is not available")
    conn = _acquire_healthy_conn()
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

-- Per-bot profit vault (additive, inactive until explicitly enabled).
-- This is deliberately separate from the retired global JEPQ/HWM ledger above.
CREATE TABLE IF NOT EXISTS per_bot_vault_accounts (
    bot_id                  TEXT PRIMARY KEY,
    activation_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    activation_equity       NUMERIC,
    seed_amount             NUMERIC NOT NULL DEFAULT 0,
    trading_capital         NUMERIC,
    bil_qty                 NUMERIC NOT NULL DEFAULT 0,
    voo_qty                 NUMERIC NOT NULL DEFAULT 0,
    cash_usd                NUMERIC NOT NULL DEFAULT 0,
    cumulative_contributions NUMERIC NOT NULL DEFAULT 0,
    last_rebalance_date     DATE,
    activated_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS per_bot_vault_contributions (
    id              BIGSERIAL PRIMARY KEY,
    bot_id          TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
    source_trade_id TEXT NOT NULL,
    realized_profit NUMERIC NOT NULL,
    skim_amount     NUMERIC NOT NULL,
    bil_allocated   NUMERIC NOT NULL DEFAULT 0,
    voo_allocated   NUMERIC NOT NULL DEFAULT 0,
    cash_accrued    NUMERIC NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bot_id, source_trade_id)
);
CREATE INDEX IF NOT EXISTS idx_per_bot_vault_contrib_bot_ts
    ON per_bot_vault_contributions (bot_id, created_at DESC);
CREATE TABLE IF NOT EXISTS per_bot_vault_value_history (
    id                       BIGSERIAL PRIMARY KEY,
    bot_id                   TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
    recorded_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_capital          NUMERIC NOT NULL,
    cumulative_contributions NUMERIC NOT NULL,
    vault_value              NUMERIC NOT NULL,
    vault_return_pct         NUMERIC NOT NULL DEFAULT 0,
    combined_total           NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_per_bot_vault_history_bot_ts
    ON per_bot_vault_value_history (bot_id, recorded_at DESC);
CREATE TABLE IF NOT EXISTS per_bot_vault_deployment_queue (
    bot_id           TEXT PRIMARY KEY REFERENCES per_bot_vault_accounts(bot_id),
    pending_cash_usd NUMERIC NOT NULL DEFAULT 0,
    pending_bil_usd  NUMERIC NOT NULL DEFAULT 0,
    pending_voo_usd  NUMERIC NOT NULL DEFAULT 0,
    bil_order_id     TEXT,
    voo_order_id     TEXT,
    bil_filled_usd   NUMERIC NOT NULL DEFAULT 0,
    voo_filled_usd   NUMERIC NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'pending',
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS per_bot_vault_holdings (
    bot_id         TEXT NOT NULL REFERENCES per_bot_vault_accounts(bot_id),
    symbol         TEXT NOT NULL CHECK (symbol IN ('BIL', 'VOO')),
    qty            NUMERIC NOT NULL DEFAULT 0,
    cost_basis_usd NUMERIC NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bot_id, symbol)
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

-- ETF execution ledger. stop_order_id is the owned broker-native GTC stop
-- reference for the open position; it must remain part of the canonical schema.
CREATE TABLE IF NOT EXISTS alpaca_etf_positions (
    id              BIGSERIAL     PRIMARY KEY,
    bot_id          TEXT          NOT NULL,
    symbol          TEXT          NOT NULL,
    direction       TEXT          NOT NULL DEFAULT 'long',
    qty             NUMERIC       NOT NULL,
    entry_price     NUMERIC       NOT NULL,
    entry_atr       NUMERIC,
    notional_usd    NUMERIC       NOT NULL,
    stop_price      NUMERIC,
    tp1_price       NUMERIC,
    tp2_price       NUMERIC,
    stop_order_id   TEXT,
    scaled_out_tp1  BOOLEAN       DEFAULT FALSE,
    scaled_out_tp2  BOOLEAN       DEFAULT FALSE,
    min_hold_until  TIMESTAMPTZ,
    status          TEXT          NOT NULL DEFAULT 'open',
    opened_at       TIMESTAMPTZ   DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    exit_reason     TEXT,
    realised_pnl    NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_etf_pos_status
    ON alpaca_etf_positions (bot_id, status, opened_at);

-- Equity snapshots (time-series portfolio value for equity curve chart)
-- Per-bot fleet equity snapshots used for mark-to-market 24h P&L.
CREATE TABLE IF NOT EXISTS fleet_equity_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    snapshot_ts    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_id         TEXT NOT NULL,
    equity_usd     NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fleet_equity_snapshots_ts
    ON fleet_equity_snapshots (snapshot_ts);
CREATE INDEX IF NOT EXISTS idx_fleet_equity_snapshots_bot_ts
    ON fleet_equity_snapshots (bot_id, snapshot_ts);

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

-- Automated safety and reconciliation audit tables.
CREATE TABLE IF NOT EXISTS kill_switch_events (
    id            BIGSERIAL PRIMARY KEY,
    trigger       TEXT NOT NULL,
    event_ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    account       TEXT,
    snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_taken  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kill_switch_events_ts ON kill_switch_events (event_ts DESC);

CREATE TABLE IF NOT EXISTS reconciliation_log (
    id            BIGSERIAL PRIMARY KEY,
    run_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    clean         BOOLEAN NOT NULL,
    flags         JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_reconciliation_log_ts ON reconciliation_log (run_ts DESC);

CREATE TABLE IF NOT EXISTS kill_switch_acknowledgements (
    condition_key       TEXT PRIMARY KEY,
    acknowledged_until  TIMESTAMPTZ NOT NULL,
    acknowledged_by     TEXT NOT NULL,
    reason              TEXT,
    acknowledged_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE kill_switch_acknowledgements ADD COLUMN IF NOT EXISTS reason TEXT;

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
  ('oracle',          100000, 100000, 100000, '[]'::jsonb, 'alpaca_api',   FALSE),
  ('spy_qqq_trend',   100000, 100000, 100000, '[]'::jsonb, 'alpaca_api',   FALSE),
  ('jerome_macro',    100000, 100000, 100000, '[]'::jsonb, 'alpaca_api',   FALSE)
ON CONFLICT (bot_id) DO NOTHING;

-- ── Market State Engine (MSE) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_state (
    id          SERIAL      PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    regime      TEXT        NOT NULL,   -- BULL | BEAR | CRISIS
    high_vol    BOOLEAN     NOT NULL DEFAULT FALSE,
    spy_close   NUMERIC,
    spy_20d_ret NUMERIC,
    spy_200sma  NUMERIC,
    spy_10d_vol NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_market_state_recorded_at
    ON market_state (recorded_at DESC);

-- ARC 4: Reconciliation event ledger — replaces RECON-* pseudo-trade rows.
-- Both reconcilers write here; trades table gets is_recon_tracking tag.
CREATE TABLE IF NOT EXISTS reconciliation_events (
    id                    BIGSERIAL PRIMARY KEY,
    event_type            TEXT NOT NULL,   -- orphan_close / recon_insert / race_phantom / empty_response_skip
    bot_id                TEXT NOT NULL,
    symbol                TEXT,
    trade_id_ref          TEXT,            -- trade_id of the trades row being described
    detail                TEXT,
    broker_state_snapshot JSONB,           -- snapshot of broker positions dict at event time
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_recon_events_bot_ts    ON reconciliation_events (bot_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recon_events_trade_ref ON reconciliation_events (trade_id_ref);

-- ARC 4: Shadow-signal ledger — decision data without execution.
-- One row per evaluated candidate per cycle; executed=TRUE if an order fired.
-- Retention: 90-day nightly sweep (see scheduler.py).
CREATE TABLE IF NOT EXISTS shadow_signals (
    id                    BIGSERIAL PRIMARY KEY,
    bot_id                TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    side                  TEXT,            -- long / short / buy
    signal_ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_price_at_signal DOUBLE PRECISION,
    score                 DOUBLE PRECISION,   -- bot-specific signal strength (ADX, EMA-score, etc.)
    conviction            DOUBLE PRECISION,   -- 0–1 conviction weight (jerome/buck)
    regime_at_signal      TEXT,
    executed              BOOLEAN NOT NULL DEFAULT FALSE,
    skip_reason           TEXT,              -- cap_full / regime_gate / crisis / cash / theme_cap / already_holding
    extra_context         JSONB             -- additional fields (atr, ema_spread, kelly, etc.)
);
CREATE INDEX IF NOT EXISTS idx_shadow_signals_bot_ts ON shadow_signals (bot_id, signal_ts DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_signals_symbol  ON shadow_signals (symbol, signal_ts DESC);

-- Life-of-platform fleet equity history — one row per day, written by the nightly scheduler.
-- Powers the sparkline on the home dashboard. ON CONFLICT DO UPDATE keeps only the latest
-- value for each date so re-runs are idempotent.
CREATE TABLE IF NOT EXISTS fleet_equity_history (
    id            SERIAL      PRIMARY KEY,
    snapshot_date DATE        NOT NULL UNIQUE,
    total_equity  NUMERIC     NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fleet_equity_history_date
    ON fleet_equity_history (snapshot_date DESC);

"""

# Safe column migrations — run after CREATE TABLE IF NOT EXISTS so the base
# tables always exist first.  Each statement is idempotent (ADD COLUMN IF NOT EXISTS).
_MIGRATION_SQL = """
ALTER TABLE trades ADD COLUMN IF NOT EXISTS regime_at_entry      TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS time_in_trade_hours  DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_reason          TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS realized_pnl         DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS slippage_pct         DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS is_recon_tracking    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS recon_event_id       BIGINT;
"""

# ARC 4 backfill: tag existing RECON-* rows so WR/expectancy queries can use the
# clean boolean predicate (NOT is_recon_tracking) instead of LIKE 'RECON-%'.
# Idempotent — safe to run on every startup.
_ARC4_BACKFILL_SQL = """
UPDATE trades
SET    is_recon_tracking = TRUE
WHERE  trade_id LIKE 'RECON-%'
  AND  NOT is_recon_tracking;
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

    # ARC 4: tag existing RECON-* rows as is_recon_tracking=TRUE so WR queries
    # can use the clean boolean predicate instead of LIKE 'RECON-%' string-match.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_ARC4_BACKFILL_SQL.strip())
                updated = cur.rowcount
        if updated:
            logger.info(f"DB | ARC4 backfill: tagged {updated} RECON-* row(s) as is_recon_tracking=TRUE")
    except Exception as exc:
        logger.warning(f"DB | ARC4 is_recon_tracking backfill failed (non-fatal): {exc}")

    # One-time backfill: seed ratchet_stops for all 6 live Oracle equity positions.
    # ARM and MU had no broker GTC stops; placed manually 2026-06-15 (order_ids below).
    # CSCO/DELL/MS/PANW already had broker stops; this links their order_ids to the DB.
    # MRVL skipped (sub-1-share, cannot place broker stop).
    # ATR=0.0 for positions where ATR was unavailable at entry time (known Jun 9-10 issue).
    # Idempotent: ON CONFLICT (symbol) DO UPDATE keeps the record fresh on re-runs.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ratchet_stops
                        (symbol, stop_price, fill_price, atr, atr_multiplier, side, last_updated, stop_order_id)
                    VALUES
                        ('ARM',  242.44,  319.784916, 38.6728, 2.0, 'long', CURRENT_DATE, 'b5c5020c-0110-45cf-af2b-cfa0077d6c28'),
                        ('MU',   761.67,  922.116585, 80.2227, 2.0, 'long', CURRENT_DATE, 'e2ea75e3-63e9-42bf-8dc7-a5b00c900905'),
                        ('CSCO', 117.01,  119.396432, 0.0,     2.0, 'long', CURRENT_DATE, '9605dae2-d4e5-4751-a939-d74a75515390'),
                        ('DELL', 326.72,  379.434447, 0.0,     2.0, 'long', CURRENT_DATE, '5899798a-5079-4472-984b-58c119dfab56'),
                        ('MS',   203.61,  207.77,     0.0,     2.0, 'long', CURRENT_DATE, 'd9df546c-fa03-478e-a16a-4f3d8e257928'),
                        ('PANW', 257.40,  262.65,     0.0,     2.0, 'long', CURRENT_DATE, 'b289f55a-1af3-49ac-9d7b-5c4699f7e9e6')
                    ON CONFLICT (symbol) DO UPDATE
                        SET stop_price     = EXCLUDED.stop_price,
                            fill_price     = EXCLUDED.fill_price,
                            atr            = EXCLUDED.atr,
                            atr_multiplier = EXCLUDED.atr_multiplier,
                            side           = EXCLUDED.side,
                            last_updated   = EXCLUDED.last_updated,
                            stop_order_id  = EXCLUDED.stop_order_id
                    """
                )
                logger.info(f"DB | ratchet_stops backfill applied ({cur.rowcount} rows upserted)")
    except Exception as exc:
        logger.error(f"DB | ratchet_stops backfill FAILED: {exc}")
        try:
            from core.degradation_tracker import record_degradation as _rd
            _rd(component="oracle", severity="high",
                error_type="startup_repair_failed",
                message=f"ratchet_stops backfill failed — 6 live positions may have no DB stop record",
                detail=str(exc)[:2000])
        except Exception:
            pass

    # One-time repair: close the RECON-SNOW-20260615 phantom row inserted by the
    # reconciler race on 2026-06-15.  The exit manager submitted a day-order sell
    # for SNOW at 13:31:26 UTC; the sell didn't fill until 13:40:12 UTC, so the
    # reconciler (running ~0.5s later) still saw SNOW as an open broker position
    # and inserted a spurious Active row.  True P&L is captured in the real
    # Closed_Loss row (trade_id=35775d2e, realized_pnl=-531.16).
    # Idempotent: AND status='Active' makes this a no-op once already closed.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE trades
                    SET status            = 'Closed_Reconciled',
                        actual_fill_price = 232.843038,
                        realized_pnl      = 0.00,
                        exit_reason       = 'reconciler_race_phantom',
                        closed_at         = '2026-06-15T13:40:12+00:00'
                    WHERE trade_id = 'RECON-SNOW-20260615'
                      AND status   = 'Active'
                    """
                )
                if cur.rowcount:
                    logger.info("DB | RECON-SNOW-20260615 phantom row closed (reconciler_race_phantom)")
    except Exception as exc:
        logger.error(f"DB | SNOW phantom repair FAILED: {exc}")
        try:
            from core.degradation_tracker import record_degradation as _rd
            _rd(component="oracle", severity="high",
                error_type="startup_repair_failed",
                message=f"SNOW phantom trade row (RECON-SNOW-20260615) repair failed — Active count overstated by 1",
                detail=str(exc)[:2000])
        except Exception:
            pass

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

                    ON CONFLICT (bot_id) DO NOTHING;
                """)
        logger.info("DB | bots_state seed complete")
    except Exception as exc:
        logger.warning(f"DB | bots_state seed failed (non-fatal): {exc}")

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

    # JEROME V2 SCHEMA — 2026-05-28
    # Additive only — ADD COLUMN IF NOT EXISTS means fully idempotent.
    # entry_price       : close price at time of entry (used for trailing stop baseline)
    # highest_price_seen: best close reached since entry (longs) / lowest close (shorts)
    #                     stored as the same field — "most favourable close seen"
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE jerome_positions "
                    "ADD COLUMN IF NOT EXISTS entry_price NUMERIC"
                )
                cur.execute(
                    "ALTER TABLE jerome_positions "
                    "ADD COLUMN IF NOT EXISTS highest_price_seen NUMERIC"
                )
        logger.info("DB | Jerome v2: entry_price + highest_price_seen columns ensured")
    except Exception as exc:
        logger.error(f"DB | Jerome v2 schema migration failed (non-fatal): {exc}")

    # JEROME V2 — backfill COPX position that pre-existed v2 launch.
    # Alpaca avg_entry_price = 86.989133 (verified 2026-05-28).
    # Idempotent: only touches rows where entry_price IS NULL.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE jerome_positions
                    SET entry_price          = 86.989133,
                        highest_price_seen   = 86.989133
                    WHERE symbol = 'COPX'
                      AND status = 'open'
                      AND entry_price IS NULL
                """)
                _n = cur.rowcount
        if _n:
            logger.info(f"DB | Jerome v2: backfilled COPX entry_price={86.989133} ({_n} row(s))")
    except Exception as exc:
        logger.warning(f"DB | Jerome v2 COPX backfill failed (non-fatal): {exc}")

    # BUCK FUTURES — add bot_id column to jerome_positions so Jerome and Buck
    # Futures can share the table without row collisions. Fully idempotent.
    # Jerome rows default to 'jerome_macro'; Buck Futures writes 'buck_futures'.
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE jerome_positions "
                    "ADD COLUMN IF NOT EXISTS bot_id TEXT DEFAULT 'jerome_macro'"
                )
                cur.execute("""
                    UPDATE jerome_positions
                    SET bot_id = 'jerome_macro'
                    WHERE bot_id IS NULL
                """)
        logger.info("DB | jerome_positions: bot_id column ensured (jerome_macro default)")
    except Exception as exc:
        logger.error(f"DB | jerome_positions bot_id migration failed (non-fatal): {exc}")

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
                    WHERE bot_id = 'forex_gump'
                      AND data_source IS NULL
                """)

                logger.info("DB | Phase A: backfilled data_source")

                logger.info("DB | Phase A: ensured all bots have rows")
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

    # Phase F — Crypto bot removal (Phase 2 cleanup).
    # Drop decommissioned crypto tables and purge 4 bot_portfolio rows.
    # Safe to re-run: IF EXISTS guards + ON CONFLICT checks make it idempotent.
    try:
        with get_conn() as _f_conn:
            with _f_conn.cursor() as _f_cur:
                _f_cur.execute("DROP TABLE IF EXISTS crypto_signals")
                logger.info("DB | Phase F: dropped crypto_signals")
    except Exception as _f_exc:
        logger.error(f"DB | Phase F crypto_signals drop failed: {_f_exc}")
    try:
        with get_conn() as _f_conn:
            with _f_conn.cursor() as _f_cur:
                _f_cur.execute("DROP TABLE IF EXISTS crypto_price_cache")
                logger.info("DB | Phase F: dropped crypto_price_cache")
    except Exception as _f_exc:
        logger.error(f"DB | Phase F crypto_price_cache drop failed: {_f_exc}")
    try:
        with get_conn() as _f_conn:
            with _f_conn.cursor() as _f_cur:
                _f_cur.execute(
                    "DELETE FROM bot_portfolio WHERE bot_id = ANY(%s)",
                    (["depeg_hunter", "momentum_alpha", "momentum_beta", "momentum_gamma", "forex_gump"],),
                )
                logger.info("DB | Phase F: deleted retired bot_portfolio rows")
    except Exception as _f_exc:
        logger.error(f"DB | Phase F bot_portfolio delete failed: {_f_exc}")

    # Phase G — Oracle orphan-close one-time fix.
    # ALL (trade_id 1a6ab178-c2a4-4d4b-988a-4358731b58fc) and CDNS
    # (d9ef004e-24c7-44c1-9241-2e7cae2171ac) were opened 2026-04-16 and
    # confirmed absent from Alpaca PA33G6QCIHDS as of 2026-05-31.
    # The inverse reconciler in pipeline.py will handle future occurrences;
    # this block back-fills the two known pre-existing orphans once.
    # Idempotent: WHERE status = 'Active' means re-runs are no-ops.
    _g_orphan_ids = [
        "1a6ab178-c2a4-4d4b-988a-4358731b58fc",  # ALL
        "d9ef004e-24c7-44c1-9241-2e7cae2171ac",   # CDNS
    ]
    try:
        with get_conn() as _g_conn:
            with _g_conn.cursor() as _g_cur:
                _g_cur.execute(
                    """
                    UPDATE trades
                    SET status            = 'Closed_Reconciled',
                        closed_at         = NOW(),
                        exit_reason       = 'orphan_db_reconciler',
                        actual_fill_price = NULL,
                        realized_pnl      = NULL,
                        pnl_percentage    = NULL
                    WHERE trade_id = ANY(%s)
                      AND status = 'Active'
                    RETURNING trade_id, ticker
                    """,
                    (_g_orphan_ids,),
                )
                _g_closed = _g_cur.fetchall()
        for _g_trade_id, _g_ticker in _g_closed:
            try:
                with get_conn() as _g_deg_conn:
                    with _g_deg_conn.cursor() as _g_dcur:
                        _g_dcur.execute(
                            """
                            INSERT INTO system_degradations
                                (ts, component, severity, error_type, message)
                            VALUES (NOW(), 'oracle', 'medium', 'orphan_db_closed',
                                    %s)
                            """,
                            (f"{_g_ticker} marked closed — DB Active but no broker position",),
                        )
            except Exception as _g_deg_exc:
                logger.warning(f"DB | Phase G degradation insert failed for {_g_ticker}: {_g_deg_exc}")
            logger.info(f"DB | Phase G: {_g_ticker} ({_g_trade_id}) → Closed_Reconciled")
        if not _g_closed:
            logger.info("DB | Phase G: no orphan rows to close (already applied or clean)")
    except Exception as _g_exc:
        logger.error(f"DB | Phase G orphan-close failed: {_g_exc}")

    # Phase H — Jerome v1 duplicate-row cleanup (one-time, idempotent).
    #
    # Jerome v1's LLM loop re-inserted positions every cycle without checking
    # for an existing open row, creating multiple DB rows per ticker backed by
    # one real broker position.  Two sub-steps:
    #
    # H-1: Close the open COPX phantom (id=9, opened 2026-05-25).  id=4
    #      (opened 2026-05-24) is the canonical live position.
    #      Idempotent: WHERE status='open' is a no-op after first run.
    #
    # H-2: Append ' [v1_duplicate]' to the exit_reason of every non-first
    #      v1 row (opened_at < 2026-05-28) for each symbol.  This marks
    #      WEAT ids 3/6/8/11, GLD ids 7/10, and COPX id=9 so future
    #      metrics queries can filter them out.
    #      Idempotent: NOT LIKE guard prevents double-appending.
    try:
        with get_conn() as _h_conn:
            with _h_conn.cursor() as _h_cur:
                # H-1: close the open COPX duplicate
                _h_cur.execute(
                    """
                    UPDATE jerome_positions
                    SET status           = 'Closed_Reconciled',
                        closed_at        = NOW(),
                        exit_reason      = 'duplicate_row_reconciler',
                        realised_pnl_usd = 0.00
                    WHERE id = 9
                      AND bot_id = 'jerome_macro'
                      AND symbol = 'COPX'
                      AND status = 'open'
                    RETURNING id
                    """
                )
                _h1_count = len(_h_cur.fetchall())

                # H-2: mark all non-first v1 rows with [v1_duplicate]
                _h_cur.execute(
                    """
                    UPDATE jerome_positions
                    SET exit_reason = COALESCE(exit_reason, '') || ' [v1_duplicate]'
                    WHERE id IN (
                        SELECT id FROM jerome_positions
                        WHERE bot_id   = 'jerome_macro'
                          AND opened_at < '2026-05-28 00:00:00+00'
                          AND id NOT IN (
                              SELECT MIN(id)
                              FROM jerome_positions
                              WHERE bot_id   = 'jerome_macro'
                                AND opened_at < '2026-05-28 00:00:00+00'
                              GROUP BY symbol
                          )
                    )
                    AND (exit_reason NOT LIKE '%%[v1_duplicate]%%' OR exit_reason IS NULL)
                    """
                )
                _h2_count = _h_cur.rowcount
        logger.info(
            f"DB | Phase H: H-1 closed {_h1_count} COPX phantom row(s); "
            f"H-2 marked {_h2_count} v1 duplicate row(s) with [v1_duplicate]"
        )
    except Exception as _h_exc:
        logger.error(f"DB | Phase H duplicate-row cleanup failed: {_h_exc}")

    # Phase I — bot_evaluation_history table (live-capital readiness snapshots).
    #
    # Created once; idempotent via CREATE TABLE IF NOT EXISTS.  Populated by
    # GET /fleet/scorecard at most once per 12 hours per bot.
    try:
        with get_conn() as _i_conn:
            with _i_conn.cursor() as _i_cur:
                _i_cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bot_evaluation_history (
                        id              SERIAL PRIMARY KEY,
                        bot_id          TEXT NOT NULL,
                        snapshot_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        trades_count    INTEGER,
                        win_rate        DOUBLE PRECISION,
                        expectancy_usd  DOUBLE PRECISION,
                        sharpe          DOUBLE PRECISION,
                        max_drawdown    DOUBLE PRECISION,
                        gates_passed    INTEGER,
                        readiness_score DOUBLE PRECISION,
                        verdict         TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_bot_eval_history_bot_time
                        ON bot_evaluation_history (bot_id, snapshot_at DESC);
                    """
                )
        logger.info("DB | Phase I: bot_evaluation_history table ensured")
    except Exception as _i_exc:
        logger.error(f"DB | Phase I bot_evaluation_history failed: {_i_exc}")

    # Phase J — ratchet_stops orphan cleanup (2026-06-26, one-time, idempotent).
    #
    # Autopsy of the Jun-9 reconciler mass-exit revealed two problems:
    #   1. Four active positions (ARM/MS/MU/PANW) have live GTC stop orders at
    #      Alpaca but ratchet_stops.stop_order_id = NULL (backfill linkage gap).
    #      maybe_ratchet skips cancel_order when old_id is None → would place a
    #      second stop on next ratchet trigger → duplicate GTC orders.
    #      Fix: write the live Alpaca order IDs into the DB.
    #   2. Thirteen stale ratchet_stops rows remain for closed/reconciled positions
    #      (INTC/NUE/QCOM/TXN/UNH/AMD closed Jun-10 via orphan_db_reconciler;
    #       DDOG/FTNT/HPE closed Jun-9 via deleted EOD reconciler;
    #       APD/CCL/USO from Kraken era).  These cause nightly compute_atr
    #      "possibly delisted" log noise.  All five orphan GTC orders confirmed
    #      already gone from Alpaca PA33G6QCIHDS as of 2026-06-26.
    #   3. MRVL has a stale d96941eb stop_order_id — order gone from broker
    #      (sub-share 0.285 can't take a whole-share stop).  Clear the ref.
    #
    # Idempotency:
    #   Part A UPDATEs: setting same UUID twice is harmless.
    #   Part B DELETEs: deleting absent rows is a no-op (returns 0 rows).
    #   Part C UPDATE:  setting NULL twice is harmless.
    try:
        with get_conn() as _j_conn:
            with _j_conn.cursor() as _j_cur:

                # Part A — link live broker stop_order_ids into ratchet_stops
                _j_live_stops = [
                    ("ARM",  "b5c5020c-0110-45cf-af2b-cfa0077d6c28"),
                    ("MS",   "d9df546c-fa03-478e-a16a-4f3d8e257928"),
                    ("MU",   "e2ea75e3-63e9-42bf-8dc7-a5b00c900905"),
                    ("PANW", "b289f55a-1af3-49ac-9d7b-5c4699f7e9e6"),
                ]
                _j_a_updated: list[str] = []
                for _j_sym, _j_oid in _j_live_stops:
                    _j_cur.execute(
                        "UPDATE ratchet_stops SET stop_order_id = %s WHERE symbol = %s"
                        " AND (stop_order_id IS NULL OR stop_order_id != %s)"
                        " RETURNING symbol",
                        (_j_oid, _j_sym, _j_oid),
                    )
                    if _j_cur.fetchone():
                        _j_a_updated.append(_j_sym)

                # Part B — delete stale rows for closed positions
                _j_stale = [
                    "INTC", "NUE", "QCOM", "TXN", "UNH", "AMD",  # orphan_db_reconciler Jun-10
                    "DDOG", "FTNT", "HPE",                          # reconciler_market_exit Jun-9
                    "APD",  "CCL",  "USO",                          # Kraken-era, all closed
                ]
                _j_cur.execute(
                    "DELETE FROM ratchet_stops WHERE symbol = ANY(%s) RETURNING symbol",
                    (_j_stale,),
                )
                _j_b_deleted = [r[0] for r in _j_cur.fetchall()]

                # Part C — clear stale stop_order_id on MRVL (sub-share, order gone)
                _j_cur.execute(
                    "UPDATE ratchet_stops SET stop_order_id = NULL WHERE symbol = 'MRVL'"
                    " AND stop_order_id IS NOT NULL RETURNING symbol",
                )
                _j_c_cleared = bool(_j_cur.fetchone())

        logger.info(
            f"DB | Phase J: A-linked={_j_a_updated}, "
            f"B-deleted={_j_b_deleted}, "
            f"C-MRVL-cleared={_j_c_cleared}"
        )
    except Exception as _j_exc:
        logger.error(f"DB | Phase J ratchet_stops cleanup failed: {_j_exc}")

    # ── Phase K — oos_envelope table + seed ───────────────────────────────────
    # Stores the pre-registered OOS envelope for each bot (pooled Sharpe,
    # worst-window floor, maxDD, params hash).  The nightly walk-forward job
    # reads these to classify GREEN/AMBER/RED/INSUFFICIENT_DATA/DISQUALIFIED.
    # Seeded once; ON CONFLICT DO NOTHING keeps it idempotent.
    try:
        import hashlib as _hlib
        import json as _json_k

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS oos_envelope (
                        bot_id               TEXT PRIMARY KEY,
                        pooled_sharpe        DOUBLE PRECISION,
                        worst_window_sharpe  DOUBLE PRECISION,
                        worst_window         TEXT,
                        best_window_sharpe   DOUBLE PRECISION,
                        worst_window_maxdd   DOUBLE PRECISION,
                        oos_run_date         DATE,
                        params_hash          TEXT,
                        disqualified         BOOLEAN DEFAULT FALSE,
                        disqualified_reason  TEXT,
                        created_at           TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                _oracle_params = {
                    "strategy": "stf_v1.0_momentum_equity",
                    "note":     "STF v1.0 deployed config as-of 2026-07-14 OOS run",
                }
                _spy_params = {
                    "ema_fast": 50, "ema_slow": 200,
                    "trail_stop_pct": 0.08, "position_size_pct": 0.40,
                    "max_deployment": 0.80, "min_hold_days": 5,
                    "tp1_pct": 0.06, "tp2_pct": 0.12,
                    "crisis_threshold": -0.12, "max_3day_drop_pct": 0.05,
                }
                _disq_params = {"disqualified": True}

                def _h(d: dict) -> str:
                    return _hlib.sha256(
                        _json_k.dumps(d, sort_keys=True).encode()
                    ).hexdigest()[:16]

                _seed_rows = [
                    ("oracle",        0.633,  -0.153, "2021",  1.526, 0.170, "2026-07-14", _h(_oracle_params), False, None),
                    ("spy_qqq_trend", 0.862,  -1.889, "2022",  1.411, 0.065, "2026-07-14", _h(_spy_params),    False, None),
                    ("jerome_macro",  None,   None,   None,    None,  None,  None,          _h(_disq_params),   True,  "No OOS run completed — flag any live trading as anomaly"),
                    ("buck_futures",  None,   None,   None,    None,  None,  None,          _h(_disq_params),   True,  "No OOS run completed — flag any live trading as anomaly"),
                ]
                for row in _seed_rows:
                    cur.execute("""
                        INSERT INTO oos_envelope
                            (bot_id, pooled_sharpe, worst_window_sharpe, worst_window,
                             best_window_sharpe, worst_window_maxdd, oos_run_date,
                             params_hash, disqualified, disqualified_reason)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (bot_id) DO NOTHING
                    """, row)

        logger.info("DB | Phase K: oos_envelope table ensured and seeded")
    except Exception as _k_exc:
        logger.error(f"DB | Phase K oos_envelope setup failed: {_k_exc}")

    # ── Phase L — walk-forward columns on bot_evaluation_history ──────────────
    # Adds 14 new WF columns to the existing table.  All ADD COLUMN IF NOT EXISTS
    # → fully idempotent.  Populated nightly by the arc2_walk_forward job.
    try:
        _wf_cols = [
            ("wf_sharpe_30d",             "DOUBLE PRECISION"),
            ("wf_sharpe_90d",             "DOUBLE PRECISION"),
            ("wf_maxdd_30d",              "DOUBLE PRECISION"),
            ("wf_maxdd_90d",              "DOUBLE PRECISION"),
            ("wf_trades_30d",             "INTEGER"),
            ("wf_trades_90d",             "INTEGER"),
            ("wf_win_rate_30d",           "DOUBLE PRECISION"),
            ("wf_win_rate_90d",           "DOUBLE PRECISION"),
            ("wf_expectancy_30d",         "DOUBLE PRECISION"),
            ("wf_expectancy_90d",         "DOUBLE PRECISION"),
            ("wf_status",                 "TEXT"),
            ("wf_consecutive_below_floor","INTEGER"),
            ("wf_oos_floor_sharpe",       "DOUBLE PRECISION"),
        ]
        with get_conn() as conn:
            with conn.cursor() as cur:
                for col, dtype in _wf_cols:
                    cur.execute(
                        f"ALTER TABLE bot_evaluation_history "
                        f"ADD COLUMN IF NOT EXISTS {col} {dtype}"
                    )
        logger.info(f"DB | Phase L: {len(_wf_cols)} walk-forward columns ensured on bot_evaluation_history")
    except Exception as _l_exc:
        logger.error(f"DB | Phase L walk-forward column migrations failed: {_l_exc}")


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
    Legacy Kraken equity is retired.  Fleet equity is now sourced from the
    canonical bot portfolio/fleet-equity path, so this compatibility helper
    must not query the removed heartbeat table.
    """
    return 0.0


# ── Equity snapshots ───────────────────────────────────────────────────────

def insert_fleet_equity_snapshots(rows: list[tuple[str, float]]) -> int:
    """Write one current equity snapshot for each active fleet bot."""
    if not rows or not is_pg_available():
        return 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO fleet_equity_snapshots (snapshot_ts, bot_id, equity_usd)
                    VALUES (NOW(), %s, %s)
                    """,
                    [(bot_id, float(equity)) for bot_id, equity in rows],
                )
                return cur.rowcount
    except Exception as exc:
        logger.error(f"DB | insert_fleet_equity_snapshots failed: {exc}")
        return 0


def get_equity_curve(limit: int = 500) -> list[dict]:
    """Return canonical active-bot fleet equity snapshots oldest first."""
    if not is_pg_available():
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MIN(id) AS id,
                           snapshot_ts AT TIME ZONE 'UTC' AS ts,
                           SUM(equity_usd)::DOUBLE PRECISION AS total_equity,
                           NULL::TEXT AS regime,
                           'fleet_equity_snapshots'::TEXT AS source
                    FROM fleet_equity_snapshots
                    WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                    GROUP BY snapshot_ts
                    ORDER BY snapshot_ts DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        cols = ["id", "ts", "total_equity", "regime", "source"]
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


# ── ARC 4: Reconciliation event writer ────────────────────────────────────────

def record_reconciliation_event(
    event_type: str,
    bot_id: str,
    symbol: str | None = None,
    trade_id_ref: str | None = None,
    detail: str | None = None,
    broker_state_snapshot: dict | None = None,
) -> None:
    """
    ARC 4: Write one reconciliation_events row.
    event_type: recon_insert | orphan_close | race_phantom | empty_response_skip
    Fire-and-forget — never raises; all errors logged at DEBUG.
    """
    import json as _rce_json
    try:
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reconciliation_events
                        (event_type, bot_id, symbol, trade_id_ref, detail,
                         broker_state_snapshot)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event_type,
                        bot_id,
                        symbol,
                        trade_id_ref,
                        detail,
                        _rce_json.dumps(broker_state_snapshot) if broker_state_snapshot else None,
                    ),
                )
    except Exception as exc:
        logger.debug(f"DB | record_reconciliation_event failed (non-fatal): {exc}")
