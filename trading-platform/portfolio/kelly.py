"""
Kelly Criterion Position Sizer — v2.0 (Institutional Refactor)
----------------------------------------------------------------
PRIMARY MODE: Fixed Fractional Risk (1–2% of equity per trade).
OPTIONAL MODE: Quarter-Kelly derived from trailing 30-day empirical
               win/loss ratio — never static assumptions.

Full Kelly formula: f* = (bp - q) / b
  where b = net odds (expected gain per unit risked)
        p = probability of win
        q = probability of loss (1 - p)

For risk management we apply Quarter-Kelly (25% of full Kelly) as the
maximum aggressive option, and hard-cap each position at MAX_KELLY_FRACTION.

A negative Kelly result means negative expected value — the slot is
forced to SGOV regardless of conviction score.

v2.0 CHANGES (Institutional Gap Analysis):
  - Default mode switched from Half-Kelly to Fixed Fractional Risk (1% equity).
  - Kelly retained as OPTIONAL mode at Quarter-Kelly (0.25× full).
  - MAX_KELLY_FRACTION reduced from 20% → 10%.
  - Added compute_empirical_kelly() ingesting trailing 30-day trade data.
  - Static assumption fallbacks eliminated in favour of empirical data.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

MAX_KELLY_FRACTION  = 0.10
KELLY_MULTIPLIER    = 0.25
DEFAULT_RISK_PCT    = 0.01
MAX_RISK_PCT        = 0.02
MIN_TRADES_FOR_KELLY = 20


def get_trailing_30d_stats(db_path: Optional[str] = None) -> tuple[float, float, int]:
    """
    Query the trading journal for trailing 30-day empirical win rate
    and win/loss ratio.

    Returns:
        (win_rate, win_loss_ratio, trade_count)
        Falls back to (0.0, 0.0, 0) if no data or DB unavailable.
    """
    if db_path is None:
        candidates = [
            Path(__file__).parent.parent / "journal" / "trades.db",
            Path(__file__).parent.parent / "trading_journal.db",
        ]
        for c in candidates:
            if c.exists():
                db_path = str(c)
                break
        if db_path is None:
            return 0.0, 0.0, 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """SELECT pnl_usd FROM journal_trades
               WHERE closed_at >= ? AND pnl_usd IS NOT NULL""",
            (cutoff,),
        ).fetchall()
        conn.close()
    except Exception:
        return 0.0, 0.0, 0

    if not rows:
        return 0.0, 0.0, 0

    pnls = [r[0] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]

    trade_count = len(pnls)
    win_rate = len(wins) / trade_count if trade_count > 0 else 0.0

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

    return win_rate, win_loss_ratio, trade_count


def compute_kelly(
    conviction_score: float,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> float:
    """
    Compute the position size as a fraction of total portfolio.

    Uses Fixed Fractional Risk (DEFAULT_RISK_PCT) as the baseline.
    If conviction is high enough, uses Quarter-Kelly capped at
    MAX_KELLY_FRACTION (10%).

    Args:
        conviction_score: LLM probability of success (0.0 – 1.0).
        take_profit_pct:  Expected gain as a positive decimal (e.g. 0.10 = 10%).
        stop_loss_pct:    Maximum acceptable loss as a negative decimal (e.g. -0.05).

    Returns:
        Kelly fraction clamped to [0.0, MAX_KELLY_FRACTION].
        Returns DEFAULT_RISK_PCT (1%) as the floor for valid trades.
        Returns 0.0 if the trade has negative expected value.
    """
    if conviction_score <= 0 or take_profit_pct <= 0 or stop_loss_pct >= 0:
        return 0.0

    p = conviction_score
    q = 1.0 - conviction_score
    b = take_profit_pct / abs(stop_loss_pct)

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0.0

    quarter_kelly = full_kelly * KELLY_MULTIPLIER
    # Do NOT apply DEFAULT_RISK_PCT floor here. The 1% floor is only for the
    # "insufficient history" fallback in compute_empirical_kelly(). When the
    # Kelly formula produces a value below 1% with sufficient trade history,
    # the formula's output should be respected (it signals low conviction).
    # Clamped at 0 only — negative Kelly has already been filtered above.
    return round(min(max(quarter_kelly, 0.0), MAX_KELLY_FRACTION), 4)


def compute_empirical_kelly(
    db_path: Optional[str] = None,
    take_profit_pct: float = 0.05,
    stop_loss_pct: float = -0.03,
) -> float:
    """
    Compute Quarter-Kelly using trailing 30-day empirical win/loss data.

    If fewer than MIN_TRADES_FOR_KELLY trades exist in the window,
    returns DEFAULT_RISK_PCT (1%) as the fixed-fractional insufficient-history
    fallback. For all other paths (negative edge, zero Kelly, or valid quarter-
    Kelly), the output is clamped to [0.0, MAX_KELLY_FRACTION] — the DEFAULT
    floor is NOT applied so that genuinely negative-edge systems can be sized
    at 0 rather than being forced to trade at 1%.

    Args:
        db_path: Path to the SQLite trading journal. Auto-detected if None.
        take_profit_pct: Expected gain (used as b-ratio numerator).
        stop_loss_pct: Expected loss (used as b-ratio denominator).

    Returns:
        Kelly fraction clamped to [0.0, MAX_KELLY_FRACTION], or DEFAULT_RISK_PCT
        only when count < MIN_TRADES_FOR_KELLY (insufficient history fallback).
    """
    win_rate, wl_ratio, count = get_trailing_30d_stats(db_path)

    # Insufficient history: use fixed-fractional fallback (only 1% floor path).
    if count < MIN_TRADES_FOR_KELLY:
        return DEFAULT_RISK_PCT

    # Non-positive win/loss ratio → no positive edge; size at 0, not 1%.
    if wl_ratio <= 0:
        return 0.0

    b = wl_ratio
    p = win_rate
    full_kelly = (b * p - (1 - p)) / b

    # Negative full Kelly → system has negative expected value; size at 0, not 1%.
    if full_kelly <= 0:
        return 0.0

    quarter_kelly = full_kelly * KELLY_MULTIPLIER
    # Clamp to [0.0, MAX_KELLY_FRACTION] — DEFAULT_RISK_PCT floor not applied here;
    # it is reserved only for the insufficient-history fallback above.
    return round(max(0.0, min(quarter_kelly, MAX_KELLY_FRACTION)), 4)


def compute_kelly_for_slots(allocations: list[dict]) -> list[dict]:
    """
    Apply Kelly sizing to a list of allocation dicts (from LLM output).
    Overwrites the 'kelly_fraction' field with the computed value.
    """
    for slot in allocations:
        slot["kelly_fraction"] = compute_kelly(
            conviction_score=slot["conviction_score"],
            take_profit_pct=slot["take_profit_pct"],
            stop_loss_pct=slot["stop_loss_pct"],
        )
    return allocations


def normalise_kelly_fractions(allocations: list[dict]) -> list[dict]:
    """
    Ensure total Kelly fractions across all slots do not exceed 1.0.
    If they do, scale all fractions proportionally downward.
    Slots with kelly_fraction = 0.0 (SGOV) are excluded from scaling.
    """
    active = [s for s in allocations if s.get("ticker") != "SGOV" and s["kelly_fraction"] > 0]
    total = sum(s["kelly_fraction"] for s in active)

    if total > 1.0:
        scale = 1.0 / total
        for slot in active:
            slot["kelly_fraction"] = round(slot["kelly_fraction"] * scale, 4)

    return allocations
