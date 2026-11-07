"""Link health: when each outside connection last worked and last failed.

One row per link (OANDA, each Alpaca account, each AI provider, each news
source, the push to DDG Control). Callers report every success or failure; a
single failure never hides a later success, and vice versa. Read by
GET /connections, so anyone (Markus or Claude) can see at a glance whether a
link is actually broken before acting on an error message.

Non-fatal: never raises, never slows the caller (successes are written at most
every 5 minutes per link; failures always).
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

DDL = """
CREATE TABLE IF NOT EXISTS link_health (
    name        TEXT PRIMARY KEY,
    last_ok     TIMESTAMPTZ,
    last_fail   TIMESTAMPTZ,
    last_error  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
OK_WRITE_EVERY_SECONDS = 300
ERROR_MAX_CHARS = 200
_last_ok_write: dict[str, float] = {}
_ddl_done = False


def _conn():
    from db.postgres import get_conn
    return get_conn()


def record_link(name: str, ok: bool, error: str = "") -> None:
    """Report one success or failure for a link. Error text must already be safe to show."""
    global _ddl_done
    try:
        now = time.monotonic()
        if ok and now - _last_ok_write.get(name, -1e9) < OK_WRITE_EVERY_SECONDS:
            return
        with _conn() as conn, conn.cursor() as cur:
            if not _ddl_done:
                cur.execute(DDL)
                _ddl_done = True
            if ok:
                cur.execute(
                    """INSERT INTO link_health (name, last_ok) VALUES (%s, NOW())
                       ON CONFLICT (name) DO UPDATE SET last_ok = NOW(), updated_at = NOW()""",
                    (name[:80],),
                )
                _last_ok_write[name] = now
            else:
                cur.execute(
                    """INSERT INTO link_health (name, last_fail, last_error) VALUES (%s, NOW(), %s)
                       ON CONFLICT (name) DO UPDATE SET last_fail = NOW(), last_error = EXCLUDED.last_error,
                       updated_at = NOW()""",
                    (name[:80], (error or "failed")[:ERROR_MAX_CHARS]),
                )
    except (Exception, SystemExit) as exc:  # never break the caller (db.postgres exits on bad config at import)
        logger.debug(f"link_health | record {name} skipped: {type(exc).__name__}")


def state(last_ok: Any, last_fail: Any) -> str:
    """working: last success is newer than the last failure (or no failure).
    failing: the last thing that happened was a failure. unknown: nothing yet."""
    if last_ok is None and last_fail is None:
        return "unknown"
    if last_fail is None or (last_ok is not None and last_ok >= last_fail):
        return "working"
    return "failing"


def read_links() -> list[dict[str, Any]]:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("SELECT name, last_ok, last_fail, last_error FROM link_health ORDER BY name")
        rows = cur.fetchall()
    return [
        {"name": name, "state": state(ok, fail),
         "last_ok": ok.isoformat() if ok else None,
         "last_fail": fail.isoformat() if fail else None,
         "last_error": err if fail else None}
        for name, ok, fail, err in rows
    ]
