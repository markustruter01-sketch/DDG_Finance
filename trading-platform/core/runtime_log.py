"""Keep the live deployment's important log lines for 30 days.

Replit keeps deployment logs for about a day; the 9 Nov stop incident was only
explained because someone read the logs within that window (finance-2027-plan.md
Step 2 item 13). This sink copies the lines that matter into the runtime_log
table:
  * WARNING and above from every module;
  * INFO from the modules that place, protect or reconcile orders.

Published deployment only. Lines are buffered and written in one insert every
15 s by a daemon thread, so logging never waits on the database. Rows older
than 30 days are deleted once a day. A database failure drops that batch and
is printed to stderr; it never raises into the caller.
"""
from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from datetime import datetime, timezone

from loguru import logger

RETENTION_DAYS = 30
FLUSH_SECONDS = 15
MAX_BUFFER = 5000
# loguru record["name"] prefixes whose INFO lines are kept (order path).
ORDER_PATH_MODULES = (
    "alpaca_etf_engine", "jerome_alpaca", "sgov_parking", "asia_trend_strategy",
    "bot3_hard_assets_strategy", "forex_ai_strategy", "forex_execution",
    "core.kill_switch", "core.oanda_trader", "core.degradation_resolver",
    "execution.", "sleeve_runtime.",
)

_installed = False


def keep(record: dict, *, process: str) -> bool:
    """Pure filter: which log records are worth keeping for 30 days."""
    if record["level"].no >= 30:  # WARNING
        return True
    if record["level"].no < 20:  # below INFO
        return False
    name = record["name"] or ""
    # The runner's own cycle lines (pause state, cycle results) run as __main__.
    return name.startswith(ORDER_PATH_MODULES) or (process == "runner" and name == "__main__")


class _Buffer:
    def __init__(self, process: str, dsn: str):
        self.process, self.dsn = process, dsn
        self.rows: list[tuple] = []
        self.lock = threading.Lock()
        self.last_prune = 0.0

    def sink(self, message) -> None:
        r = message.record
        row = (r["time"].astimezone(timezone.utc), self.process, r["level"].name,
               f"{r['name']}:{r['function']}:{r['line']}", r["message"][:4000].replace("\x00", ""))
        with self.lock:
            if len(self.rows) < MAX_BUFFER:
                self.rows.append(row)

    def flush(self) -> None:
        with self.lock:
            rows, self.rows = self.rows, []
        if not rows and time.time() - self.last_prune < 86400:
            return
        conn = None
        try:
            import psycopg2
            from psycopg2.extras import execute_values
            conn = psycopg2.connect(self.dsn, connect_timeout=10)
            with conn, conn.cursor() as cur:
                if rows:
                    execute_values(cur, "INSERT INTO runtime_log (ts, process, level, source, message) VALUES %s", rows)
                if time.time() - self.last_prune >= 86400:
                    cur.execute("DELETE FROM runtime_log WHERE ts < now() - make_interval(days => %s)", (RETENTION_DAYS,))
                    self.last_prune = time.time()
        except Exception as exc:  # never raise into logging
            print(f"runtime_log | dropped {len(rows)} lines: {exc}", file=sys.stderr)
        finally:
            if conn is not None:
                conn.close()

    def loop(self) -> None:
        while True:
            time.sleep(FLUSH_SECONDS)
            self.flush()


def install(process: str) -> bool:
    """Add the sink once per process. Published deployment only."""
    global _installed
    dsn = os.environ.get("DATABASE_URL")
    if _installed or os.environ.get("REPLIT_DEPLOYMENT") != "1" or not dsn:
        return False
    try:
        import psycopg2
        with psycopg2.connect(dsn, connect_timeout=10) as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS runtime_log ("
                " id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, process TEXT NOT NULL,"
                " level TEXT NOT NULL, source TEXT NOT NULL, message TEXT NOT NULL)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS runtime_log_ts_idx ON runtime_log (ts)")
        conn.close()
    except Exception as exc:
        logger.warning(f"runtime_log | not installed: {exc}")
        return False
    buffer = _Buffer(process, dsn)
    logger.add(buffer.sink, level="INFO", filter=lambda r: keep(r, process=process))
    threading.Thread(target=buffer.loop, name="runtime_log", daemon=True).start()
    atexit.register(buffer.flush)  # the last lines before a restart matter most
    _installed = True
    logger.info(f"runtime_log | keeping WARNING+ and order-path INFO for {RETENTION_DAYS} days ({process}, started {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)")
    return True
