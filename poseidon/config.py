"""
config.py — Poseidon Bot Configuration
Bot #7: Statistical Arbitrage / Pairs Trading on Kraken
$100,000 paper capital | 15-minute cycle
"""
from __future__ import annotations
import os

BOT_ID = "poseidon"
DISPLAY_NAME = "Poseidon"
DB_ID = 7
STRATEGY_TYPE = "pairs_trading"
STRATEGY_LABEL = "Statistical Arbitrage"
PAPER_STARTING_BALANCE = 100_000.0
PAPER_FEE_PCT = 0.0026
LOOP_SLEEP_SECONDS = 900  # 15 minutes

# ── Pair definitions ──────────────────────────────────────────────────────────
# Each pair: (pair_set_id, asset_a, asset_b, description)
PAIR_SETS = [
    {"pair_set_id": 1, "asset_a": "ETH/USD", "asset_b": "BTC/USD", "description": "ETH vs BTC (foundational crypto pair)"},
    {"pair_set_id": 2, "asset_a": "ADA/USD", "asset_b": "SOL/USD", "description": "ADA vs SOL (competing L1s)"},
    {"pair_set_id": 3, "asset_a": "AVAX/USD", "asset_b": "SOL/USD", "description": "AVAX vs SOL (competing L1s)"},
    {"pair_set_id": 4, "asset_a": "DOT/USD", "asset_b": "ATOM/USD", "description": "DOT vs ATOM (interoperability)"},
    {"pair_set_id": 5, "asset_a": "LINK/USD", "asset_b": "UNI/USD", "description": "LINK vs UNI (oracle/DeFi)"},
]

# ── Entry conditions ──────────────────────────────────────────────────────────
ZSCORE_ENTRY = 2.0        # enter when |Z| > this
ZSCORE_EXIT = 0.3         # exit when |Z| < this (mean reversion complete)
ZSCORE_STOP = 3.5         # stop loss when |Z| > this (divergence accelerating)
HURST_MAX = 1.0           # Hurst not used as a hard gate for crypto pairs (crypto trends; cointegration via ADF is the quality gate)
ADF_PVALUE_MAX = 0.15     # ADF p-value must be below 0.15 (cointegration significance)
HEDGE_RATIO_STABILITY = 0.15  # hedge ratio must be within 15% of 30d avg
HEDGE_RATIO_BREAKDOWN = 0.25  # exit if hedge ratio drifts 25% from entry

# ── Position parameters ───────────────────────────────────────────────────────
POSITION_VALUE_PCT = 0.20  # 20% of equity per pair position
MAX_POSITIONS = 3          # maximum open pair positions

# ── Time-based exit ───────────────────────────────────────────────────────────
MAX_HOLD_HOURS = 72        # exit after 72 hours regardless

# ── Hedge ratio recalculation ─────────────────────────────────────────────────
HEDGE_RATIO_RECALC_HOURS = 24    # recalculate every 24 hours
OLS_LOOKBACK_DAYS = 60           # 60 days of hourly data for OLS
ZSCORE_LOOKBACK_HOURS = 60       # rolling Z-score window (60 hours = 2.5 days)
SPREAD_HISTORY_HOURS = 168       # 7 days for hedge ratio stability check

# ── Circuit breaker ───────────────────────────────────────────────────────────
CB_CONSECUTIVE_LOSSES = 5        # pause after 5 consecutive losses
CB_PAUSE_HOURS = 24              # pause duration

# ── Kraken exchange ───────────────────────────────────────────────────────────
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

# Kraken pair name mapping (ccxt format → Kraken ticker)
KRAKEN_SYMBOLS = {
    "ETH/USD": "XETHZUSD",
    "BTC/USD": "XXBTZUSD",
    "ADA/USD": "ADAUSD",
    "SOL/USD": "SOLUSD",
    "AVAX/USD": "AVAXUSD",
    "DOT/USD": "DOTUSD",
    "ATOM/USD": "ATOMUSD",
    "LINK/USD": "LINKUSD",
    "UNI/USD": "UNIUSD",
}

STATUS_FILE = "poseidon/poseidon_status.json"
LIVE_STATE_FILE = "poseidon/poseidon_live_state.json"
