"""Nightly GEAR-V1-G4 shadow run (no orders) and its one-row-per-day record.

The replay itself lives in sleeve_runtime/gear_shadow.py (shared with the
research code); this module only schedules it, stores the result and reads
it back for the dashboard.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

SLEEVE_ID = "GEAR-V1-G4"
DDL = """
CREATE TABLE IF NOT EXISTS sleeve_shadow_daily (
    sleeve_id   TEXT NOT NULL,
    as_of       DATE NOT NULL,
    payload     JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (sleeve_id, as_of)
)
"""


def _repo_on_path() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.append(str(root))


def run_and_store(now: datetime | None = None, fetch=None) -> dict[str, Any]:
    _repo_on_path()
    from config.settings import settings
    from sleeve_runtime.gear_shadow import alpaca_ohlc_fetcher, run_gear_shadow

    now = now or datetime.now(timezone.utc)
    fetch = fetch or alpaca_ohlc_fetcher(settings.alpaca_api_key, settings.alpaca_secret_key)
    result = run_gear_shadow(fetch, now)
    logger.info(f"GEAR-V1-G4 shadow | {json.dumps(result, default=str)[:600]}")
    if result.get("status") == "ok":
        from db.postgres import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute(
                """INSERT INTO sleeve_shadow_daily (sleeve_id, as_of, payload) VALUES (%s, %s, %s::jsonb)
                   ON CONFLICT (sleeve_id, as_of) DO UPDATE SET payload = EXCLUDED.payload, recorded_at = NOW()""",
                (SLEEVE_ID, result["as_of"], json.dumps(result, default=str)),
            )
    return result


def history(limit: int = 400) -> list[dict[str, Any]]:
    """Stored daily results, oldest first. Empty if none yet or unreadable."""
    try:
        from db.postgres import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('sleeve_shadow_daily')")
            if cur.fetchone()[0] is None:
                return []
            cur.execute("""SELECT as_of::text, payload FROM sleeve_shadow_daily
                           WHERE sleeve_id = %s ORDER BY as_of DESC LIMIT %s""", (SLEEVE_ID, limit))
            rows = cur.fetchall()
    except Exception as exc:
        logger.debug(f"gear shadow history unreadable: {exc}")
        return []
    return [{"as_of": d, **(p if isinstance(p, dict) else json.loads(p))} for d, p in reversed(rows)]
