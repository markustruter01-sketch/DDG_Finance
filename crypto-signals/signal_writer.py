"""
signal_writer.py — Read/write crypto_signals table.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.insert(0, _TRADING_PLATFORM)


def _get_conn():
    from db.postgres import get_conn
    return get_conn()


def write_signal(
    signal_type: str,
    asset: str,
    severity: str = "medium",
    payload: Optional[dict] = None,
) -> int:
    """Insert a new signal row. Returns the new row id."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crypto_signals
                    (signal_type, asset, severity, payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (signal_type, asset, severity, json.dumps(payload or {})),
            )
            row = cur.fetchone()
            return int(row[0]) if row else -1


def read_unprocessed_signals(signal_type: Optional[str] = None) -> list[dict]:
    """Return unprocessed signals, optionally filtered by type."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            if signal_type:
                cur.execute(
                    """
                    SELECT id, signal_type, asset, severity, detected_at, payload
                    FROM crypto_signals
                    WHERE processed = FALSE AND signal_type = %s
                    ORDER BY detected_at ASC
                    """,
                    (signal_type,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, signal_type, asset, severity, detected_at, payload
                    FROM crypto_signals
                    WHERE processed = FALSE
                    ORDER BY detected_at ASC
                    """
                )
            cols = ["id", "signal_type", "asset", "severity", "detected_at", "payload"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_processed(signal_id: int) -> None:
    """Mark a signal as processed."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crypto_signals
                SET processed = TRUE, processed_at = NOW()
                WHERE id = %s
                """,
                (signal_id,),
            )
