"""
core/market_state.py — Market State Engine (MSE)
-------------------------------------------------
Computes current regime for display and trading gates.

Regime labels:
  BULL   — SPY >= 200SMA AND 20d return > -12%  (normal trading)
  BEAR   — SPY < 200SMA AND 20d return > -12%   (display only, NO gate)
  CRISIS — SPY 20d return <= -12%               (validated gate, Pass C OOS)

HIGH_VOL flag:
  SPY 10-day realized volatility > 30% annualised

CRISIS trading gate (Pass C validated: pooled Sharpe +0.633 vs +0.599 baseline):
  • Block ALL new entries, both longs AND shorts.
  • Exception: TLT / GLD / IEF eligible as longs only, capped at 2 total
    safe-haven positions. Sized at 0.5× (MSE_HIGH_VOL_SCALE).
  • Exits are NEVER gated.

BEAR / BULL: NO trading effect — computed for visibility only.

Dual-gate coexistence:
  Live fast gate (algo_scanner.py + executor.py):
    SPY close > 200SMA AND 5d return > -3% → long-only brake (Oracle only)
  CRISIS gate (this module, all bots):
    SPY 20d return <= -12% → both-sides block + safe-haven rotation
  These are COMPLEMENTARY:
    — Fast gate has shorter lookback; fires first in moderate sell-offs.
    — CRISIS gate has deeper lookback (-12% / 20d); fires in severe crashes.
    — Both can be active simultaneously; CRISIS is the more restrictive when so.
    — Neither gates exits.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

from loguru import logger

# ── Constants (authoritative for all modules) ─────────────────────────────────

MSE_CRISIS_THRESHOLD:    float              = -0.12
MSE_CRISIS_LOOKBACK:     int                = 20    # trading days for 20d return
MSE_HIGH_VOL_LOOKBACK:   int                = 10    # trading days for realized vol
MSE_HIGH_VOL_ANN:        float              = 0.30  # 30% annualised → HIGH_VOL
MSE_SAFE_HAVENS:         frozenset[str]     = frozenset({"TLT", "GLD", "IEF"})
MSE_SAFE_HAVEN_MAX:      int                = 2
MSE_HIGH_VOL_SCALE:      float              = 0.50  # 0.5× sizing for safe-havens in CRISIS


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _compute_from_spy_closes(closes: list[float]) -> dict[str, Any]:
    """
    Given a list of SPY daily closes (oldest first), return the full MSE state dict.
    Requires at least 201 bars for full computation; degrades gracefully with fewer.
    """
    n = len(closes)
    spy_close    = float(closes[-1]) if n >= 1 else None
    spy_20d_ret  = None
    spy_200sma   = None
    spy_10d_vol  = None

    # 20-day return (CRISIS trigger)
    if n >= MSE_CRISIS_LOOKBACK + 1:
        spy_20d_ret = spy_close / float(closes[-(MSE_CRISIS_LOOKBACK + 1)]) - 1

    # 200-day SMA (BEAR / BULL display)
    if n >= 200:
        spy_200sma = float(sum(closes[-200:]) / 200)

    # 10-day realized vol (HIGH_VOL flag)
    if n >= MSE_HIGH_VOL_LOOKBACK + 1:
        daily_rets = [
            closes[-i] / closes[-i - 1] - 1
            for i in range(1, MSE_HIGH_VOL_LOOKBACK + 1)
        ]
        spy_10d_vol = statistics.stdev(daily_rets) * math.sqrt(252)

    # ── Regime classification ───────────────────────────────────────────────
    # CRISIS dominates: -12% 20d return regardless of 200SMA relationship
    if spy_20d_ret is not None and spy_20d_ret <= MSE_CRISIS_THRESHOLD:
        regime = "CRISIS"
    elif spy_close is not None and spy_200sma is not None and spy_close < spy_200sma:
        regime = "BEAR"
    else:
        regime = "BULL"

    high_vol = bool(spy_10d_vol is not None and spy_10d_vol > MSE_HIGH_VOL_ANN)

    return {
        "regime":      regime,
        "high_vol":    high_vol,
        "spy_close":   round(spy_close,   4) if spy_close   is not None else None,
        "spy_20d_ret": round(spy_20d_ret, 6) if spy_20d_ret is not None else None,
        "spy_200sma":  round(spy_200sma,  4) if spy_200sma  is not None else None,
        "spy_10d_vol": round(spy_10d_vol, 6) if spy_10d_vol is not None else None,
        "computed_at": _now_utc().isoformat(),
        "data_bars":   n,
    }


def _persist_state(state: dict) -> None:
    """Write state snapshot to the market_state table (best-effort, non-fatal)."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO market_state
                        (regime, high_vol, spy_close, spy_20d_ret, spy_200sma, spy_10d_vol)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        state["regime"],
                        state["high_vol"],
                        state.get("spy_close"),
                        state.get("spy_20d_ret"),
                        state.get("spy_200sma"),
                        state.get("spy_10d_vol"),
                    ),
                )
    except Exception as exc:
        logger.debug(f"MSE | persist_state non-fatal: {exc}")


def _fetch_historical_states(limit: int = 5) -> list[dict]:
    """Return the most recent `limit` rows from market_state."""
    try:
        import psycopg2.extras
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT recorded_at, regime, high_vol, spy_close, spy_20d_ret,
                           spy_200sma, spy_10d_vol
                    FROM market_state
                    ORDER BY recorded_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug(f"MSE | fetch_historical_states non-fatal: {exc}")
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_market_state(persist: bool = True) -> dict[str, Any]:
    """
    Compute the current MSE regime and return a state dict.

    Parameters
    ----------
    persist : bool
        If True (default) write a snapshot to the market_state DB table.
        Set to False when calling from notification/report paths that don't
        need another DB row (e.g. the Discord daily report).

    Returns
    -------
    dict with keys:
        regime      : "BULL" | "BEAR" | "CRISIS"
        high_vol    : bool
        spy_close   : float | None
        spy_20d_ret : float | None   (e.g. -0.134 = -13.4%)
        spy_200sma  : float | None
        spy_10d_vol : float | None   (annualised)
        computed_at : ISO-8601 string
        data_bars   : int
        error       : str | None     (if SPY data unavailable)
    """
    try:
        from data.yfinance_client import get_cached_momentum_data
        cache = get_cached_momentum_data() or {}
        spy_data = (cache.get("by_ticker") or {}).get("SPY") or {}
        closes   = list(spy_data.get("closes") or [])

        if len(closes) < MSE_CRISIS_LOOKBACK + 1:
            logger.warning(
                f"MSE | Insufficient SPY data ({len(closes)} bars, "
                f"need {MSE_CRISIS_LOOKBACK + 1}) — fail-safe CRISIS (entries blocked until real data)"
            )
            return {
                "regime": "CRISIS", "high_vol": False, "spy_close": None,
                "spy_20d_ret": None, "spy_200sma": None, "spy_10d_vol": None,
                "computed_at": _now_utc().isoformat(), "data_bars": len(closes),
                "fail_safe": True,
                "fail_safe_reason": f"insufficient_data ({len(closes)} bars — need {MSE_CRISIS_LOOKBACK + 1})",
                "error": None,
            }

        state = _compute_from_spy_closes(closes)

        if persist:
            _persist_state(state)

        logger.info(
            f"MSE | regime={state['regime']}  high_vol={state['high_vol']}  "
            f"SPY={state.get('spy_close')}  20d={state.get('spy_20d_ret'):+.3f}"
            if state.get("spy_20d_ret") is not None else
            f"MSE | regime={state['regime']}  high_vol={state['high_vol']}"
        )
        state["error"]     = None
        state["fail_safe"] = False
        return state

    except Exception as exc:
        logger.warning(f"MSE | get_market_state failed: {exc} — fail-safe CRISIS active")
        return {
            "regime": "CRISIS", "high_vol": False, "spy_close": None,
            "spy_20d_ret": None, "spy_200sma": None, "spy_10d_vol": None,
            "computed_at": _now_utc().isoformat(), "data_bars": 0,
            "fail_safe": True,
            "fail_safe_reason": f"computation_error: {exc}",
            "error": str(exc),
        }


def is_crisis() -> bool:
    """
    Fast boolean check: is SPY in CRISIS right now?

    Used by bot entry gates that need a simple True/False without building
    the full state dict. Does NOT persist to DB (read-only).
    """
    try:
        state = get_market_state(persist=False)
        return state.get("regime") == "CRISIS"
    except Exception:
        return False


def get_market_state_with_history(history_limit: int = 5) -> dict[str, Any]:
    """
    Returns the current state plus the last `history_limit` DB rows.
    Used by GET /trading-api/market-state.
    """
    state   = get_market_state(persist=True)
    history = _fetch_historical_states(limit=history_limit)
    return {**state, "history": history}
