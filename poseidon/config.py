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

# ── Dynamic pair discovery ────────────────────────────────────────────────────
UNIVERSE_SIZE = 250        # top N coins by market cap to fetch from CoinGecko
MIN_PAIR_CORR = 0.85       # minimum |log-price correlation| to run ADF
ADF_PVALUE_MAX_DISCOVERY = 0.20  # relaxed from 0.15 — crypto spreads are noisier; 0.20 still confirms approximate stationarity
MAX_UNIVERSE_PAIRS = 50    # max pairs held in the tradeable universe
DISCOVERY_HOURS = 24       # full rediscovery interval
DISCOVERY_DAILY_DAYS = 30  # days of daily closes used during discovery

# Fallback pairs used if CoinGecko is unavailable at startup
# Fix 5: expanded from 5 → 10 pair sets, adding stronger idiosyncratic divergence pairs
FALLBACK_PAIR_SETS = [
    {"pair_set_id": 1,  "asset_a": "ETH/USD",  "asset_b": "BTC/USD",  "description": "ETH vs BTC (beta spread)"},
    {"pair_set_id": 2,  "asset_a": "ADA/USD",  "asset_b": "SOL/USD",  "description": "ADA vs SOL (L1 alts)"},
    {"pair_set_id": 3,  "asset_a": "AVAX/USD", "asset_b": "SOL/USD",  "description": "AVAX vs SOL (smart contract L1s)"},
    {"pair_set_id": 4,  "asset_a": "DOT/USD",  "asset_b": "ATOM/USD", "description": "DOT vs ATOM (interoperability)"},
    {"pair_set_id": 5,  "asset_a": "LINK/USD", "asset_b": "UNI/USD",  "description": "LINK vs UNI (DeFi infrastructure)"},
    {"pair_set_id": 6,  "asset_a": "BNB/USD",  "asset_b": "ETH/USD",  "description": "BNB vs ETH (exchange token vs platform)"},
    {"pair_set_id": 7,  "asset_a": "LTC/USD",  "asset_b": "BCH/USD",  "description": "LTC vs BCH (Bitcoin fork pair)"},
    {"pair_set_id": 8,  "asset_a": "LINK/USD", "asset_b": "DOT/USD",  "description": "LINK vs DOT (oracle vs interoperability)"},
    {"pair_set_id": 9,  "asset_a": "INJ/USD",  "asset_b": "AVAX/USD", "description": "INJ vs AVAX (DeFi L1s)"},
    {"pair_set_id": 10, "asset_a": "DYM/USD",  "asset_b": "ARB/USD",  "description": "DYM vs ARB (modular L2 vs Ethereum L2)"},
]

# ── Entry conditions ──────────────────────────────────────────────────────────
ZSCORE_ENTRY = 1.5        # relaxed from 2.0 — still statistically significant; produces signals more frequently in crypto's lower-amplitude regimes
ZSCORE_EXIT = 0.3         # exit when |Z| < this (mean reversion complete)
ZSCORE_STOP = 3.5         # stop loss when |Z| > this (divergence accelerating)
# Hurst is NO LONGER used as an entry gate for Poseidon. ADF already tests
# spread stationarity directly. Applying Hurst to the spread was double-filtering
# and blocking almost all valid cointegrated pairs. Hurst is still computed and
# logged for informational purposes only.
HURST_MAX = 1.0           # effectively disabled — ADF is the sole stationarity gate
ADF_PVALUE_MAX = 0.20     # relaxed from 0.15 — accepts t-stat < -1.95 (approx 20% confidence); crypto spreads are noisier than equity spreads
HEDGE_RATIO_STABILITY = 0.25  # relaxed from 0.15 — 25% drift tolerance over 30 days; volatility is higher in crypto

# ── Position parameters ───────────────────────────────────────────────────────
POSITION_VALUE_PCT = 0.15  # reduced from 0.20 — 15% per pair; max 5 positions = 75% deployed
MAX_POSITIONS = 5          # increased from 3 — allows up to 5 simultaneous pair positions across 10 pair sets

# ── Time-based exit ───────────────────────────────────────────────────────────
MAX_HOLD_HOURS = 72        # exit after 72 hours regardless

# ── Hedge ratio recalculation ─────────────────────────────────────────────────
HEDGE_RATIO_RECALC_HOURS = 24    # recalculate every 24 hours
OLS_LOOKBACK_DAYS = 60           # 60 days of hourly data for OLS
ZSCORE_LOOKBACK_HOURS = 60       # rolling Z-score window (60 hours = 2.5 days)
SPREAD_HISTORY_HOURS = 168       # 7 days for hedge ratio stability check
HEDGE_RATIO_BREAKDOWN = 0.25     # exit if hedge ratio drifts 25% from entry

# ── Circuit breaker ───────────────────────────────────────────────────────────
CB_CONSECUTIVE_LOSSES = 5        # pause after 5 consecutive losses
CB_PAUSE_HOURS = 24              # pause duration

# ── Kraken exchange ───────────────────────────────────────────────────────────
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

# Kraken pair name mapping (ccxt format → Kraken ticker)
KRAKEN_SYMBOLS = {
    "ETH/USD":  "XETHZUSD",
    "BTC/USD":  "XXBTZUSD",
    "ADA/USD":  "ADAUSD",
    "SOL/USD":  "SOLUSD",
    "AVAX/USD": "AVAXUSD",
    "DOT/USD":  "DOTUSD",
    "ATOM/USD": "ATOMUSD",
    "LINK/USD": "LINKUSD",
    "UNI/USD":  "UNIUSD",
    # Fix 5 additions
    "BNB/USD":  "BNBUSD",
    "LTC/USD":  "XLTCZUSD",
    "BCH/USD":  "BCHUSD",
    "INJ/USD":  "INJUSD",
    "DYM/USD":  "DYMUSD",
    "ARB/USD":  "ARBUSD",
}

STATUS_FILE = "poseidon/poseidon_status.json"
LIVE_STATE_FILE = "poseidon/poseidon_live_state.json"
