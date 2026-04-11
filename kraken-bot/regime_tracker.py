"""
regime_tracker.py — Regime-conditional strategy performance matrix (Stage 1).

Tracks how each Kraken bot performs in different market regimes and
computes regime-based position sizing multipliers.

Called at the start of each trading cycle to:
  1. get_regime_performance_matrix(bot_id) — per-bot, per-regime stats
  2. calculate_regime_size_multiplier(bot_id, current_regime) — deterministic sizing multiplier

Multiplier rules:
  profit_factor < 0.8  AND trades >= 10  → 0.50  (halve size — regime hurting us)
  profit_factor > 1.50 AND trades >= 20  → 1.25  (boost size — regime favouring us)
  else                                   → 1.00  (normal sizing)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("regime_tracker")

_DB_URL = os.environ.get("DATABASE_URL")
_CRYPTO_REGIME_FILE = Path(__file__).parent.parent / "trading-platform" / "data" / "crypto_regime.json"
_MARKET_REGIME_FILE = Path(__file__).parent.parent / "trading-platform" / "data" / "market_regime.json"


def _pg_query(sql: str, params: tuple = ()) -> list[dict]:
    if not _DB_URL:
        return []
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(_DB_URL)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"RegimeTracker | pg_query failed: {exc}")
        return []


def get_current_regime() -> str:
    """
    Return the current crypto regime label.
    Primary: crypto_regime.json — fallback: market_regime.json — fallback: 'Unknown'
    """
    try:
        if _CRYPTO_REGIME_FILE.exists():
            data = json.loads(_CRYPTO_REGIME_FILE.read_text())
            regime = data.get("crypto_regime") or data.get("regime", "")
            if regime and regime != "unknown":
                return regime
    except Exception as exc:
        logger.debug(f"RegimeTracker | crypto_regime.json read failed: {exc}")

    try:
        if _MARKET_REGIME_FILE.exists():
            data = json.loads(_MARKET_REGIME_FILE.read_text())
            regime = data.get("regime", "")
            if regime and regime != "unknown":
                return regime
    except Exception as exc:
        logger.debug(f"RegimeTracker | market_regime.json read failed: {exc}")

    return "Unknown"


def get_regime_performance_matrix(bot_id: str) -> dict[str, dict[str, Any]]:
    """
    Calculate per-regime performance metrics from kraken_trades for a specific bot.

    Returns a dict keyed by regime name:
    {
      "Crypto-Bull": {
        "total_trades": 42,
        "win_rate": 0.52,
        "avg_pnl_usd": 12.4,
        "profit_factor": 1.35,
        "total_pnl_usd": 520.8,
      },
      ...
    }
    """
    rows = _pg_query(
        """
        SELECT
            COALESCE(NULLIF(regime_at_entry, ''), 'Unknown') AS regime,
            COUNT(*)::int                                      AS total_trades,
            COUNT(*) FILTER (WHERE pnl_usd > 0)::int          AS wins,
            SUM(pnl_usd)                                       AS total_pnl_usd,
            SUM(pnl_usd) FILTER (WHERE pnl_usd > 0)           AS gross_profit,
            ABS(SUM(pnl_usd) FILTER (WHERE pnl_usd <= 0))     AS gross_loss,
            AVG(pnl_usd)                                       AS avg_pnl_usd
        FROM kraken_trades
        WHERE bot_id = %s
        GROUP BY 1
        ORDER BY total_trades DESC
        """,
        (bot_id,),
    )

    matrix: dict[str, dict[str, Any]] = {}
    for row in rows:
        regime = str(row["regime"])
        gross_profit = float(row["gross_profit"] or 0.0)
        gross_loss   = float(row["gross_loss"]   or 0.0)
        total_trades = int(row["total_trades"])
        wins         = int(row["wins"])

        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else
            (float("inf") if gross_profit > 0 else 0.0)
        )

        matrix[regime] = {
            "total_trades":  total_trades,
            "win_rate":      round(wins / total_trades, 4) if total_trades > 0 else 0.0,
            "avg_pnl_usd":   round(float(row["avg_pnl_usd"] or 0.0), 2),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else 99.99,
            "total_pnl_usd": round(float(row["total_pnl_usd"] or 0.0), 2),
            "gross_profit":  round(gross_profit, 2),
            "gross_loss":    round(gross_loss, 2),
        }

    return matrix


def calculate_regime_size_multiplier(bot_id: str, current_regime: str) -> tuple[float, str]:
    """
    Deterministic regime-based position sizing multiplier.

    Reads the last 20+ trades in the current regime for this bot,
    calculates the profit factor, and applies the sizing rules.

    Returns: (multiplier, reason_string)
    """
    rows = _pg_query(
        """
        SELECT pnl_usd
        FROM kraken_trades
        WHERE bot_id = %s
          AND (
            regime_at_entry = %s
            OR regime_at_entry LIKE %s
          )
        ORDER BY closed_at DESC
        LIMIT 30
        """,
        (bot_id, current_regime, f"%{current_regime}%"),
    )

    if not rows:
        return (1.0, f"No trade history in regime '{current_regime}' — normal sizing")

    pnls = [float(r["pnl_usd"]) for r in rows]
    n = len(pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = abs(sum(p for p in pnls if p < 0))

    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else
        (99.99 if gross_profit > 0 else 0.0)
    )

    if profit_factor < 0.8 and n >= 10:
        return (
            0.5,
            f"REGIME CAUTION: profit_factor={profit_factor:.2f} < 0.8 over {n} trades "
            f"in '{current_regime}' — halving position sizes",
        )
    elif profit_factor > 1.5 and n >= 20:
        return (
            1.25,
            f"REGIME BOOST: profit_factor={profit_factor:.2f} > 1.5 over {n} trades "
            f"in '{current_regime}' — increasing position sizes 25%",
        )
    else:
        return (
            1.0,
            f"Regime '{current_regime}': profit_factor={profit_factor:.2f} over {n} trades — normal sizing",
        )
