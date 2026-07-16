"""
Shadow Signal Ledger — ARC 4 Part 2.
Decision-level data without execution: every candidate that passes technical
filters gets a row here regardless of whether an order fires.
Fire-and-forget — never raises; DB failure is non-fatal.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_shadow_signal(
    bot_id: str,
    symbol: str,
    *,
    side: str | None = None,
    entry_price_at_signal: float | None = None,
    score: float | None = None,
    conviction: float | None = None,
    regime_at_signal: str | None = None,
    executed: bool = False,
    skip_reason: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> None:
    """
    Insert one shadow-signal row.  Keyword-only after bot_id / symbol so
    callers must be explicit.  Never raises — all errors logged at DEBUG.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shadow_signals
                        (bot_id, symbol, side, entry_price_at_signal,
                         score, conviction, regime_at_signal,
                         executed, skip_reason, extra_context)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        bot_id,
                        symbol,
                        side,
                        entry_price_at_signal,
                        score,
                        conviction,
                        regime_at_signal,
                        executed,
                        skip_reason,
                        json.dumps(extra_context) if extra_context else None,
                    ),
                )
    except Exception as exc:
        logger.debug(f"shadow_signals | log_shadow_signal failed (non-fatal): {exc}")
