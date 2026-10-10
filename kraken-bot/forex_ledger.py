"""Forex decision ledger (Phase 4): one append-only row per New York trading day.

Rows can never be updated or deleted (database trigger). Each row stores the
full council record (pack, label map, exact prompts, raw replies, parsed
decisions, baseline calls, errors, token usage) and its SHA-256 fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
# Daily candles complete at the 17:00 New York close; wait a few minutes.
CYCLE_AFTER_NY = time(17, 5)

FOREX_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS forex_decision_ledger (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trading_day    DATE NOT NULL UNIQUE,
    status         TEXT NOT NULL CHECK (status IN ('shadow', 'no_trade')),
    low_confidence BOOLEAN,
    record         JSONB NOT NULL,
    record_sha256  TEXT NOT NULL
);

CREATE OR REPLACE FUNCTION forex_decision_ledger_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'forex_decision_ledger is append-only (id=%)', OLD.id;
END;
$$;

DROP TRIGGER IF EXISTS forex_decision_ledger_append_only_trigger
    ON forex_decision_ledger;
CREATE TRIGGER forex_decision_ledger_append_only_trigger
BEFORE UPDATE OR DELETE ON forex_decision_ledger
FOR EACH ROW EXECUTE FUNCTION forex_decision_ledger_append_only();
"""


def trading_day_due(now_utc: datetime) -> date | None:
    """The New York trading day whose close has passed, or None (weekend or
    before the close). Friday's close is decided on Friday's date."""
    ny = now_utc.astimezone(NEW_YORK)
    if ny.weekday() >= 5 or ny.time() < CYCLE_AFTER_NY:
        return None
    return ny.date()


def record_sha256(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_ledger(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(FOREX_LEDGER_DDL)


def already_logged(conn: Any, trading_day: date) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forex_decision_ledger WHERE trading_day = %s",
            (trading_day,),
        )
        return cur.fetchone() is not None


def append_cycle(conn: Any, trading_day: date, record: dict[str, Any]) -> str:
    digest = record_sha256(record)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forex_decision_ledger
                (trading_day, status, low_confidence, record, record_sha256)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (trading_day) DO NOTHING
            """,
            (
                trading_day,
                record["status"],
                record.get("low_confidence"),
                json.dumps(record, default=str),
                digest,
            ),
        )
    return digest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
