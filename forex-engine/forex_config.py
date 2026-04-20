"""
config.py — The Navigator: Forex Swing-Trading Engine Configuration
====================================================================
Single source of truth for all tunable parameters.
"""

PAPER_TRADING = True
PAPER_STARTING_BALANCE = 100_000.0
PAPER_SPREAD_COST_PCT = 0.001

PAIRS = [
    # 5 majors (USD-based)
    "EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "CAD=X",
    # Expanded to 10 — USD/CHF + 4 liquid crosses
    "CHF=X",    # USD/CHF
    "EURGBP=X", # EUR/GBP
    "AUDJPY=X", # AUD/JPY
    "GBPJPY=X", # GBP/JPY
    "EURJPY=X", # EUR/JPY
]

PAIR_LABELS = {
    "EURUSD=X": "EUR_USD",
    "GBPUSD=X": "GBP_USD",
    "JPY=X":    "USD_JPY",
    "AUDUSD=X": "AUD_USD",
    "CHF=X":    "USD_CHF",
    "CAD=X":    "USD_CAD",
    "NZDUSD=X": "NZD_USD",
    "EURGBP=X": "EUR_GBP",
    "EURJPY=X": "EUR_JPY",
    "GBPJPY=X": "GBP_JPY",
    "AUDJPY=X": "AUD_JPY",
    "EURAUD=X": "EUR_AUD",
    "EURCHF=X": "EUR_CHF",
    "GBPCHF=X": "GBP_CHF",
    "AUDNZD=X": "AUD_NZD",
    "NZDJPY=X": "NZD_JPY",
    "CADJPY=X": "CAD_JPY",
    "EURCAD=X": "EUR_CAD",
    "GBPCAD=X": "GBP_CAD",
    "EURNZD=X": "EUR_NZD",
    "GBPNZD=X": "GBP_NZD",
    "AUDCAD=X": "AUD_CAD",
    "AUDCHF=X": "AUD_CHF",
    "NZDCHF=X": "NZD_CHF",
    "NZDCAD=X": "NZD_CAD",
    "CHFJPY=X": "CHF_JPY",
    "MXN=X":    "USD_MXN",
    "SGD=X":    "USD_SGD",
    "NOK=X":    "USD_NOK",
    "SEK=X":    "USD_SEK",
    "ZAR=X":    "USD_ZAR",
    "TRY=X":    "USD_TRY",
    "PLN=X":    "USD_PLN",
    "DKK=X":    "USD_DKK",
    "HKD=X":    "USD_HKD",
    "INR=X":    "USD_INR",
    "KRW=X":    "USD_KRW",
    "THB=X":    "USD_THB",
    "CZK=X":    "USD_CZK",
}

PAIR_DIRECTIONS = {
    "EURUSD=X": "counter_usd",
    "GBPUSD=X": "counter_usd",
    "JPY=X":    "base_usd",
    "AUDUSD=X": "counter_usd",
    "CHF=X":    "base_usd",
    "CAD=X":    "base_usd",
    "NZDUSD=X": "counter_usd",
    "EURGBP=X": "cross",
    "EURJPY=X": "cross",
    "GBPJPY=X": "cross",
    "AUDJPY=X": "cross",
    "EURAUD=X": "cross",
    "EURCHF=X": "cross",
    "GBPCHF=X": "cross",
    "AUDNZD=X": "cross",
    "NZDJPY=X": "cross",
    "CADJPY=X": "cross",
    "EURCAD=X": "cross",
    "GBPCAD=X": "cross",
    "EURNZD=X": "cross",
    "GBPNZD=X": "cross",
    "AUDCAD=X": "cross",
    "AUDCHF=X": "cross",
    "NZDCHF=X": "cross",
    "NZDCAD=X": "cross",
    "CHFJPY=X": "cross",
    "MXN=X":    "base_usd",
    "SGD=X":    "base_usd",
    "NOK=X":    "base_usd",
    "SEK=X":    "base_usd",
    "ZAR=X":    "base_usd",
    "TRY=X":    "base_usd",
    "PLN=X":    "base_usd",
    "DKK=X":    "base_usd",
    "HKD=X":    "base_usd",
    "INR=X":    "base_usd",
    "KRW=X":    "base_usd",
    "THB=X":    "base_usd",
    "CZK=X":    "base_usd",
}

JPY_PAIRS = {
    "JPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X",
    "NZDJPY=X", "CADJPY=X", "CHFJPY=X",
}

USD_BASE_PAIRS = {k for k, v in PAIR_DIRECTIONS.items() if v == "base_usd"}

PIP_SIZE = {
    "EURUSD=X": 0.0001,
    "GBPUSD=X": 0.0001,
    "JPY=X":    0.01,
    "AUDUSD=X": 0.0001,
    "CHF=X":    0.0001,
    "CAD=X":    0.0001,
    "NZDUSD=X": 0.0001,
    "EURGBP=X": 0.0001,
    "EURJPY=X": 0.01,
    "GBPJPY=X": 0.01,
    "AUDJPY=X": 0.01,
    "EURAUD=X": 0.0001,
    "EURCHF=X": 0.0001,
    "GBPCHF=X": 0.0001,
    "AUDNZD=X": 0.0001,
    "NZDJPY=X": 0.01,
    "CADJPY=X": 0.01,
    "EURCAD=X": 0.0001,
    "GBPCAD=X": 0.0001,
    "EURNZD=X": 0.0001,
    "GBPNZD=X": 0.0001,
    "AUDCAD=X": 0.0001,
    "AUDCHF=X": 0.0001,
    "NZDCHF=X": 0.0001,
    "NZDCAD=X": 0.0001,
    "CHFJPY=X": 0.01,
    "MXN=X":    0.0001,
    "SGD=X":    0.0001,
    "NOK=X":    0.0001,
    "SEK=X":    0.0001,
    "ZAR=X":    0.0001,
    "TRY=X":    0.0001,
    "PLN=X":    0.0001,
    "DKK=X":    0.0001,
    "HKD=X":    0.0001,
    "INR=X":    0.01,
    "KRW=X":    0.01,
    "THB=X":    0.01,
    "CZK=X":    0.001,
}

CROSS_QUOTE_USD = {
    "EURGBP=X":  ("GBPUSD=X", "multiply"),
    "EURJPY=X":  ("JPY=X",    "divide"),
    "GBPJPY=X":  ("JPY=X",    "divide"),
    "AUDJPY=X":  ("JPY=X",    "divide"),
    "NZDJPY=X":  ("JPY=X",    "divide"),
    "CADJPY=X":  ("JPY=X",    "divide"),
    "EURAUD=X":  ("AUDUSD=X", "multiply"),
    "EURCHF=X":  ("CHF=X",    "divide"),
    "GBPCHF=X":  ("CHF=X",    "divide"),
    "AUDCHF=X":  ("CHF=X",    "divide"),
    "NZDCHF=X":  ("CHF=X",    "divide"),
    "AUDNZD=X":  ("NZDUSD=X", "multiply"),
    "EURCAD=X":  ("CAD=X",    "divide"),
    "GBPCAD=X":  ("CAD=X",    "divide"),
    "AUDCAD=X":  ("CAD=X",    "divide"),
    "NZDCAD=X":  ("CAD=X",    "divide"),
    "EURNZD=X":  ("NZDUSD=X", "multiply"),
    "GBPNZD=X":  ("NZDUSD=X", "multiply"),
    "CHFJPY=X":  ("JPY=X",    "divide"),
}


def get_quote_to_usd(pair: str, current_price: float, latest_prices: dict):
    """Return the USD conversion factor for a pair, or None if unavailable.

    Returns None (never 1.0 as a fallback) when a required cross-pair reference
    price (e.g. JPY=X for EUR/JPY) is not cached.  Callers must treat None as
    "skip this pair this cycle" rather than treating 1.0 parity as valid.
    """
    import logging
    if PAIR_DIRECTIONS.get(pair) == "counter_usd":
        return 1.0
    if pair in USD_BASE_PAIRS:
        return 1.0 / current_price if current_price > 0 else 1.0
    info = CROSS_QUOTE_USD.get(pair)
    if info:
        ref_sym, method = info
        ref_price = latest_prices.get(ref_sym)
        if ref_price and ref_price > 0:
            return ref_price if method == "multiply" else 1.0 / ref_price
        logging.getLogger("forex_config").warning(
            f"Cross-pair {pair}: ref {ref_sym} price unavailable — skipping pair this cycle"
        )
        return None
    return 1.0


RSI_PERIOD = 14
RSI_OVERSOLD = 35    # relaxed from 30 — sideways markets rarely hit RSI extremes
RSI_OVERBOUGHT = 65  # relaxed from 70 — gives wider entry window in choppy conditions

ATR_PERIOD = 14

SL_ATR_MULT = 2.0
TP_ATR_MULT = 3.0
TRAIL_ATR_MULT = 2.0
BREAKEVEN_ATR_MULT = 1.5

MAX_RISK_PER_TRADE_PCT = 0.01
MAX_OPEN_POSITIONS = 5
MAX_POSITION_SIZE_PCT = 0.10

CYCLE_INTERVAL_HOURS = 4

VAULT_SWEEP_PCT = 0.20

CB_DRAWDOWN_THRESHOLD = 0.03
CB_COOLDOWN_HOURS = 8

BOT_ID = "navigator"
BOT_DISPLAY_NAME = "The Navigator"
BOT_DB_ID = 10
BOT_STRATEGY_LABEL = "Forex Swing (H4)"

import os as _os
_CONFIG_DIR = _os.path.dirname(_os.path.abspath(__file__))
CONTROL_FILE = _os.path.join(_CONFIG_DIR, "navigator_control.json")
LIVE_STATE_FILE = _os.path.join(_CONFIG_DIR, "navigator_live_state.json")
