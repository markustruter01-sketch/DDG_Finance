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

Regime normalisation:
  All raw regime labels (e.g. "Crypto-Risk-Off", "Crypto [Reconstructed]",
  "Crypto-Bull") are mapped to canonical labels before any comparison:
    "Crypto"   — any label containing "crypto"
    "Bear"     — any label containing "bear"
    "Bull"     — any label containing "bull"
    "Sideways" — any label containing "sideways"
    "Unknown"  — everything else / None
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

# ---------------------------------------------------------------------------
# Canonical regime labels
# ---------------------------------------------------------------------------
CANONICAL_REGIMES = ("Crypto", "Bear", "Bull", "Sideways", "Unknown")


def normalise_regime(regime_label: str | None) -> str:
    """
    Map any raw regime label variant to one of the canonical labels:
      Crypto | Bear | Bull | Sideways | Unknown

    Examples:
      "Crypto-Risk-Off"          → "Crypto"
      "Crypto [Reconstructed]"   → "Crypto"
      "Crypto-Bull"              → "Crypto"   (crypto takes priority)
      "Bear [Reconstructed]"     → "Bear"
      "Sideways"                 → "Sideways"
      None / ""                  → "Unknown"
    """
    if not regime_label:
        return "Unknown"
    label = regime_label.strip().lower()
    if "crypto" in label:
        return "Crypto"
    if "bear" in label:
        return "Bear"
    if "bull" in label:
        return "Bull"
    if "sideways" in label:
        return "Sideways"
    return "Unknown"


# ---------------------------------------------------------------------------
# Internal DB helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_current_regime() -> str:
    """
    Return the current crypto regime label (raw, from JSON files).
    Callers should pass this through normalise_regime() before comparison.

    Primary  : crypto_regime.json
    Fallback : market_regime.json
    Default  : 'Unknown'
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

    All raw regime labels are normalised before aggregation, so variants like
    "Crypto [Reconstructed]" and "Crypto-Risk-Off" are merged under "Crypto".

    Returns a dict keyed by canonical regime name:
    {
      "Crypto": {
        "total_trades": 89,
        "win_rate": 0.27,
        "avg_pnl_usd": -50.50,
        "profit_factor": 0.22,
        "total_pnl_usd": -4495.0,
      },
      ...
    }
    """
    rows = _pg_query(
        """
        SELECT
            COALESCE(NULLIF(regime_at_entry, ''), 'Unknown') AS regime,
            pnl_usd
        FROM kraken_trades
        WHERE bot_id = %s
        """,
        (bot_id,),
    )

    # Aggregate in Python after normalising regime labels
    buckets: dict[str, dict] = {}
    for row in rows:
        canon = normalise_regime(str(row["regime"]))
        pnl   = float(row["pnl_usd"] or 0.0)
        if canon not in buckets:
            buckets[canon] = {"pnls": [], "wins": 0}
        buckets[canon]["pnls"].append(pnl)
        if pnl > 0:
            buckets[canon]["wins"] += 1

    matrix: dict[str, dict[str, Any]] = {}
    for regime, data in buckets.items():
        pnls         = data["pnls"]
        n            = len(pnls)
        wins         = data["wins"]
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss   = abs(sum(p for p in pnls if p < 0))
        total_pnl    = sum(pnls)
        avg_pnl      = total_pnl / n if n > 0 else 0.0
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else
            (float("inf") if gross_profit > 0 else 0.0)
        )

        matrix[regime] = {
            "total_trades":  n,
            "win_rate":      round(wins / n, 4) if n > 0 else 0.0,
            "avg_pnl_usd":   round(avg_pnl, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else 99.99,
            "total_pnl_usd": round(total_pnl, 2),
            "gross_profit":  round(gross_profit, 2),
            "gross_loss":    round(gross_loss, 2),
        }

    return matrix


def calculate_regime_size_multiplier(bot_id: str, current_regime: str) -> tuple[float, str]:
    """
    Deterministic regime-based position sizing multiplier.

    Normalises current_regime to a canonical label, then reads the last 30
    trades from that canonical regime for this bot.

    Returns: (multiplier, reason_string)
    """
    canonical = normalise_regime(current_regime)

    if canonical == "Unknown":
        return (1.0, f"Regime '{current_regime}' normalised to Unknown — normal sizing")

    # Build a LIKE pattern that matches all stored variants of this canonical regime
    # e.g. canonical="Crypto" → matches "Crypto [Reconstructed]", "Crypto-Risk-Off", etc.
    rows = _pg_query(
        """
        SELECT pnl_usd
        FROM kraken_trades
        WHERE bot_id = %s
          AND LOWER(COALESCE(regime_at_entry, '')) LIKE %s
        ORDER BY closed_at DESC
        LIMIT 30
        """,
        (bot_id, f"%{canonical.lower()}%"),
    )

    if not rows:
        return (1.0, f"No trade history for canonical regime '{canonical}' — normal sizing")

    pnls = [float(r["pnl_usd"]) for r in rows]
    n = len(pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = abs(sum(p for p in pnls if p < 0))

    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else
        (99.99 if gross_profit > 0 else 0.0)
    )

    raw_label = current_regime if current_regime != canonical else canonical

    if profit_factor < 0.8 and n >= 10:
        return (
            0.5,
            f"REGIME CAUTION: PF={profit_factor:.2f} < 0.80 over {n} trades in "
            f"'{canonical}' (raw: '{raw_label}') — halving position sizes",
        )
    elif profit_factor > 1.5 and n >= 20:
        return (
            1.25,
            f"REGIME BOOST: PF={profit_factor:.2f} > 1.50 over {n} trades in "
            f"'{canonical}' (raw: '{raw_label}') — increasing sizes 25%",
        )
    else:
        return (
            1.0,
            f"Regime '{canonical}' (raw: '{raw_label}'): PF={profit_factor:.2f} "
            f"over {n} trades — normal sizing",
        )
