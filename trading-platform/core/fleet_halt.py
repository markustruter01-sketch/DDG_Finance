"""
fleet_halt.py — Fleet-wide emergency halt flag.

A single PostgreSQL row (fleet_halt WHERE id=1) acts as a cross-process
kill switch. Every bot checks this at the start of each cycle.
Setting active=True stops all new entries across the entire fleet.

This is the ONE command that stops everything:
    POST /trading-api/fleet/halt
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

logger = logging.getLogger("fleet_halt")

_CACHE: dict = {"active": False, "checked_at": 0.0}
_CACHE_TTL = 30.0  # seconds — re-check DB every 30s max


def is_halted() -> bool:
    """
    Return True if the fleet halt flag is active.
    Cached for 30 seconds to avoid hammering the DB every cycle.
    """
    import time
    now = time.time()
    if now - _CACHE["checked_at"] < _CACHE_TTL:
        return _CACHE["active"]

    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return False  # fail-open: don't halt if DB is down
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT active FROM fleet_halt WHERE id = 1")
                row = cur.fetchone()
                active = bool(row[0]) if row else False
        _CACHE["active"] = active
        _CACHE["checked_at"] = now
        return active
    except Exception as exc:
        # C-2 fix: fail-HALTED when DB is unavailable.
        # If we have a prior successful read in the cache, honour it — an operator
        # halt written before the DB flap must still propagate.  If the cache is
        # cold (first check, DB never reached), fail HALTED rather than fail-open.
        if _CACHE["checked_at"] > 0:
            logger.warning(
                f"FleetHalt | DB check failed — returning cached value "
                f"(active={_CACHE['active']}, "
                f"{int(now - _CACHE['checked_at'])}s ago): {exc}"
            )
            return _CACHE["active"]
        logger.warning(
            f"FleetHalt | DB check failed with NO cached state — "
            f"failing HALTED (fail-closed) to protect capital: {exc}"
        )
        return True


def set_halt(active: bool, reason: str = "", halted_by: str = "operator") -> bool:
    """Write the halt flag to DB. Returns True on success."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return False
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE fleet_halt SET
                        active     = %s,
                        reason     = %s,
                        halted_at  = CASE WHEN %s THEN NOW() ELSE halted_at END,
                        halted_by  = %s,
                        updated_at = NOW()
                    WHERE id = 1
                """, (active, reason, active, halted_by))
            conn.commit()
        _CACHE["active"] = active
        _CACHE["checked_at"] = 0.0  # force re-read on next check
        action = "HALTED" if active else "RESUMED"
        logger.warning(f"FleetHalt | Fleet {action} — reason: {reason} — by: {halted_by}")
        return True
    except Exception as exc:
        logger.error(f"FleetHalt | Failed to set halt flag: {exc}")
        return False


def get_status() -> dict:
    """Return current halt status for API/dashboard."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {"active": False, "reason": None, "halted_at": None, "error": "db_unavailable"}
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT active, reason, halted_at, halted_by, updated_at FROM fleet_halt WHERE id = 1"
                )
                row = cur.fetchone()
        if not row:
            return {"active": False, "reason": None, "halted_at": None}
        return {
            "active":     bool(row[0]),
            "reason":     row[1],
            "halted_at":  row[2].isoformat() if row[2] else None,
            "halted_by":  row[3],
            "updated_at": row[4].isoformat() if row[4] else None,
        }
    except Exception as exc:
        return {"active": False, "error": str(exc)}
