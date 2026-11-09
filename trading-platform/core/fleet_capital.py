"""
Single source of truth for where each account's run starts.

Markus, 10 Nov 2026: the track record starts after the 9-10 Nov stop-safety
fixes (PR #89). Every "since start" figure, the comparison and the fleet risk
stats are measured from RUN_START = the 9 Nov 2026 US session, using each
account's equity in bot_daily_returns for that date (snapshot 20:15 UTC,
read from production 10 Nov). No broker reset. It restarts once more at the
strategy lock (claude/finance-2027-plan.md, Step 3).
"""

RUN_START = "2026-11-09"

START_EQUITY = {
    "oracle":        86_919.04,   # Atlas
    "jerome_macro":  80_155.66,   # Atlas V2
    "spy_qqq_trend": 99_178.36,   # Momentum
    "forex_ai":      99_469.35,   # Forex
}


def fleet_starting_capital() -> float:
    """Total starting equity across the fleet."""
    return float(sum(START_EQUITY.values()))


def bot_starting_capital(bot_id: str) -> float:
    """Starting equity for one account (canonical id)."""
    return float(START_EQUITY[bot_id])
