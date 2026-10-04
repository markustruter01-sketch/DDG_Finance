"""
trading-platform/core/bot_state.py
Single source of truth for bot pause state, heartbeat, and status.

Reads/writes the bots_state table. Every bot dual-writes here alongside
their legacy tables during the migration period (Phase 1).

After migration is complete and verified:
  - Remove legacy control-file checks from each bot
  - Remove dual-writes, keep only this module
  - Drop kraken_heartbeat / forex_heartbeat dependency from fleet_equity
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from loguru import logger

_TP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TP not in sys.path:
    sys.path.insert(0, _TP)

from core.bot_registry import active_bot_ids, normalise_bot_id

# Includes paused but registered bots; retired identities stay excluded.
ACTIVE_BOT_IDS = set(active_bot_ids())


def _canonical(bot_id: str) -> str:
    """Resolve legacy identifiers without allowing unknown DB keys."""
    return normalise_bot_id(bot_id) or bot_id


def _get_conn():
    from db.postgres import get_conn
    return get_conn()


def write_heartbeat(
    bot_id: str,
    equity: float,
    cash: float = 0.0,
    positions: int = 0,
    status: str = "running",
    error: str = "",
) -> None:
    """Write heartbeat to bots_state. Non-fatal — never raises."""
    bot_id = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bots_state
                        (bot_id, equity_usd, cash_usd, open_positions,
                         last_heartbeat, status, error_message)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s)
                    ON CONFLICT (bot_id) DO UPDATE SET
                        equity_usd     = EXCLUDED.equity_usd,
                        cash_usd       = EXCLUDED.cash_usd,
                        open_positions = EXCLUDED.open_positions,
                        last_heartbeat = NOW(),
                        status         = EXCLUDED.status,
                        error_message  = EXCLUDED.error_message
                    """,
                    (bot_id, round(equity, 2), round(cash, 2),
                     positions, status, error or ""),
                )
    except Exception as exc:
        logger.debug(f"BotState | write_heartbeat({bot_id}) failed (non-fatal): {exc}")


def touch_heartbeat(bot_id: str, status: str = "running", error: str = "") -> None:
    """Update only last_heartbeat, status, and error_message — never touches equity_usd.
    Used by runner.py which has no access to equity (leaf cycle fns return None)."""
    bot_id = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bots_state
                       SET last_heartbeat = NOW(),
                           status         = %s,
                           error_message  = %s
                     WHERE bot_id = %s
                    """,
                    (status, error or "", bot_id),
                )
    except Exception as exc:
        logger.debug(f"BotState | touch_heartbeat({bot_id}) failed (non-fatal): {exc}")


def is_paused(bot_id: str) -> bool:
    """Check if a bot is paused. Falls back to False if row missing or DB unavailable."""
    bot_id = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT paused FROM bots_state WHERE bot_id = %s",
                    (bot_id,),
                )
                row = cur.fetchone()
                return bool(row[0]) if row else False
    except Exception as exc:
        logger.debug(f"BotState | is_paused({bot_id}) failed (non-fatal): {exc}")
        return False


def set_paused(bot_id: str, paused: bool, reason: str = "") -> None:
    """Pause or unpause a bot in bots_state."""
    bot_id = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bots_state
                       SET paused       = %s,
                           pause_reason = %s,
                           paused_at    = CASE WHEN %s THEN NOW() ELSE paused_at END
                     WHERE bot_id = %s
                    """,
                    (paused, reason, paused, bot_id),
                )
    except Exception as exc:
        logger.debug(f"BotState | set_paused({bot_id}) failed (non-fatal): {exc}")


def get_bot_state(bot_id: str) -> dict:
    """Return full bots_state row for a bot as a dict. Returns {} if not found."""
    bot_id = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM bots_state WHERE bot_id = %s",
                    (bot_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return {}
                cols = [desc[0] for desc in cur.description]
                d = dict(zip(cols, row))
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                return d
    except Exception as exc:
        logger.debug(f"BotState | get_bot_state({bot_id}) failed (non-fatal): {exc}")
        return {}


def get_all_states() -> list[dict]:
    """Return all bots_state rows ordered by bot_id."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM bots_state ORDER BY bot_id")
                cols = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(zip(cols, row))
                    for k, v in d.items():
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    result.append(d)
                return result
    except Exception as exc:
        logger.debug(f"BotState | get_all_states failed (non-fatal): {exc}")
        return []


# ── Portfolio helpers (Stage 2) ────────────────────────────────────────────

def get_portfolio(bot_id: str) -> dict:
    """Read portfolio for a bot. Returns dict with keys:
    bot_id, starting_usd, cash_usd, equity_usd, positions, updated_at, metadata.
    Resolves legacy BOT_ID env-var values via LEGACY_TO_CANONICAL first."""
    canonical = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM bot_portfolio WHERE bot_id = %s",
                    (canonical,),
                )
                row = cur.fetchone()
                if row is None:
                    return {}
                cols = [desc[0] for desc in cur.description]
                d = dict(zip(cols, row))
                for k, v in d.items():
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                return d
    except Exception as exc:
        logger.debug(f"BotState | get_portfolio({bot_id}) failed (non-fatal): {exc}")
        return {}


def touch_portfolio(bot_id: str) -> None:
    """Touch last_updated only — no equity/cash change. Called on market-closed
    pipeline cycles so oracle heartbeat stays fresh without overwriting live data."""
    canonical = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE bot_portfolio SET last_updated = NOW() WHERE bot_id = %s",
                    (canonical,),
                )
    except Exception as exc:
        logger.debug(f"BotState | touch_portfolio({bot_id}) failed (non-fatal): {exc}")


def write_portfolio(
    bot_id: str,
    cash: float,
    equity: float,
    positions: list,
) -> None:
    """UPSERT portfolio state. Called by bot at end of every cycle.
    Resolves legacy BOT_ID env-var values via LEGACY_TO_CANONICAL first."""
    import json as _json
    canonical = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_portfolio
                        (bot_id, cash_usd, equity_usd, positions, last_updated)
                    VALUES (%s, %s, %s, %s::jsonb, NOW())
                    ON CONFLICT (bot_id) DO UPDATE SET
                        cash_usd     = EXCLUDED.cash_usd,
                        equity_usd   = EXCLUDED.equity_usd,
                        positions    = EXCLUDED.positions,
                        last_updated = NOW()
                    """,
                    (
                        canonical,
                        round(cash, 2),
                        round(equity, 2),
                        _json.dumps(positions),
                    ),
                )
    except Exception as exc:
        logger.debug(f"BotState | write_portfolio({bot_id}) failed (non-fatal): {exc}")


def add_position(bot_id: str, position: dict) -> None:
    """Append a position to bot's positions array (atomic jsonb append).
    Resolves legacy BOT_ID env-var values via LEGACY_TO_CANONICAL first."""
    import json as _json
    canonical = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bot_portfolio
                       SET positions = positions || %s::jsonb
                     WHERE bot_id = %s
                    """,
                    (_json.dumps([position]), canonical),
                )
    except Exception as exc:
        logger.debug(f"BotState | add_position({bot_id}) failed (non-fatal): {exc}")


def remove_position(bot_id: str, symbol: str) -> None:
    """Remove a position by symbol from bot's positions array (atomic filter).
    Resolves legacy BOT_ID env-var values via LEGACY_TO_CANONICAL first."""
    canonical = _canonical(bot_id)
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE bot_portfolio
                       SET positions = (
                           SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                             FROM jsonb_array_elements(positions) elem
                            WHERE elem->>'symbol' != %s
                       )
                     WHERE bot_id = %s
                    """,
                    (symbol, canonical),
                )
    except Exception as exc:
        logger.debug(f"BotState | remove_position({bot_id}, {symbol}) failed (non-fatal): {exc}")


def get_all_portfolios() -> list[dict]:
    """Return all bot portfolios ordered by bot_id (for fleet equity calculation)."""
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM bot_portfolio "
                    "WHERE bot_id = ANY(%s) ORDER BY bot_id",
                    (list(ACTIVE_BOT_IDS),),
                )
                cols = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(zip(cols, row))
                    for k, v in d.items():
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    result.append(d)
                return result
    except Exception as exc:
        logger.debug(f"BotState | get_all_portfolios failed (non-fatal): {exc}")
        return []
