"""
config.py — The Navigator: Forex Swing-Trading Engine Configuration
====================================================================
Single source of truth for all tunable parameters.
"""

PAPER_TRADING = True
PAPER_STARTING_BALANCE = 100_000.0
PAPER_SPREAD_COST_PCT = 0.001

PAIRS = ["EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CHF=X"]

PAIR_LABELS = {
    "EURUSD=X": "EUR_USD",
    "GBPUSD=X": "GBP_USD",
    "JPY=X":    "USD_JPY",
    "AUDUSD=X": "AUD_USD",
    "CHF=X":    "USD_CHF",
}

PAIR_DIRECTIONS = {
    "EURUSD=X": "counter_usd",
    "GBPUSD=X": "counter_usd",
    "JPY=X":    "base_usd",
    "AUDUSD=X": "counter_usd",
    "CHF=X":    "base_usd",
}

JPY_PAIRS = {"JPY=X"}

PIP_SIZE = {
    "EURUSD=X": 0.0001,
    "GBPUSD=X": 0.0001,
    "JPY=X":    0.01,
    "AUDUSD=X": 0.0001,
    "CHF=X":    0.01,
}

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

ATR_PERIOD = 14

SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0

MAX_RISK_PER_TRADE_PCT = 0.015
MAX_OPEN_POSITIONS = 5
MAX_POSITION_SIZE_PCT = 0.10

CYCLE_INTERVAL_HOURS = 4

VAULT_SWEEP_PCT = 0.20

BOT_ID = "navigator"
BOT_DISPLAY_NAME = "The Navigator"
BOT_DB_ID = 10
BOT_STRATEGY_LABEL = "Forex Swing (H4)"

CONTROL_FILE = "forex-engine/navigator_control.json"
LIVE_STATE_FILE = "forex-engine/navigator_live_state.json"
