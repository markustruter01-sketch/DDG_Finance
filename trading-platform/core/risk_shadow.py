"""Record-only log of the fleet drawdown limits (core/risk_limits.py).

Append-only table risk_limit_shadow, one row per event:
- 'breached' / 'cleared': the fleet crossed a limit (checked with every kill
  switch snapshot, every 5 minutes by default);
- 'would_refuse': a sleeve asked for new risk while the soft limit was
  breached; the governor let it through (record only) and logged it here.
Never raises: a failed write is logged and the caller carries on.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from loguru import logger

from core.risk_limits import HARD_DRAWDOWN, SOFT_DRAWDOWN, WOULD_HAVE

DDL = """
CREATE TABLE IF NOT EXISTS risk_limit_shadow (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    limit_name     TEXT NOT NULL,
    event          TEXT NOT NULL,
    threshold      DOUBLE PRECISION NOT NULL,
    fleet_drawdown DOUBLE PRECISION,
    fleet_equity   DOUBLE PRECISION,
    fleet_hwm      DOUBLE PRECISION,
    would_have     TEXT NOT NULL,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb
)
"""
LIMITS = (("governor_soft", SOFT_DRAWDOWN), ("kill_switch_hard", HARD_DRAWDOWN))


def fleet_drawdown(snapshot: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(drawdown, equity, hwm) from a live snapshot; drawdown None if unknown."""
    try:
        equity = float(snapshot.get("fleet_equity"))
        hwm = float(snapshot.get("fleet_hwm") or equity)
    except (TypeError, ValueError):
        return None, None, None
    if equity <= 0 or hwm <= 0:
        return None, equity, hwm
    return max(0.0, (hwm - equity) / hwm), equity, hwm


def _default_conn():
    from db.postgres import get_conn
    return get_conn()


def _insert(cur, limit_name: str, event: str, threshold: float, dd, equity, hwm, detail: dict) -> None:
    cur.execute(
        """INSERT INTO risk_limit_shadow
           (limit_name, event, threshold, fleet_drawdown, fleet_equity, fleet_hwm, would_have, detail)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
        (limit_name, event, threshold, dd, equity, hwm, WOULD_HAVE[limit_name],
         json.dumps(detail, default=str)),
    )


def record_drawdown_episodes(snapshot: dict[str, Any], get_conn: Callable[[], Any] | None = None) -> list[str]:
    """Write 'breached' / 'cleared' when the fleet crosses a limit since the
    last recorded state. Returns the events written."""
    dd, equity, hwm = fleet_drawdown(snapshot)
    if dd is None:
        return []
    written: list[str] = []
    try:
        with (get_conn or _default_conn)() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            for name, threshold in LIMITS:
                cur.execute("""SELECT event FROM risk_limit_shadow
                               WHERE limit_name = %s AND event IN ('breached', 'cleared')
                               ORDER BY id DESC LIMIT 1""", (name,))
                row = cur.fetchone()
                was_breached = bool(row) and row[0] == "breached"
                now_breached = dd > threshold
                if now_breached != was_breached:
                    event = "breached" if now_breached else "cleared"
                    _insert(cur, name, event, threshold, dd, equity, hwm, {})
                    written.append(f"{name}:{event}")
        for item in written:
            logger.warning(f"Risk limits (record only) | {item} | fleet drawdown {dd:.2%}")
    except Exception as exc:
        logger.error(f"Risk limits | shadow record failed: {type(exc).__name__}: {exc}")
    return written


def record_would_refuse(dd: float, snapshot: dict[str, Any], reasons: list[str],
                        get_conn: Callable[[], Any] | None = None) -> None:
    """The governor let new risk through that an enforced limit would have refused."""
    _, equity, hwm = fleet_drawdown(snapshot)
    try:
        with (get_conn or _default_conn)() as conn, conn.cursor() as cur:
            cur.execute(DDL)
            _insert(cur, "governor_soft", "would_refuse", SOFT_DRAWDOWN, dd, equity, hwm,
                    {"reasons": reasons[:10]})
        logger.warning(f"Risk governor (record only) | would have refused new risk | {reasons[:3]}")
    except Exception as exc:
        logger.error(f"Risk governor | shadow record failed: {type(exc).__name__}: {exc}")
