"""Compatibility facade for the fleet safety controller.

Existing pipeline and route imports remain valid.  The implementation lives
in ``core.kill_switch`` and never liquidates positions.
"""
from core.kill_switch import (
    acknowledge,
    check,
    get_state,
    is_tripped,
    reset,
    manual_trip,
)


def is_pending_liquidation() -> bool:
    """Retained for compatibility; automated liquidation is retired."""
    return False


def set_pending_liquidation(value: bool = True) -> None:
    """Retained for compatibility; no deferred liquidation is scheduled."""
    return None