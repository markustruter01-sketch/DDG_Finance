"""
Single source of truth for fleet starting capital.
Sums STARTING_CAPITAL for every active bot in the fleet.
"""

# Per-bot starting capital — update only when bots are added/removed.
# This is the ONE place to change fleet capital totals.
FLEET_BOT_STARTING_CAPITAL = {
    "oracle":          100_000,
    "bot2_spy_qqq":    100_000,
    "blackbeard":      100_000,
    "bot4_sector":     100_000,
    "navigator":       100_000,
    "poseidon":        100_000,
    "kraken_current":  100_000,
}


def fleet_starting_capital() -> float:
    """Total starting capital across all active bots."""
    return float(sum(FLEET_BOT_STARTING_CAPITAL.values()))


def bot_starting_capital(bot_id: str) -> float:
    """Starting capital for a specific bot."""
    return float(FLEET_BOT_STARTING_CAPITAL.get(bot_id, 100_000))
