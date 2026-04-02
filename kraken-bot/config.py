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
        "strategy_label": "Conservative",
        "RSI_OVERSOLD": 40,
        "RSI_OVERBOUGHT": 60,
        "ZSCORE_ENTRY": 1.0,
        "CASH_RESERVE": 0.20,
        "MAX_POSITION_FRACTION": 0.10,
        "STOP_LOSS_PCT": 0.015,
        "ATR_STOP_MULTIPLIER": 1.5,
        "VPIN_ENTRY_BLOCK": 0.65,
    },
    "blackbeard": {
        "display_name": "Blackbeard's Fleet",
        "db_id": 2,
        "strategy_label": "Aggressive",
        "RSI_OVERSOLD": 45,
        "RSI_OVERBOUGHT": 55,
        "ZSCORE_ENTRY": 0.8,
        "CASH_RESERVE": 0.15,
        "MAX_POSITION_FRACTION": 0.12,
        "STOP_LOSS_PCT": 0.020,
        "ATR_STOP_MULTIPLIER": 2.0,
        "VPIN_ENTRY_BLOCK": 0.70,
    },
    "calypso": {
        "display_name": "Calypso's Tide",
        "db_id": 3,
        "strategy_label": "Most Aggressive",
        "RSI_OVERSOLD": 50,
        "RSI_OVERBOUGHT": 50,
        "ZSCORE_ENTRY": 0.6,
        "CASH_RESERVE": 0.10,
        "MAX_POSITION_FRACTION": 0.15,
        "STOP_LOSS_PCT": 0.025,
        "ATR_STOP_MULTIPLIER": 2.0,
        "VPIN_ENTRY_BLOCK": 0.75,
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


BLACKLIST = ["ALGO/USD"]

SYMBOLS = [
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
ZSCORE_EXIT      = 0.3

OHLCV_TIMEFRAME  = "1h"
OHLCV_LIMIT      = 100


CASH_RESERVE          = _profile.get("CASH_RESERVE", 0.20)
MAX_POSITION_FRACTION = _profile.get("MAX_POSITION_FRACTION", 0.10)
MAX_POSITIONS         = 10
RISK_FRACTION         = 0.01
STOP_LOSS_PCT         = _profile.get("STOP_LOSS_PCT", 0.015)
ATR_STOP_MULTIPLIER   = _profile.get("ATR_STOP_MULTIPLIER", 1.5)
TRAIL_PCT             = 0.05

VPIN_ENTRY_BLOCK      = _profile.get("VPIN_ENTRY_BLOCK", 0.65)

VPIN_ELEVATED_CAP     = 0.82
VOLUME_SURGE_RATIO    = 1.50

CONTRARIAN_RSI_THRESH = 25
CONTRARIAN_EQUITY_PCT = 0.03

VPIN_DECAY_AFTER_CYCLES = 4
VPIN_DECAY_RATE         = 0.10

DEEP_OVERSOLD_RSI     = 20
MICRO_LOT_EQUITY_PCT  = 0.01

BEAR_MAX_POSITIONS       = 5
BEAR_MAX_POSITION_FRACTION = 0.075

MIN_POSITION_USD      = 500.0
MIN_NET_PROFIT_PCT    = 0.008


EQUITY_REFRESH_INTERVAL = 3600
LOOP_SLEEP_SECONDS      = 60
RESTART_SLEEP_SECONDS   = 30


CB_PRICE_DROP_PCT = 0.10
CB_WINDOW_MINUTES = 5
CB_PAUSE_HOURS    = 2


STATUS_FILE           = f"kraken-bot/{BOT_ID}_status.json"
LIVE_STATE_FILE       = f"kraken-bot/{BOT_ID}_live_state.json"
PAPER_PORTFOLIO_FILE  = f"kraken-bot/{BOT_ID}_paper_portfolio.json"
CONTROL_FILE          = f"kraken-bot/{BOT_ID}_control.json"
MARKET_CACHE_FILE     = "kraken-bot/_market_cache.json"
IS_PRIMARY_FETCHER    = (BOT_ID == "davy-jones")
MARKET_CACHE_TTL      = 45
