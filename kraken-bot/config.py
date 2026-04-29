"""
config.py  —  Kraken Bot Configuration (Multi-Bot)
====================================================
Single source of truth for every tunable parameter in the bot.
Supports multiple bot profiles via BOT_ID environment variable.
"""

import os
import sys

import ccxt
from dotenv import load_dotenv

load_dotenv()


PAPER_TRADING = True
PAPER_STARTING_BALANCE = 100_000.0
PAPER_FEE_PCT = 0.0026

BOT_PROFILES = {
    "davy-jones": {
        "display_name": "Davy Jones' Portfolio",
        "db_id": 1,
        "strategy_type": "mean_reversion",
        "strategy_label": "Conservative",
        "BLACKLIST": ["ALGO/USD", "OP/USD", "RENDER/USD"],
        "RSI_OVERSOLD": 40,
        "RSI_OVERBOUGHT": 60,
        "ZSCORE_ENTRY": 1.0,
        "CASH_RESERVE": 0.20,
        "MAX_POSITION_FRACTION": 0.10,
        "STOP_LOSS_PCT": 0.015,
        "ATR_STOP_MULTIPLIER": 2.0,
        "VPIN_ENTRY_BLOCK": 0.82,
        "OHLCV_TIMEFRAME": "1h",
        "OHLCV_LIMIT": 100,
        "LOOP_SLEEP_SECONDS": 60,
        "LOSS_STREAK_LIMIT": 12,
        "LOSS_STREAK_COOLDOWN_HOURS": 6,
    },
    "blackbeard": {
        "display_name":      "Jerome",
        "db_id":             2,
        "strategy_type":     "llm_commodity",
        "strategy_label":    "LLM Commodity Macro",
        # ── Alpaca account (Jerome's dedicated paper account) ──────────────────
        "ALPACA_API_KEY":    os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        # ── Groq / cycle settings ──────────────────────────────────────────────
        "GROQ_CYCLE_HOURS":  [9, 21],   # UTC hours to fire Groq analysis
        "LOOP_SLEEP_SECONDS": 900,       # 15-min polling (exits checked every cycle)
        # ── Universe ──────────────────────────────────────────────────────────
        "COMMODITY_UNIVERSE": [
            "GLD", "SLV", "GDX", "GDXJ", "PPLT",
            "USO", "BNO", "UNG", "XLE", "OIH",
            "DBA", "WEAT", "CORN", "SOYB", "JO",
            "COPX", "JJC", "PDBC", "GSG", "DJP",
        ],
        "COMMODITY_THEMES": {
            "precious_metals": ["GLD", "SLV", "GDX", "GDXJ", "PPLT"],
            "energy":          ["USO", "BNO", "UNG", "XLE", "OIH"],
            "agriculture":     ["DBA", "WEAT", "CORN", "SOYB", "JO"],
            "industrial":      ["COPX", "JJC", "PDBC", "GSG", "DJP"],
        },
        # ── Risk management ───────────────────────────────────────────────────
        "MAX_POSITIONS":     3,
        "STOP_LOSS_PCT":     0.04,     # 4% hard stop per position
        "TAKE_PROFIT_PCT":   0.08,     # 8% default take-profit
        "MAX_HOLD_DAYS":     21,       # time-stop
        "MIN_CONVICTION":    0.65,     # Groq conviction threshold to enter
    },
    "calypso": {
        "display_name": "Calypso's Tide",
        "db_id": 3,
        "strategy_type": "mean_reversion_conservative",
        "strategy_label": "mean_reversion_conservative",
        "BLACKLIST": [],
        "RSI_OVERSOLD": 35,
        "RSI_OVERBOUGHT": 65,
        "ZSCORE_ENTRY": 2.0,
        "CASH_RESERVE": 0.20,
        "MAX_POSITION_FRACTION": 0.05,
        "MAX_POSITIONS": 6,
        "STOP_LOSS_PCT": 0.020,
        "ATR_STOP_MULTIPLIER": 2.0,
        "VPIN_ENTRY_BLOCK": 0.75,
        "OHLCV_TIMEFRAME": "1h",
        "OHLCV_LIMIT": 100,
        "LOOP_SLEEP_SECONDS": 60,
        "LOSS_STREAK_LIMIT": 7,
        "LOSS_STREAK_COOLDOWN_HOURS": 10,
        "SWING_TP_ATR_MULT": 3.0,
        "SWING_SL_ATR_MULT": 2.0,
        "SWING_TRAIL_TRIGGER_ATR": 1.5,
        "SWING_TRAIL_ATR_MULT": 1.5,
        "SWING_MAX_HOLD_HOURS": 48,
        "CALYPSO_TIER1_MAX": 0.10,
        "CALYPSO_TIER2_MAX": 0.07,
        "CALYPSO_TIER3_MAX": 0.05,
        "TREND_EMA_FAST": 50,
        "TREND_EMA_SLOW": 200,
        "FLOW_VPIN_MAX": 0.75,
        "FLOW_VOLUME_MULT": 1.5,
        "FLOW_RSI_MIN": 40,
        "FLOW_RSI_MAX": 60,
    },
    "apex-predator": {
        "display_name": "Apex Predator",
        "db_id": 4,
        "strategy_type": "momentum_scalper",
        "strategy_label": "Dual-TF Momentum Scalper",
        "BLACKLIST": [],
        # Top-15 Kraken pairs by liquidity
        "SYMBOLS": [
            "BTC/USD", "ETH/USD", "XRP/USD", "SOL/USD", "DOGE/USD",
            "ADA/USD", "AVAX/USD", "LINK/USD", "DOT/USD", "LTC/USD",
            "ATOM/USD", "NEAR/USD", "AAVE/USD", "BCH/USD", "UNI/USD",
        ],
        # Risk management
        "RISK_FRACTION": 0.015,          # 1.5% risk per trade
        "ATR_STOP_MULTIPLIER": 1.5,      # 1.5× ATR stop loss
        "APEX_TP_ATR_MULT": 3.0,         # 3× ATR take-profit
        "MAX_POSITIONS": 5,
        "MAX_POSITION_FRACTION": 0.15,
        "CASH_RESERVE": 0.20,
        # Entry signal thresholds
        "RSI_OVERSOLD": 35,              # 1h RSI crossing up from below 35 = bullish (was 45 — too tight)
        "RSI_OVERBOUGHT": 65,            # 1h RSI crossing down from above 65 = bearish (was 55 — too tight)
        "APEX_EMA_FAST": 20,             # 4h EMA for trend filter
        "APEX_EMA_SLOW": 50,
        "APEX_VOLUME_MULT": 0.75,        # volume must be 0.75× 20-bar average (lowered from 1.5× — weekend crypto volume is typically 0.1–0.8×)
        "APEX_VPIN_BLOCK": 0.80,         # block if VPIN > 0.80 (toxic flow)
        # Timeframes
        "OHLCV_TIMEFRAME": "1h",         # primary candles for RSI
        "APEX_TREND_TIMEFRAME": "4h",    # secondary candles for EMA trend
        "OHLCV_LIMIT": 100,
        # Loop
        "LOOP_SLEEP_SECONDS": 3600,      # hourly cycle
        # Loss circuit breaker
        "LOSS_STREAK_LIMIT": 6,
        "LOSS_STREAK_COOLDOWN_HOURS": 12,
        # Stop params (unused by scalper path but must exist for shared reads)
        "STOP_LOSS_PCT": 0.015,
        "VPIN_ENTRY_BLOCK": 0.80,
    },

    # ── Phase 2: New Alpaca-based bots (built paused, staggered activation) ───
    #
    # All 4 share the ALPACA_BB paper account with Jerome.
    # All start with BOT_PAUSED=True — flip to False on the activation schedule:
    #   Week 2: bot2_spy_qqq   (db_id=1, replaces Davy Jones)
    #   Week 3: bot4_sector    (db_id=3, replaces Calypso)
    #   Week 4: bot7_macro_bond (db_id=7, replaces FOMO Fred/Poseidon)
    #   Week 5: bot5_defensive  (db_id=4, replaces Apex Predator)
    #
    # ACTIVATION CHECKLIST (run before flipping BOT_PAUSED=False):
    #   1. UPDATE kraken_heartbeat SET bot_id=<new>, bot_display_name=<new>
    #      WHERE id=<db_id>;
    #   2. Set BOT_PAUSED=False in this file.
    #   3. Restart the relevant workflow.

    "bot2_spy_qqq": {
        "display_name":      "SPY/QQQ Trend",
        "db_id":             1,              # replaces Davy Jones (id=1)
        "strategy_type":     "etf_trend",
        "strategy_label":    "SPY/QQQ Long-Only Trend",
        "ALPACA_API_KEY":    os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "STARTING_CAPITAL":  100_000,
        "LOOP_SLEEP_SECONDS": 3600,          # hourly check (exits + 4:30 PM entry)
        "BOT_PAUSED":        True,           # Week 2 activation
    },
    "bot4_sector": {
        "display_name":      "Sector Rotation",
        "db_id":             3,              # replaces Calypso (id=3)
        "strategy_type":     "etf_rotation",
        "strategy_label":    "SPDR Sector Momentum",
        "ALPACA_API_KEY":    os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "STARTING_CAPITAL":  100_000,
        "LOOP_SLEEP_SECONDS": 3600,          # hourly check; rebalance only Mondays
        "BOT_PAUSED":        True,           # Week 3 activation
    },
    "bot5_defensive": {
        "display_name":      "Defensive Guardian",
        "db_id":             4,              # replaces Apex Predator (id=4)
        "strategy_type":     "etf_defensive",
        "strategy_label":    "Risk-Off Defensive Allocation",
        "ALPACA_API_KEY":    os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "STARTING_CAPITAL":  100_000,
        "LOOP_SLEEP_SECONDS": 3600,          # hourly check; regime detection each cycle
        "BOT_PAUSED":        True,           # Week 5 activation
    },
    "bot7_macro_bond": {
        "display_name":      "Macro Bond Trader",
        "db_id":             7,              # replaces FOMO Fred/Poseidon (id=7)
        "strategy_type":     "llm_bonds",
        "strategy_label":    "Groq Fixed Income Macro",
        "ALPACA_API_KEY":    os.environ.get("ALPACA_BB_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_BB_SECRET_KEY", ""),
        "ALPACA_BASE_URL":   "https://paper-api.alpaca.markets",
        "STARTING_CAPITAL":  100_000,
        "BOND_UNIVERSE":     ["TLT", "IEF", "SHY", "TIP", "HYG", "LQD", "EMB"],
        "CYCLE_HOURS_UTC":   [13, 22],       # 9AM ET + 6PM ET
        "LOOP_SLEEP_SECONDS": 900,           # 15-min polling (exits every cycle)
        "MAX_POSITIONS":     3,
        "STOP_LOSS_PCT":     0.04,
        "TAKE_PROFIT_PCT":   0.08,
        "MAX_HOLD_DAYS":     60,
        "MIN_HOLD_DAYS":     14,
        "MIN_CONVICTION":    0.65,
        "POSITION_SIZE_MIN": 0.10,
        "POSITION_SIZE_MAX": 0.30,
        "BOT_PAUSED":        True,           # Week 4 activation
    },
}

BOT_ID = os.environ.get("BOT_ID", "davy-jones")
if BOT_ID not in BOT_PROFILES:
    print(f"ERROR: Unknown BOT_ID '{BOT_ID}'. Valid: {list(BOT_PROFILES.keys())}")
    sys.exit(1)

_profile = BOT_PROFILES[BOT_ID]
BOT_DISPLAY_NAME = _profile["display_name"]
BOT_DB_ID = _profile["db_id"]
BOT_STRATEGY_LABEL = _profile["strategy_label"]
BOT_STRATEGY_TYPE = _profile.get("strategy_type", "mean_reversion")
IS_SCALP_BOT          = BOT_STRATEGY_TYPE in ("momentum_wave", "liquidity_scout")
IS_SWING_BOT          = BOT_STRATEGY_TYPE in ("momentum_breakout", "trend_following", "flow_sentiment")
IS_MOMENTUM_SCALPER   = BOT_STRATEGY_TYPE == "momentum_scalper"

if PAPER_TRADING:
    print("\n" + "=" * 65)
    print(f"  PAPER TRADING MODE  —  {BOT_DISPLAY_NAME}")
    print(f"  Bot ID: {BOT_ID} (DB id={BOT_DB_ID}) | Strategy: {BOT_STRATEGY_LABEL}")
    print(f"  Simulated ${PAPER_STARTING_BALANCE:,.0f} account")
    print("=" * 65 + "\n")

    exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 10000})

else:
    KRAKEN_API_KEY    = os.environ.get("KRAKEN_API_KEY", "")
    KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

    if not KRAKEN_API_KEY or not KRAKEN_SECRET_KEY:
        print("\n" + "=" * 65)
        print(" STARTUP ERROR — Missing Kraken API credentials")
        print("=" * 65)
        print(" Live trading requires API keys.")
        print(" Add these in Replit (padlock icon → Secrets):")
        print("   KRAKEN_API_KEY    — Your Kraken Pro API key ID")
        print("   KRAKEN_SECRET_KEY — Your Kraken Pro secret key")
        print(" OR set PAPER_TRADING = True in config.py to run")
        print(" safely with a simulated $100K account first.")
        print("=" * 65 + "\n")
        sys.exit(1)

    exchange = ccxt.kraken({
        "apiKey":          KRAKEN_API_KEY,
        "secret":          KRAKEN_SECRET_KEY,
        "enableRateLimit": True,
        "timeout":         10000,
    })


BLACKLIST = _profile.get("BLACKLIST", ["ALGO/USD", "OP/USD", "RENDER/USD"])

PAIR_SIZING_PENALIZED = {
    "ETH/USD":    0.50,
    "SOL/USD":    0.50,
    "W/USD":      0.50,
    "VET/USD":    0.50,
    "STX/USD":    0.50,
    "SUI/USD":    0.50,
}
PAIR_SIZING_PENALIZED_GRADUATE_WIN_RATE = 0.35
PAIR_SIZING_PENALIZED_GRADUATE_MIN_TRADES = 20

PAIR_SIZING_BOOSTED = {
    "TIA/USD":  1.25,
    "IMX/USD":  1.25,
    "SEI/USD":  1.25,
    "TAO/USD":  1.25,
    "ARB/USD":  1.25,
    "DYM/USD":  1.25,
}

SYMBOLS = _profile.get("SYMBOLS") or [
    "BTC/USD",
    "ETH/USD",
    "XRP/USD",
    "SOL/USD",
    "BNB/USD",
    "DOGE/USD",
    "ADA/USD",
    "TRX/USD",
    "AVAX/USD",
    "SHIB/USD",
    "LINK/USD",
    "TON/USD",
    "DOT/USD",
    "UNI/USD",
    "BCH/USD",
    "NEAR/USD",
    "LTC/USD",
    "ATOM/USD",
    "APT/USD",
    "ICP/USD",
    "FIL/USD",
    "ARB/USD",
    "OP/USD",
    "SUI/USD",
    "INJ/USD",
    "RENDER/USD",
    "STX/USD",
    "TAO/USD",
    "PEPE/USD",
    "POL/USD",
    "IMX/USD",
    "GRT/USD",
    "VET/USD",
    "HBAR/USD",
    "RUNE/USD",
    "SNX/USD",
    "ENS/USD",
    "WLD/USD",
    "JUP/USD",
    "TIA/USD",
    "ONDO/USD",
    "SEI/USD",
    "PYTH/USD",
    "W/USD",
    "DYM/USD",
    "STRK/USD",
    "ENA/USD",
    "AAVE/USD",
    "CRV/USD",
]


RSI_PERIOD       = 14
RSI_OVERSOLD     = _profile.get("RSI_OVERSOLD", 40)
RSI_OVERBOUGHT   = _profile.get("RSI_OVERBOUGHT", 60)

ZSCORE_WINDOW    = 20
ZSCORE_ENTRY     = _profile.get("ZSCORE_ENTRY", 1.0)
ZSCORE_EXIT      = 0.45

OHLCV_TIMEFRAME  = _profile.get("OHLCV_TIMEFRAME", "1h")
OHLCV_LIMIT      = _profile.get("OHLCV_LIMIT", 100)


CASH_RESERVE          = _profile.get("CASH_RESERVE", 0.20)
MAX_POSITION_FRACTION = _profile.get("MAX_POSITION_FRACTION", 0.10)
MAX_POSITIONS         = _profile.get("MAX_POSITIONS", 8)
RISK_FRACTION         = _profile.get("RISK_FRACTION", 0.01)
STOP_LOSS_PCT         = _profile.get("STOP_LOSS_PCT", 0.015)
ATR_STOP_MULTIPLIER   = _profile.get("ATR_STOP_MULTIPLIER", 1.5)
TRAIL_PCT             = 0.039

VPIN_ENTRY_BLOCK      = _profile.get("VPIN_ENTRY_BLOCK", 0.65)

try:
    from vpin_adaptive import get_dynamic_threshold as _get_dyn_vpin
    VPIN_ENTRY_BLOCK_DYNAMIC = True
except ImportError:
    VPIN_ENTRY_BLOCK_DYNAMIC = False

VPIN_ELEVATED_CAP     = 0.90
VOLUME_SURGE_RATIO    = 1.50

CONTRARIAN_RSI_THRESH = 28
CONTRARIAN_EQUITY_PCT = 0.015

VPIN_DECAY_AFTER_CYCLES = 4
VPIN_DECAY_RATE         = 0.10

DEEP_OVERSOLD_RSI     = 20
MICRO_LOT_EQUITY_PCT  = 0.01

BEAR_MAX_POSITIONS       = 5
BEAR_MAX_POSITION_FRACTION = 0.075

REGIME_COOLDOWN_CYCLES  = 3
REGIME_CONFIDENCE_GATE  = 0.67

MIN_POSITION_USD      = 500.0
MIN_NET_PROFIT_PCT    = 0.0104

STALE_EXIT_HOURS      = 24
STALE_DEAD_ZONE_PCT   = 0.005


EQUITY_REFRESH_INTERVAL = 3600
LOOP_SLEEP_SECONDS      = _profile.get("LOOP_SLEEP_SECONDS", 60)
RESTART_SLEEP_SECONDS   = 30

SCALP_TP_PCT             = _profile.get("SCALP_TP_PCT", 0.010)
SCALP_SL_PCT             = _profile.get("SCALP_SL_PCT", 0.005)
SCALP_STAGNANCY_MINUTES  = _profile.get("SCALP_STAGNANCY_MINUTES", 15)
SCALP_STAGNANCY_DEADZONE = _profile.get("SCALP_STAGNANCY_DEADZONE", 0.002)
LATENCY_TAX_BPS          = _profile.get("LATENCY_TAX_BPS", 0)
LATENCY_TAX_PCT          = LATENCY_TAX_BPS / 10000.0
SCALP_FEE_RATE           = _profile.get("SCALP_FEE_RATE", PAPER_FEE_PCT)

EMA_FAST         = _profile.get("EMA_FAST", 8)
EMA_MID          = _profile.get("EMA_MID", 13)
EMA_SLOW         = _profile.get("EMA_SLOW", 21)
RVOL_THRESHOLD   = _profile.get("RVOL_THRESHOLD", 1.5)
RVOL_PERIOD      = _profile.get("RVOL_PERIOD", 20)

KELTNER_EMA_PERIOD  = _profile.get("KELTNER_EMA_PERIOD", 20)
KELTNER_ATR_MULT    = _profile.get("KELTNER_ATR_MULT", 1.5)
VWAP_PROXIMITY_PCT  = _profile.get("VWAP_PROXIMITY_PCT", 0.002)

MIN_CONVICTION            = _profile.get("MIN_CONVICTION", 0.50)
STAGNANCY_COOLDOWN_MINUTES = _profile.get("STAGNANCY_COOLDOWN_MINUTES", 0)
MAX_NEW_ENTRIES_PER_CYCLE  = _profile.get("MAX_NEW_ENTRIES_PER_CYCLE", 99)


CB_PRICE_DROP_PCT = 0.10
CB_WINDOW_MINUTES = 5
CB_PAUSE_HOURS    = 2

LOSS_STREAK_LIMIT          = _profile.get("LOSS_STREAK_LIMIT", 10)
LOSS_STREAK_COOLDOWN_HOURS = _profile.get("LOSS_STREAK_COOLDOWN_HOURS", 8)

SWING_TP_ATR_MULT         = _profile.get("SWING_TP_ATR_MULT", 3.0)
SWING_SL_ATR_MULT         = _profile.get("SWING_SL_ATR_MULT", 1.5)
SWING_TRAIL_TRIGGER_ATR   = _profile.get("SWING_TRAIL_TRIGGER_ATR", 1.0)
SWING_TRAIL_ATR_MULT      = _profile.get("SWING_TRAIL_ATR_MULT", 1.5)
SWING_MIN_HOLD_HOURS      = _profile.get("SWING_MIN_HOLD_HOURS", 4)
SWING_MAX_HOLD_HOURS      = _profile.get("SWING_MAX_HOLD_HOURS", 72)

MOMENTUM_LOOKBACK_CANDLES = _profile.get("MOMENTUM_LOOKBACK_CANDLES", 4)
MOMENTUM_ATR_THRESHOLD    = _profile.get("MOMENTUM_ATR_THRESHOLD", 1.5)
VOLUME_MA_PERIOD          = _profile.get("VOLUME_MA_PERIOD", 20)

TREND_EMA_FAST            = _profile.get("TREND_EMA_FAST", 30)
TREND_EMA_SLOW            = _profile.get("TREND_EMA_SLOW", 75)
TREND_PULLBACK_ATR_MULT   = _profile.get("TREND_PULLBACK_ATR_MULT", 0.5)

FLOW_IMBALANCE_LONG_THRESHOLD  = _profile.get("FLOW_IMBALANCE_LONG_THRESHOLD", 0.65)
FLOW_IMBALANCE_SHORT_THRESHOLD = _profile.get("FLOW_IMBALANCE_SHORT_THRESHOLD", 0.35)
FLOW_VPIN_MAX                  = _profile.get("FLOW_VPIN_MAX", 0.75)
FLOW_VPIN_SPIKE_BLOCK          = _profile.get("FLOW_VPIN_SPIKE_BLOCK", 0.85)
FLOW_RSI_MIN                   = _profile.get("FLOW_RSI_MIN", 40)
FLOW_RSI_MAX                   = _profile.get("FLOW_RSI_MAX", 60)
FLOW_VOLUME_MA_PERIOD          = _profile.get("FLOW_VOLUME_MA_PERIOD", 20)
FLOW_VOLUME_MULT               = _profile.get("FLOW_VOLUME_MULT", 1.5)

SYMBOL_WINRATE_LOOKBACK           = _profile.get("SYMBOL_WINRATE_LOOKBACK", 15)
SYMBOL_WINRATE_PENALTY_THRESHOLD  = _profile.get("SYMBOL_WINRATE_PENALTY_THRESHOLD", 0.35)
SYMBOL_WINRATE_RECOVERY_THRESHOLD = _profile.get("SYMBOL_WINRATE_RECOVERY_THRESHOLD", 0.40)
SYMBOL_WINRATE_PENALTY_FACTOR     = _profile.get("SYMBOL_WINRATE_PENALTY_FACTOR", 0.70)


CALYPSO_TIER1_MAX = _profile.get("CALYPSO_TIER1_MAX", 0.05)
CALYPSO_TIER2_MAX = _profile.get("CALYPSO_TIER2_MAX", 0.05)
CALYPSO_TIER3_MAX = _profile.get("CALYPSO_TIER3_MAX", 0.05)

APEX_TP_ATR_MULT      = _profile.get("APEX_TP_ATR_MULT", 3.0)
APEX_EMA_FAST         = _profile.get("APEX_EMA_FAST", 20)
APEX_EMA_SLOW         = _profile.get("APEX_EMA_SLOW", 50)
APEX_VOLUME_MULT      = _profile.get("APEX_VOLUME_MULT", 0.75)
APEX_VPIN_BLOCK       = _profile.get("APEX_VPIN_BLOCK", 0.80)
APEX_TREND_TIMEFRAME  = _profile.get("APEX_TREND_TIMEFRAME", "4h")


STATUS_FILE           = f"kraken-bot/{BOT_ID}_status.json"
LIVE_STATE_FILE       = f"kraken-bot/{BOT_ID}_live_state.json"
PAPER_PORTFOLIO_FILE  = f"kraken-bot/{BOT_ID}_paper_portfolio.json"
CONTROL_FILE          = f"kraken-bot/{BOT_ID}_control.json"
MARKET_CACHE_FILE     = "kraken-bot/_market_cache.json"
IS_PRIMARY_FETCHER    = (BOT_ID == "davy-jones")
MARKET_CACHE_TTL      = 45
