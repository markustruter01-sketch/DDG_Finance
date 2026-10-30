"""
Bot Registry — single source of truth for all bot identity, capital, 
and lifecycle metadata. Every other module that needs to know about 
bots reads from this file.

NEVER hardcode a bot id or display name elsewhere. Always go through 
this registry's helper functions.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal, Optional


BotStatus = Literal["active", "paused", "retired"]
AssetClass = Literal["stocks", "equity_etf", "sector_etf", "defensive_etf",
                     "bond_etf", "commodity_etf", "crypto", "forex"]
Exchange = Literal["alpaca", "kraken", "oanda", "binance_data_only"]


@dataclass(frozen=True)
class BotEntry:
    # Identity
    id: str                          # canonical id (e.g. "spy_qqq_trend")
    display_name: str                # primary UI name
    short_name: str                  # tight UI name
    icon: str                        # emoji or icon ref
    
    # Strategy
    strategy_label: str
    asset_class: AssetClass
    exchange: Exchange
    
    # Capital + accounting
    starting_capital: float
    db_id: Optional[int] = None      # kraken_portfolio.id, None for non-kraken
    
    # Lifecycle
    status: BotStatus = "active"
    display_order: int = 0
    
    # Backward compat — historical IDs that map to this bot
    legacy_aliases: tuple = field(default_factory=tuple)
    
    # Schedule
    trading_hours: str = "24_7"      # "nyse_only" | "24_7" | "forex_session" | "macro_cycle"
    cycle_minutes: int = 60

    # UI color (Tailwind color name, e.g. "purple", "amber", "cyan")
    color: str = ""
    subtitle: str = ""


# ───────────────────────────────────────────────────────────────────────
# THE REGISTRY — edit ONLY this dict to add/remove/rename bots
# ───────────────────────────────────────────────────────────────────────

BOT_REGISTRY: dict[str, BotEntry] = {
    "oracle": BotEntry(
        id="oracle",
        display_name="Atlas",
        short_name="Atlas",
        icon="🔮",
        strategy_label="Gearbox G4: SPY/QQQ + 2x when calm, T-bills below SPY's 200-day average",
        asset_class="stocks",
        exchange="alpaca",
        starting_capital=100_000,
        db_id=None,
        status="active",
        display_order=1,
        legacy_aliases=(
            "bot1_global",
            "asia_trend_strategy",
            "davy-jones",
            "davy_jones",
            "Davy Jones",
        ),
        trading_hours="nyse_only",
        cycle_minutes=15,
        color="purple",
        subtitle="Gearbox G4 (headline)",
    ),
    "spy_qqq_trend": BotEntry(
        id="spy_qqq_trend",
        display_name="Momentum",
        short_name="Momentum",
        icon="📈",
        strategy_label="G4 with DBMF instead of T-bills in the safe gear (forward test)",
        asset_class="equity_etf",
        exchange="alpaca",
        starting_capital=100_000,
        db_id=1,
        status="active",
        display_order=2,
        legacy_aliases=("bot2_spy_qqq",),
        trading_hours="nyse_only",
        cycle_minutes=60,
        color="amber",
        subtitle="G4 + DBMF (forward test)",
    ),
    "jerome_macro": BotEntry(
        id="jerome_macro",
        display_name="Bullion",
        short_name="Bullion",
        icon="🏛️",
        strategy_label="LLM Commodity Macro — Groq ETF decisions",
        asset_class="commodity_etf",
        exchange="alpaca",
        starting_capital=100_000,
        db_id=2,
        status="active",
        display_order=3,
        legacy_aliases=("bot3_reserved", "blackbeard", "Blackbeard"),
        trading_hours="macro_cycle",
        cycle_minutes=240,
        color="red",
        subtitle="Precious Metals and Crypto (research)",
    ),

    "forex_gump": BotEntry(
        id="forex_gump",
        display_name="Forex Gump",
        short_name="Forex",
        icon="💱",
        strategy_label="Gemini macro forex 2-14d holds",
        asset_class="forex",
        exchange="oanda",
        starting_capital=100_000,
        db_id=None,
        status="retired",
        display_order=4,
        legacy_aliases=("navigator", "Navigator"),
        trading_hours="forex_session",
        cycle_minutes=720,
        color="blue",
    ),
    "forex_ai": BotEntry(
        id="forex_ai",
        display_name="Forex",
        short_name="Forex",
        icon="💱",
        strategy_label="AI Currency Trading",
        asset_class="forex",
        exchange="oanda",
        starting_capital=100_000,
        db_id=None,
        status="paused",
        display_order=4,
        legacy_aliases=(),
        trading_hours="forex_session",
        cycle_minutes=60,
        color="blue",
        subtitle="AI Currency Trading (research)",
    ),
}


# Build alias → canonical lookup at module load time
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical_id, entry in BOT_REGISTRY.items():
    _ALIAS_TO_CANONICAL[canonical_id] = canonical_id
    _ALIAS_TO_CANONICAL[canonical_id.lower()] = canonical_id
    for alias in entry.legacy_aliases:
        _ALIAS_TO_CANONICAL[alias] = canonical_id
        _ALIAS_TO_CANONICAL[alias.lower()] = canonical_id


# ───────────────────────────────────────────────────────────────────────
# Helper functions — use these everywhere instead of hardcoding bot ids
# ───────────────────────────────────────────────────────────────────────

def all_bots() -> list[BotEntry]:
    """All non-retired bots (active + paused), sorted by display_order."""
    return sorted(
        [b for b in BOT_REGISTRY.values() if b.status != "retired"],
        key=lambda b: b.display_order,
    )

def active_bots() -> list[BotEntry]:
    """Only currently-active bots."""
    return [b for b in all_bots() if b.status == "active"]

def active_bot_ids() -> list[str]:
    """Canonical IDs for every non-retired bot, including paused bots."""
    return [bot.id for bot in all_bots()]

def paused_bots() -> list[BotEntry]:
    """Only paused bots."""
    return [b for b in all_bots() if b.status == "paused"]

def bot_by_id(any_id: str) -> Optional[BotEntry]:
    """Resolve a canonical id or any legacy alias to a BotEntry. Case-insensitive."""
    if not any_id:
        return None
    canonical = _ALIAS_TO_CANONICAL.get(any_id) or _ALIAS_TO_CANONICAL.get(any_id.lower())
    return BOT_REGISTRY.get(canonical) if canonical else None

def normalise_bot_id(any_id: str) -> Optional[str]:
    """Map any input id (canonical or legacy alias) to canonical id."""
    bot = bot_by_id(any_id)
    return bot.id if bot else None


def resolve_bot_id(any_id: str) -> str:
    """Resolve a known bot id or alias, failing closed for unknown values."""
    canonical = normalise_bot_id(any_id)
    if canonical is None:
        raise ValueError(f"Unknown bot identifier: {any_id!r}")
    return canonical

def display_name(any_id: str) -> str:
    """Get display name. Returns the input unchanged if unknown (safe fallback)."""
    bot = bot_by_id(any_id)
    return bot.display_name if bot else any_id


def display_label(any_id: str) -> str:
    """Return the registry display name and subtitle as one UI-friendly label."""
    bot = bot_by_id(any_id)
    if not bot:
        return any_id
    return f"{bot.display_name} · {bot.subtitle}" if bot.subtitle else bot.display_name


def fleet_starting_capital() -> float:
    """Sum of starting_capital for all non-retired bots."""
    return float(sum(b.starting_capital for b in all_bots()))

def fleet_bot_count() -> int:
    """Count of all non-retired bots."""
    return len(all_bots())

def to_dict_list() -> list[dict]:
    """Serialise all non-retired bots for API/JSON consumption."""
    return [asdict(b) for b in all_bots()]
