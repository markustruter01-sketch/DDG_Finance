"""
Kill Switch — Daily Drawdown Protection
-----------------------------------------
Monitors portfolio equity vs the opening balance at market open.
If the daily drawdown exceeds the configured threshold (default 5%),
all positions are immediately liquidated and further trading is blocked
until manually reset.

State:
    - opening_equity: captured once per trading day at first run
    - tripped:        set to True when drawdown threshold is breached

This module is designed to be called at the start of every execution
cycle by the scheduler (Phase 5).
"""

from loguru import logger

from config.settings import settings
from execution.broker import close_all_positions, get_account

_state: dict = {
    "opening_equity": None,
    "tripped": False,
    "drawdown_pct": 0.0,
}


def reset(opening_equity: float | None = None) -> None:
    """
    Reset the kill switch state for a new trading day.
    Call this at market open each morning before the first cycle.

    Args:
        opening_equity: Override the opening balance (e.g. from DB).
                        If None, it will be fetched from Alpaca on first check.
    """
    _state["tripped"] = False
    _state["drawdown_pct"] = 0.0
    _state["opening_equity"] = opening_equity
    logger.info(f"Kill switch reset | opening_equity={opening_equity}")


def is_tripped() -> bool:
    """Return True if the kill switch has been triggered today."""
    return _state["tripped"]


def check(current_equity: float | None = None) -> bool:
    """
    Check whether the daily drawdown exceeds the threshold.
    If so, liquidate all positions and trip the kill switch.

    Args:
        current_equity: Current portfolio equity. Fetched from Alpaca if None.

    Returns:
        True if kill switch was triggered, False if safe.
    """
    if _state["tripped"]:
        logger.warning("Kill switch already tripped — skipping check")
        return True

    try:
        if current_equity is None:
            acct = get_account()
            current_equity = acct["equity"]

        if _state["opening_equity"] is None:
            _state["opening_equity"] = current_equity
            logger.info(f"Kill switch | Baseline set: opening_equity=${current_equity:,.2f}")
            return False

        opening = _state["opening_equity"]
        drawdown = (opening - current_equity) / opening
        _state["drawdown_pct"] = drawdown
        threshold = settings.kill_switch_drawdown_pct

        logger.info(
            f"Kill switch | equity=${current_equity:,.2f} | "
            f"opening=${opening:,.2f} | drawdown={drawdown:.2%} | "
            f"threshold={threshold:.2%}"
        )

        if drawdown >= threshold:
            logger.critical(
                f"KILL SWITCH TRIGGERED | drawdown={drawdown:.2%} >= threshold={threshold:.2%} | "
                f"Liquidating all positions immediately!"
            )
            _state["tripped"] = True
            n = close_all_positions()
            logger.critical(f"Kill switch | {n} positions liquidated. Trading halted for the day.")
            return True

        return False

    except Exception as exc:
        logger.error(f"Kill switch check failed: {exc} — trading will continue")
        return False


def get_state() -> dict:
    """Return current kill switch state for logging/API exposure."""
    return {
        "tripped":         _state["tripped"],
        "drawdown_pct":    round(_state["drawdown_pct"] * 100, 3),
        "opening_equity":  _state["opening_equity"],
        "threshold_pct":   settings.kill_switch_drawdown_pct * 100,
    }
