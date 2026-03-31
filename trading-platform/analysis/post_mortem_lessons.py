"""
Deterministic Post-Mortem Lesson Generator
-------------------------------------------
Phase 2 of the RAG memory architecture.

Given a completed trade's metadata, generates a deterministic hardcoded
text string categorised by failure or success type.  These strings are
stored in execution_post_mortems and queried by Phase 3 for context-aware
LLM prompt injection and by Phase 4 for permanent rule rollup.

All public functions are pure (no I/O).  Callers persist the result via
analysis.trade_journal.log_post_mortem().

Exit-reason vocabulary
----------------------
  ratchet_stop       — GTC stop-loss order triggered by price breach
  time_exit          — 5-day 3× inverse ETF mandatory liquidation
  algo_cover         — Z-score / trailing-stop short-scanner cover
  short_scanner_exit — alias for algo_cover
  manual             — human-initiated close outside normal strategy
  allocation_sell    — executor sold because LLM dropped the ticker
  unknown            — order type / exit path could not be determined
"""

from __future__ import annotations

# ── Lesson category prefixes ───────────────────────────────────────────────
# Used as structured tags by Phase 3 (retrieval) and Phase 4 (rollup).
EXECUTION_FAILURE = "[EXECUTION FAILURE]"
THESIS_FAILURE    = "[THESIS FAILURE]"
EXECUTION_WIN     = "[EXECUTION WIN]"
THESIS_WIN        = "[THESIS WIN]"
MANUAL_EXIT       = "[MANUAL EXIT]"
AUDIT_NOTE        = "[AUDIT NOTE]"

# Human-readable context injected into every lesson
_REGIME_HINTS: dict[str, str] = {
    "Bear":     "Bear regime — inverse ETFs and shorts favoured",
    "Bull":     "Bull regime — long equities favoured",
    "Sideways": "Sideways regime — mean-reversion expected",
    "Crypto":   "Crypto regime — elevated volatility expected",
    "RISK-OFF": "RISK-OFF — capital preservation priority",
}

_ALGO_COVER_REASONS = {"algo_cover", "short_scanner_exit"}


def generate_lesson(
    ticker: str,
    regime: str,
    pnl_pct: float,
    exit_reason: str,
    time_in_trade_hours: float | None,
    asset_class: str | None = None,
) -> str:
    """
    Generate a deterministic lesson string for a completed trade.

    Parameters
    ----------
    ticker               : trading symbol (e.g. "QQQ", "SQQQ")
    regime               : market regime string (e.g. "Bear", "Bull")
    pnl_pct              : realized P&L as a percentage
    exit_reason          : see module-level vocabulary above
    time_in_trade_hours  : hours position was held (None = unavailable)
    asset_class          : equity | crypto | bear_hedge | direct_short

    Returns
    -------
    Deterministic plain-text lesson string with a structured prefix.
    """
    is_loss    = pnl_pct < 0
    hours      = time_in_trade_hours if time_in_trade_hours is not None else 0.0
    short_hold = hours < 24.0
    regime_ctx = _REGIME_HINTS.get(regime, f"Regime={regime}")
    ac         = (asset_class or "equity").lower()
    is_bear_hedge = ac == "bear_hedge"

    # ── Ratchet stop (GTC order triggered by Alpaca price breach) ──────────
    if exit_reason == "ratchet_stop":
        if is_loss and short_hold:
            return (
                f"{EXECUTION_FAILURE} Asset: {ticker}. Regime: {regime}. "
                f"Stop-loss triggered prematurely due to intraday noise after "
                f"{hours:.1f}h. P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Consider widening ATR multiplier to reduce noise sensitivity "
                f"for {ticker} in {regime} conditions."
            )
        elif is_loss:
            return (
                f"{THESIS_FAILURE} Asset: {ticker}. Regime: {regime}. "
                f"Stop-loss hit after {hours:.1f}h — price thesis invalidated "
                f"before reaching target. P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Review entry conviction and regime alignment for {ticker}."
            )
        else:
            return (
                f"{EXECUTION_WIN} Asset: {ticker}. Regime: {regime}. "
                f"Ratchet stop protected realized profit after {hours:.1f}h. "
                f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Ratchet mechanism functioned as designed for {ticker}."
            )

    # ── 5-day 3× inverse ETF mandatory time exit ───────────────────────────
    elif exit_reason == "time_exit":
        if is_loss:
            return (
                f"{THESIS_FAILURE} Asset: {ticker}. Regime: {regime}. "
                f"Directional momentum stalled — holding period exceeded 5 "
                f"trading days ({hours:.0f}h). P&L: {pnl_pct:+.2f}%. "
                f"{regime_ctx}. 3× leveraged ETF time-decay accelerated loss. "
                f"Consider earlier mean-reversion signal monitoring for {ticker}."
            )
        else:
            return (
                f"{THESIS_WIN} Asset: {ticker}. Regime: {regime}. "
                f"5-day time exit captured profit before leverage decay eroded "
                f"gains ({hours:.0f}h held). P&L: {pnl_pct:+.2f}%. "
                f"{regime_ctx}. Time-based exit rule worked as designed for "
                f"3× LETF {ticker}."
            )

    # ── Algo short cover (Z-score mean-reversion / trailing stop) ──────────
    elif exit_reason in _ALGO_COVER_REASONS:
        if is_loss and short_hold:
            return (
                f"{EXECUTION_FAILURE} Asset: {ticker}. Regime: {regime}. "
                f"Short squeezed intraday — covered at loss after {hours:.1f}h. "
                f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Check borrow cost and short-term momentum before entry on "
                f"{ticker}. Consider raising Z-score entry threshold."
            )
        elif is_loss:
            return (
                f"{THESIS_FAILURE} Asset: {ticker}. Regime: {regime}. "
                f"Short thesis failed — directional momentum did not sustain. "
                f"Covered after {hours:.1f}h at P&L {pnl_pct:+.2f}%. "
                f"{regime_ctx}. Z-score entry or regime confirmation may need "
                f"strengthening for {ticker}."
            )
        else:
            return (
                f"{THESIS_WIN} Asset: {ticker}. Regime: {regime}. "
                f"Algo short covered at profit after {hours:.1f}h. "
                f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Mean-reversion completed as expected for {ticker}."
            )

    # ── Allocation sell (LLM dropped ticker in rebalance) ──────────────────
    elif exit_reason == "allocation_sell":
        direction = "loss" if is_loss else "profit"
        return (
            f"{AUDIT_NOTE} Asset: {ticker}. Regime: {regime}. "
            f"Position liquidated by allocation rebalance at {direction} "
            f"after {hours:.1f}h. P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
            f"LLM dropped {ticker} from portfolio in updated allocation."
        )

    # ── Manual close ───────────────────────────────────────────────────────
    elif exit_reason == "manual":
        direction = "loss" if is_loss else "profit"
        return (
            f"{MANUAL_EXIT} Asset: {ticker}. Regime: {regime}. "
            f"Position manually closed at {direction} after {hours:.1f}h. "
            f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
            f"Manual intervention outside automated strategy logic."
        )

    # ── Bear hedge closed via any path ─────────────────────────────────────
    elif is_bear_hedge:
        if is_loss:
            return (
                f"{THESIS_FAILURE} Asset: {ticker}. Regime: {regime}. "
                f"Bear-hedge position closed at a loss after {hours:.1f}h. "
                f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Verify regime was genuinely Bear/RISK-OFF at entry; "
                f"false Bear signal may have triggered premature allocation."
            )
        else:
            return (
                f"{THESIS_WIN} Asset: {ticker}. Regime: {regime}. "
                f"Bear-hedge position closed at profit after {hours:.1f}h. "
                f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
                f"Inverse-ETF hedge performed as intended for {ticker}."
            )

    # ── Unknown / unclassified ─────────────────────────────────────────────
    else:
        return (
            f"{AUDIT_NOTE} Asset: {ticker}. Regime: {regime}. "
            f"Trade closed via '{exit_reason}' after {hours:.1f}h. "
            f"P&L: {pnl_pct:+.2f}%. {regime_ctx}. "
            f"Exit reason not covered by current rule set — review manually."
        )


def _load_regime_from_file() -> str:
    """
    Read the current regime from market_regime.json.
    Returns 'unknown' on any failure (file missing, parse error, etc.).
    Isolated here so it's easy to unit-test and replace in Phase 3.
    """
    try:
        from pathlib import Path
        import json
        path = Path(__file__).parent.parent / "data" / "market_regime.json"
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text())
            regime = str(data.get("regime", "") or "").strip()
            return regime or "unknown"
    except Exception:
        pass
    return "unknown"


def compute_hours_since(entry_ts_iso: str | None) -> float | None:
    """
    Compute hours elapsed since entry_ts_iso (ISO-8601 UTC string).
    Returns None if the timestamp is missing or unparseable.
    """
    if not entry_ts_iso:
        return None
    try:
        from datetime import datetime, timezone
        entry = datetime.fromisoformat(entry_ts_iso.replace("Z", "+00:00"))
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - entry
        return delta.total_seconds() / 3600.0
    except Exception:
        return None
