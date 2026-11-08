"""
Single source of truth for where each account's run starts.

Markus, 9 Nov 2026: restart the whole fleet now instead of on 1 Jan 2027, in
software (no broker resets). Every "since start" figure, the 2027 comparison
and the fleet risk stats are measured from RUN_START, the 6 Nov 2026 US close
(the last close before the restart), using each account's equity at that close
(bot_daily_returns.equity_close for 2026-11-06, read from production 9 Nov).
"""

RUN_START = "2026-11-06"

START_EQUITY = {
    "oracle":        85_748.98,   # Atlas
    "jerome_macro":  79_986.99,   # Atlas V2
    "spy_qqq_trend": 99_178.03,   # Momentum
    "forex_ai":      99_586.58,   # Forex
}


def fleet_starting_capital() -> float:
    """Total starting equity across the fleet."""
    return float(sum(START_EQUITY.values()))


def bot_starting_capital(bot_id: str) -> float:
    """Starting equity for one account (canonical id)."""
    return float(START_EQUITY[bot_id])
