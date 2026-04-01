"""
db.py — PostgreSQL access layer for Kraken bots (multi-bot).

Supports multiple bot instances via bot_id / db_id parameters.
Each bot gets its own row in heartbeat/portfolio/adaptive_params (keyed by integer id)
and its own trades in kraken_trades (filtered by bot_id text column).

Tables:
  kraken_heartbeat      — one row per bot (id=1 davy-jones, id=2 blackbeard, id=3 calypso)
  kraken_portfolio      — one row per bot
  kraken_trades         — append-only, filtered by bot_id column
  kraken_adaptive_params — one row per bot
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from loguru import logger

import time

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool as _pg_pool
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False
    logger.warning("DB | psycopg2 not installed — Kraken bot DB unavailable")

_pool: "_pg_pool.ThreadedConnectionPool | None" = None


_KRAKEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS kraken_heartbeat (
    id              INTEGER PRIMARY KEY,
    bot_id          TEXT    NOT NULL DEFAULT 'davy-jones',
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

CREATE TABLE IF NOT EXISTS kraken_portfolio (
    id                   INTEGER PRIMARY KEY,
    bot_id               TEXT NOT NULL DEFAULT 'davy-jones',
    starting_balance_usd DOUBLE PRECISION NOT NULL DEFAULT 100000,
    cash_usd             DOUBLE PRECISION NOT NULL DEFAULT 100000,
    positions            JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS kraken_trades (
    id          BIGSERIAL PRIMARY KEY,
    bot_id      TEXT             NOT NULL DEFAULT 'davy-jones',
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
    order_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_kraken_trades_closed_at ON kraken_trades (closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_kraken_trades_bot_id ON kraken_trades (bot_id);

CREATE TABLE IF NOT EXISTS kraken_adaptive_params (
    id          INTEGER PRIMARY KEY,
    bot_id      TEXT NOT NULL DEFAULT 'davy-jones',
    params      JSONB NOT NULL DEFAULT '{}',
    metrics     JSONB,
    reasons     JSONB,
    adapted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lookback_n  INTEGER NOT NULL DEFAULT 0
);
"""

_MIGRATION_SQL = """
DO $$
BEGIN
    -- Drop CHECK constraints if they exist
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname LIKE '%kraken_heartbeat%check%' OR
               (conrelid = 'kraken_heartbeat'::regclass AND contype = 'c')) THEN
        BEGIN
            ALTER TABLE kraken_heartbeat DROP CONSTRAINT IF EXISTS kraken_heartbeat_id_check;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname LIKE '%kraken_portfolio%check%' OR
               (conrelid = 'kraken_portfolio'::regclass AND contype = 'c')) THEN
        BEGIN
            ALTER TABLE kraken_portfolio DROP CONSTRAINT IF EXISTS kraken_portfolio_id_check;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname LIKE '%kraken_adaptive_params%check%' OR
               (conrelid = 'kraken_adaptive_params'::regclass AND contype = 'c')) THEN
        BEGIN
            ALTER TABLE kraken_adaptive_params DROP CONSTRAINT IF EXISTS kraken_adaptive_params_id_check;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END IF;

    -- Add bot_id columns if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='kraken_heartbeat' AND column_name='bot_id') THEN
        ALTER TABLE kraken_heartbeat ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'davy-jones';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='kraken_portfolio' AND column_name='bot_id') THEN
        ALTER TABLE kraken_portfolio ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'davy-jones';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='kraken_trades' AND column_name='bot_id') THEN
        ALTER TABLE kraken_trades ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'davy-jones';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='kraken_adaptive_params' AND column_name='bot_id') THEN
        ALTER TABLE kraken_adaptive_params ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'davy-jones';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_kraken_trades_bot_id ON kraken_trades (bot_id);
"""


def _get_dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


def _is_available() -> bool:
    return _PG_AVAILABLE and bool(_get_dsn())


def _init_pool() -> None:
    global _pool
    if not _PG_AVAILABLE:
        return
    dsn = _get_dsn()
    if not dsn:
        return
    bot_label = "kraken"
    try:
        from config import BOT_ID
        bot_label = BOT_ID
    except Exception:
        pass
    for attempt in range(1, 4):
        try:
            _pool = _pg_pool.ThreadedConnectionPool(minconn=1, maxconn=4, dsn=dsn)
            logger.info(f"DB | Kraken ({bot_label}) connection pool initialised (min=1, max=4)")
            return
        except Exception as exc:
            logger.warning(f"DB | Kraken ({bot_label}) pool init attempt {attempt}/3 failed: {exc}")
            if attempt < 3:
                time.sleep(2)
    logger.error(f"DB | Kraken ({bot_label}) pool init failed after 3 attempts — falling back to per-query connections")


_init_pool()


@contextmanager
def _conn() -> "Generator[psycopg2.extensions.connection, None, None]":
    if _pool is not None:
        try:
            conn = _pool.getconn()
        except Exception as exc:
            logger.warning(f"DB | Kraken pool checkout failed (exhausted?): {exc} — falling back to direct connection")
            conn = psycopg2.connect(_get_dsn())
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pool.putconn(conn)
    else:
        conn = psycopg2.connect(_get_dsn())
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _get_bot_config():
    from config import BOT_ID, BOT_DB_ID
    return BOT_ID, BOT_DB_ID


def ensure_schema() -> None:
    if not _is_available():
        logger.debug("DB | ensure_schema skipped (PostgreSQL unavailable)")
        return
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_KRAKEN_SCHEMA)
                cur.execute(_MIGRATION_SQL)
        logger.info("DB | Kraken schema verified / migrated (multi-bot)")
    except Exception as exc:
        logger.error(f"DB | Kraken schema bootstrap failed: {exc}")


def migrate_from_json(paper_portfolio_path: str) -> bool:
    if not _is_available():
        return False
    if not os.path.exists(paper_portfolio_path):
        return False
    try:
        with open(paper_portfolio_path) as f:
            pf = json.load(f)
    except Exception as exc:
        logger.warning(f"DB | migration_from_json: could not read {paper_portfolio_path}: {exc}")
        return False

    bot_id, db_id = _get_bot_config()

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM kraken_portfolio WHERE id = %s", (db_id,))
                row = cur.fetchone()
                if row is not None:
                    logger.debug(f"DB | Portfolio row exists for {bot_id} — skipping JSON migration")
                    return False
    except Exception:
        pass

    try:
        starting = pf.get("starting_balance_usd", 100_000)
        cash     = pf.get("cash_usd", starting)
        positions = pf.get("positions", {})
        all_trades = pf.get("all_trades", [])

        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_portfolio (id, bot_id, starting_balance_usd, cash_usd, positions)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        bot_id               = EXCLUDED.bot_id,
                        starting_balance_usd = EXCLUDED.starting_balance_usd,
                        cash_usd             = EXCLUDED.cash_usd,
                        positions            = EXCLUDED.positions
                    """,
                    (db_id, bot_id, starting, cash, json.dumps(positions, default=str)),
                )

                cur.execute("SELECT COUNT(*) FROM kraken_trades WHERE bot_id = %s", (bot_id,))
                existing = cur.fetchone()[0]
                if existing == 0 and all_trades:
                    for t in all_trades:
                        cur.execute(
                            """
                            INSERT INTO kraken_trades
                                (bot_id, symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                                 fees_usd, reason, closed_at, paper)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                            """,
                            (
                                bot_id,
                                t.get("symbol"),
                                t.get("side"),
                                t.get("entry_price", 0),
                                t.get("exit_price", 0),
                                t.get("pnl_pct", 0),
                                t.get("pnl_usd", 0),
                                t.get("fees_usd"),
                                t.get("reason"),
                                t.get("closed_at"),
                            ),
                        )
                    logger.info(f"DB | Migrated {len(all_trades)} trades from JSON for {bot_id}")

        logger.info(
            f"DB | Migration complete for {bot_id} — "
            f"cash=${cash:,.2f}, {len(positions)} open positions, "
            f"{len(all_trades)} historical trades"
        )
        return True

    except Exception as exc:
        logger.error(f"DB | Migration from JSON failed: {exc}")
        return False


def migrate_heartbeat_from_json(status_file_path: str) -> bool:
    if not _is_available():
        return False
    if not os.path.exists(status_file_path):
        return False

    bot_id, db_id = _get_bot_config()

    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM kraken_heartbeat WHERE id = %s", (db_id,))
                if cur.fetchone():
                    logger.debug(f"DB | kraken_heartbeat row exists for {bot_id} — skipping heartbeat migration")
                    return False
    except Exception:
        return False
    try:
        with open(status_file_path) as f:
            st = json.load(f)
    except Exception as exc:
        logger.warning(f"DB | migrate_heartbeat_from_json: could not read {status_file_path}: {exc}")
        return False
    try:
        cb = st.get("circuit_breaker") or {"active": False, "paused_until": None}
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_heartbeat
                        (id, bot_id, status, cycle_count, equity_usd, position_count,
                         paper_trading, bot_paused, circuit_breaker, error, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        db_id,
                        bot_id,
                        st.get("status", "not_started"),
                        st.get("cycle_count", 0),
                        st.get("total_equity_usd", 0),
                        st.get("position_count", 0),
                        st.get("paper_trading", True),
                        st.get("bot_paused", False),
                        json.dumps(cb),
                        st.get("error"),
                    ),
                )
        logger.info(f"DB | Migrated heartbeat from {status_file_path} to PostgreSQL for {bot_id}")
        return True
    except Exception as exc:
        logger.error(f"DB | migrate_heartbeat_from_json failed: {exc}")
        return False


def upsert_heartbeat(
    status: str,
    cycle_count: int,
    equity_usd: float,
    position_count: int,
    paper_trading: bool,
    bot_paused: bool,
    circuit_breaker: dict,
    error: str | None,
) -> bool:
    if not _is_available():
        return False
    bot_id, db_id = _get_bot_config()
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_heartbeat
                        (id, bot_id, status, cycle_count, equity_usd, position_count,
                         paper_trading, bot_paused, circuit_breaker, error, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        bot_id          = EXCLUDED.bot_id,
                        status          = EXCLUDED.status,
                        cycle_count     = EXCLUDED.cycle_count,
                        equity_usd      = EXCLUDED.equity_usd,
                        position_count  = EXCLUDED.position_count,
                        paper_trading   = EXCLUDED.paper_trading,
                        bot_paused      = EXCLUDED.bot_paused,
                        circuit_breaker = EXCLUDED.circuit_breaker,
                        error           = EXCLUDED.error,
                        last_updated    = NOW()
                    """,
                    (
                        db_id,
                        bot_id,
                        status,
                        cycle_count,
                        equity_usd,
                        position_count,
                        paper_trading,
                        bot_paused,
                        json.dumps(circuit_breaker),
                        error,
                    ),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | upsert_heartbeat failed: {exc}")
        return False


def load_heartbeat() -> dict | None:
    if not _is_available():
        return None
    bot_id, db_id = _get_bot_config()
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (db_id,))
                row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("last_updated"):
            d["last_updated"] = d["last_updated"].isoformat()
        if isinstance(d.get("circuit_breaker"), str):
            d["circuit_breaker"] = json.loads(d["circuit_breaker"])
        return d
    except Exception as exc:
        logger.warning(f"DB | load_heartbeat failed: {exc}")
        return None


def load_portfolio() -> dict | None:
    if not _is_available():
        return None
    bot_id, db_id = _get_bot_config()
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT starting_balance_usd, cash_usd, positions FROM kraken_portfolio WHERE id = %s",
                    (db_id,)
                )
                row = cur.fetchone()
        if not row:
            return None
        starting, cash, positions_raw = row
        if isinstance(positions_raw, str):
            positions_raw = json.loads(positions_raw)
        return {
            "starting_balance_usd": starting,
            "cash_usd":             cash,
            "positions":            positions_raw or {},
        }
    except Exception as exc:
        logger.warning(f"DB | load_portfolio failed: {exc}")
        return None


def save_portfolio(
    cash_usd: float,
    positions: dict,
    starting_balance_usd: float | None = None,
) -> bool:
    if not _is_available():
        return False
    bot_id, db_id = _get_bot_config()
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                if starting_balance_usd is not None:
                    cur.execute(
                        """
                        INSERT INTO kraken_portfolio (id, bot_id, starting_balance_usd, cash_usd, positions)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            bot_id               = EXCLUDED.bot_id,
                            starting_balance_usd = EXCLUDED.starting_balance_usd,
                            cash_usd             = EXCLUDED.cash_usd,
                            positions            = EXCLUDED.positions
                        """,
                        (db_id, bot_id, starting_balance_usd, cash_usd, json.dumps(positions, default=str)),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO kraken_portfolio (id, bot_id, cash_usd, positions)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            bot_id    = EXCLUDED.bot_id,
                            cash_usd  = EXCLUDED.cash_usd,
                            positions = EXCLUDED.positions
                        """,
                        (db_id, bot_id, cash_usd, json.dumps(positions, default=str)),
                    )
        return True
    except Exception as exc:
        logger.warning(f"DB | save_portfolio failed: {exc}")
        return False


def insert_trade(trade: dict) -> bool:
    if not _is_available():
        return False
    bot_id, db_id = _get_bot_config()
    try:
        closed_at = trade.get("closed_at")
        if isinstance(closed_at, str):
            try:
                closed_at = datetime.fromisoformat(closed_at)
            except Exception:
                closed_at = datetime.now(tz=timezone.utc)
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_trades
                        (bot_id, symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                         fees_usd, reason, closed_at, paper, order_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    """,
                    (
                        bot_id,
                        trade.get("symbol"),
                        trade.get("side"),
                        trade.get("entry_price", 0),
                        trade.get("exit_price", 0),
                        trade.get("pnl_pct", 0),
                        trade.get("pnl_usd", 0),
                        trade.get("fees_usd"),
                        trade.get("reason"),
                        closed_at,
                        trade.get("order_id"),
                    ),
                )
        return True
    except Exception as exc:
        logger.warning(f"DB | insert_trade failed: {exc}")
        return False


def load_all_trades(limit: int | None = None) -> list[dict]:
    if not _is_available():
        return []
    bot_id, db_id = _get_bot_config()
    try:
        sql = """
            SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                   fees_usd, reason, closed_at, paper, order_id
            FROM   kraken_trades
            WHERE  bot_id = %s
            ORDER  BY closed_at ASC
        """
        params: list = [bot_id]
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        cols = ("symbol", "side", "entry_price", "exit_price", "pnl_pct", "pnl_usd",
                "fees_usd", "reason", "closed_at", "paper", "order_id")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            if d.get("closed_at"):
                d["closed_at"] = d["closed_at"].isoformat()
            result.append(d)
        return result
    except Exception as exc:
        logger.warning(f"DB | load_all_trades failed: {exc}")
        return []
