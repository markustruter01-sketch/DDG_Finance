"""
config.py  —  Kraken Bot Configuration
=======================================
Single source of truth for every tunable parameter in the bot.
To change how the bot behaves, edit the values here — you should
never need to touch the trading logic in logic.py or main.py.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  THE ONE SWITCH TO RULE THEM ALL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PAPER_TRADING = True   →  Simulated $100K account, NO real money,
                            NO API keys needed.  Safe to run now.

  PAPER_TRADING = False  →  Live trading on your real Kraken account.
                            Requires KRAKEN_API_KEY + KRAKEN_SECRET_KEY
                            in Replit Secrets (padlock icon).

  To go live: set PAPER_TRADING = False below, add your keys, restart.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys

import ccxt
from dotenv import load_dotenv

# Load any .env file if present (useful for local development)
load_dotenv()


# ══════════════════════════════════════════════════════════════════════════════
# ▶▶  THE MASTER SWITCH  ◀◀
# ══════════════════════════════════════════════════════════════════════════════

PAPER_TRADING = True
# ↑ Change to False when you are ready to trade with real money on Kraken.

PAPER_STARTING_BALANCE = 100_000.0
# ↑ The fake starting balance for paper trading (USD).
#   This is only used the very first time the bot runs — after that,
#   the simulated balance is tracked in kraken-bot/paper_portfolio.json.

PAPER_FEE_PCT = 0.0026
# ↑ Simulated trading fee per trade (0.26% = Kraken's standard taker fee).
#   Deducted on both entry and exit to keep the simulation realistic.


# ══════════════════════════════════════════════════════════════════════════════
# EXCHANGE CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

if PAPER_TRADING:
    # Paper mode — no API keys needed.
    # We still create a Kraken connection for fetching real live prices,
    # but we never place any orders through it.
    print("\n" + "=" * 65)
    print("  PAPER TRADING MODE  —  Simulated $100,000 account")
    print("  Real live prices from Kraken.  Zero real money at risk.")
    print("=" * 65 + "\n")

    exchange = ccxt.kraken({"enableRateLimit": True})

else:
    # Live mode — real money, real orders, requires API keys.
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
    })


# ── Trading Universe ──────────────────────────────────────────────────────────
# The pairs the bot is allowed to trade. Kraken uses "XBT" internally
# for Bitcoin but ccxt normalises it to "BTC" for us.

SYMBOLS = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "ADA/USD",
    "AVAX/USD",
    "LINK/USD",
    "DOT/USD",
    "ATOM/USD",
    "LTC/USD",
]


# ── Signal Parameters ─────────────────────────────────────────────────────────
# These control when the bot decides to buy or sell.

RSI_PERIOD       = 14     # Number of candles used to calculate RSI.
                          # 14 is the industry-standard default.

RSI_OVERSOLD     = 40     # If RSI drops below this level, the asset is
                          # considered "oversold" — a potential buy signal.
                          # (Production value — enough symbols to find real setups)

RSI_OVERBOUGHT   = 60     # If RSI rises above this level, the asset is
                          # considered "overbought" — a potential sell/short signal.
                          # (Production value — enough symbols to find real setups)

ZSCORE_WINDOW    = 20     # How many hourly candles to use when calculating
                          # the rolling mean and standard deviation for z-score.

ZSCORE_ENTRY     = 1.0    # Enter a trade when price is 1.0 standard deviations
                          # away from the rolling mean.
                          # (Production quality — 10 symbols give enough scan coverage)

ZSCORE_EXIT      = 0.3    # Close a mean-reversion trade when price has returned
                          # to within 0.3 standard deviations of the mean
                          # (i.e. the "reversion" has happened).

OHLCV_TIMEFRAME  = "1h"   # Candle timeframe — 1-hour candles.
OHLCV_LIMIT      = 100    # How many recent candles to fetch each cycle.
                          # We need at least RSI_PERIOD + ZSCORE_WINDOW = 34.


# ── Risk Management ───────────────────────────────────────────────────────────
# These are the guardrails that protect the account from large losses.

CASH_RESERVE          = 0.20   # Always keep at least 20% of total equity as cash.
MAX_POSITION_FRACTION = 0.10   # No single position can exceed 10% of total equity.
                               # (Down from 30% — with 10 slots, 10×10% = 100% of
                               #  the 80% deployable ceiling, so cash reserve holds.)
MAX_POSITIONS         = 10     # Maximum number of positions open simultaneously.
RISK_FRACTION         = 0.01   # Risk 1% of total equity per trade.
STOP_LOSS_PCT         = 0.02   # Hard stop loss at 2% against us.
TRAIL_PCT             = 0.05   # Trailing take-profit kicks in after 5% gain.


# ── Operational Parameters ────────────────────────────────────────────────────

EQUITY_REFRESH_INTERVAL = 3600   # Refresh equity figure every 60 minutes.
LOOP_SLEEP_SECONDS      = 60     # Pause between trading cycles (1 minute).
RESTART_SLEEP_SECONDS   = 30     # Wait before restarting after an error.


# ── Circuit Breaker ───────────────────────────────────────────────────────────
# Emergency pause: if any symbol drops >10% in 5 minutes, halt all trading
# for 2 hours to wait for the dust to settle.

CB_PRICE_DROP_PCT = 0.10
CB_WINDOW_MINUTES = 5
CB_PAUSE_HOURS    = 2


# ── File Paths ────────────────────────────────────────────────────────────────
# The bot writes its current state to STATUS_FILE after every cycle.
# When in paper trading mode, the simulated portfolio is persisted to
# PAPER_PORTFOLIO_FILE so it survives bot restarts.

STATUS_FILE           = "kraken-bot/status.json"
PAPER_PORTFOLIO_FILE  = "kraken-bot/paper_portfolio.json"
CONTROL_FILE          = "kraken-bot/control.json"
