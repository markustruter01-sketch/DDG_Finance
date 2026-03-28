"""
config.py  —  Kraken Bot Configuration
=======================================
Single source of truth for every tunable parameter in the bot.
To change how the bot behaves, edit the values here — you should
never need to touch the trading logic in logic.py or main.py.

IMPORTANT — Before running the bot, add these two secrets
in Replit (click the padlock icon → Secrets):
  KRAKEN_API_KEY    — Your Kraken Pro API key
  KRAKEN_SECRET_KEY — Your Kraken Pro API secret key
"""

import os
import sys

import ccxt
from dotenv import load_dotenv

# Load any .env file if present (useful for local development)
load_dotenv()


# ── API Credentials ───────────────────────────────────────────────────────────
# We read the keys from environment variables, never hard-code them.

KRAKEN_API_KEY    = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

# Validate immediately — exit with a clear message rather than failing silently
if not KRAKEN_API_KEY or not KRAKEN_SECRET_KEY:
    print("\n" + "=" * 65)
    print(" STARTUP ERROR — Missing Kraken API credentials")
    print("=" * 65)
    print(" The bot cannot run without API keys.")
    print(" Please add the following secrets in Replit (padlock icon):")
    print("   KRAKEN_API_KEY    — Your Kraken Pro API key ID")
    print("   KRAKEN_SECRET_KEY — Your Kraken Pro secret key")
    print("=" * 65 + "\n")
    sys.exit(1)


# ── Exchange Connection ───────────────────────────────────────────────────────
# We create the ccxt Kraken object here so every module can import it.
# enableRateLimit=True means ccxt automatically sleeps between requests
# to stay within Kraken's API rate limits.

exchange = ccxt.kraken({
    "apiKey":          KRAKEN_API_KEY,
    "secret":          KRAKEN_SECRET_KEY,
    "enableRateLimit": True,
})


# ── Trading Universe ─────────────────────────────────────────────────────────
# The pairs the bot is allowed to trade. Kraken uses "XBT" internally
# for Bitcoin but ccxt normalises it to "BTC" for us.

SYMBOLS = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
]


# ── Signal Parameters ─────────────────────────────────────────────────────────
# These control when the bot decides to buy or sell.

RSI_PERIOD       = 14     # Number of candles used to calculate RSI.
                          # 14 is the industry-standard default.

RSI_OVERSOLD     = 35     # If RSI drops below this level, the asset is
                          # considered "oversold" — a potential buy signal.

RSI_OVERBOUGHT   = 65     # If RSI rises above this level, the asset is
                          # considered "overbought" — a potential sell/short signal.

ZSCORE_WINDOW    = 20     # How many hourly candles to use when calculating
                          # the rolling mean and standard deviation for z-score.

ZSCORE_ENTRY     = 1.8    # Enter a trade when price is 1.8 standard deviations
                          # away from the rolling mean.

ZSCORE_EXIT      = 0.3    # Close a mean-reversion trade when price has returned
                          # to within 0.3 standard deviations of the mean
                          # (i.e. the "reversion" has happened).

OHLCV_TIMEFRAME  = "1h"   # Candle timeframe — 1-hour candles.
OHLCV_LIMIT      = 100    # How many recent candles to fetch each cycle.
                          # We need at least RSI_PERIOD + ZSCORE_WINDOW = 34.


# ── Risk Management ───────────────────────────────────────────────────────────
# These are the guardrails that protect the account from large losses.

CASH_RESERVE         = 0.20   # Always keep at least 20% of total equity as cash.
                              # This acts as a buffer for fees, drawdowns, and
                              # unexpected volatility. We never deploy this.

MAX_POSITION_FRACTION = 0.30  # No single position can exceed 30% of total equity.
                              # This prevents over-concentration in one asset.

MAX_POSITIONS        = 3      # Maximum number of positions open simultaneously.
                              # With 3 positions at ≤30% each, max deployment ≈ 70-90%.

RISK_FRACTION        = 0.01   # We risk 1% of total account equity per trade.
                              # Combined with the 2% stop loss, this determines
                              # the position size (see logic.py for the formula).

STOP_LOSS_PCT        = 0.02   # Hard stop loss: exit immediately if the trade
                              # moves 2% against us. This is non-negotiable.

TRAIL_PCT            = 0.05   # Trailing take-profit: once a trade is 5% in profit,
                              # we lock in gains by trailing the stop behind the
                              # best price seen so far.


# ── Operational Parameters ────────────────────────────────────────────────────

EQUITY_REFRESH_INTERVAL = 3600   # Re-fetch the total account balance every 60 minutes.
                                 # Crypto moves fast — we need fresh equity numbers
                                 # to keep position sizing accurate.

LOOP_SLEEP_SECONDS  = 60         # How long to pause between each trading cycle (1 min).

RESTART_SLEEP_SECONDS = 30       # If an unexpected error occurs, wait 30 seconds
                                 # before restarting the loop. Prevents a crash loop
                                 # from hammering the API.


# ── Circuit Breaker ───────────────────────────────────────────────────────────
# A "circuit breaker" is an emergency pause mechanism. If the market
# crashes suddenly (a "flash crash"), technical indicators like RSI can
# give dangerously false signals. This rule says: if the price of any
# watched symbol drops more than 10% in 5 minutes, stop all trading
# for 2 hours and wait for the dust to settle.

CB_PRICE_DROP_PCT    = 0.10    # Trigger the circuit breaker if price falls >10%...
CB_WINDOW_MINUTES    = 5       # ...within any 5-minute rolling window.
CB_PAUSE_HOURS       = 2       # Once triggered, pause all trading for 2 hours.


# ── Status File ───────────────────────────────────────────────────────────────
# The bot writes its current state to this file after every cycle.
# The FastAPI server reads this file to serve the dashboard.

STATUS_FILE = "kraken-bot/status.json"
