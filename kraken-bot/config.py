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

    exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 10000})

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
        "timeout":         10000,
    })


# ── Trading Universe ──────────────────────────────────────────────────────────
# The pairs the bot is allowed to trade. Kraken uses "XBT" internally
# for Bitcoin but ccxt normalises it to "BTC" for us.

SYMBOLS = [
    # ── Tier 1: Mega-cap (1–10) ───────────────────────────────────────────
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
    # ── Tier 2: Large-cap (11–25) ─────────────────────────────────────────
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
    # ── Tier 3: Mid-cap (26–50) ───────────────────────────────────────────
    "RENDER/USD",
    "STX/USD",
    "TAO/USD",
    "PEPE/USD",
    "POL/USD",
    "IMX/USD",
    "GRT/USD",
    "ALGO/USD",
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
MAX_POSITION_FRACTION = 0.10   # No single position can exceed 10% of total equity (normal regime).
                               # In Bear/RISK-OFF regime this is overridden to 7.5%.
MAX_POSITIONS         = 10     # Maximum number of positions (normal regime).
                               # In Bear/RISK-OFF regime this is overridden to 5.
RISK_FRACTION         = 0.01   # Risk 1% of total equity per trade.
STOP_LOSS_PCT         = 0.015  # Hard stop loss at 1.5% against us (tightened from 2%).
TRAIL_PCT             = 0.05   # Trailing take-profit kicks in after 5% gain.

# ── VPIN Defensive Threshold ──────────────────────────────────────────────────
# When VPIN exceeds this level, all new entries are blocked (toxic/institutional
# flow detected). Lowered from 0.70 to 0.65 for a more selective/defensive posture.
VPIN_ENTRY_BLOCK      = 0.65

# ── Dynamic VPIN Cap (Stage 3) ──────────────────────────────────────────────
# When 24h volume is 50%+ above the trailing mean, raise the VPIN entry cap
# to allow entries during high-volume-but-healthy markets.
VPIN_ELEVATED_CAP     = 0.82    # Relaxed cap when volume surge detected
VOLUME_SURGE_RATIO    = 1.50    # 24h vol must be >= 1.5x the 30-candle mean

# ── Contrarian Scout (Stage 3) ──────────────────────────────────────────────
# In Bear/RISK-OFF regime, if RSI is extremely low, allow a small contrarian
# "Tier 1" entry instead of blocking all longs.
CONTRARIAN_RSI_THRESH = 25      # RSI must be below this
CONTRARIAN_EQUITY_PCT = 0.03    # 3% of equity for the scout position

# ── VPIN Decay & Convergence (Stage 3.5) ────────────────────────────────────
# If VPIN stays above threshold for N consecutive cycles while price volatility
# is stabilizing (ATR is falling), decay the effective VPIN by 10% per cycle
# so the bot doesn't stay permanently locked out.
VPIN_DECAY_AFTER_CYCLES = 4     # Start decaying after this many consecutive blocks
VPIN_DECAY_RATE         = 0.10  # 10% importance reduction per cycle

# ── Deep Oversold RSI Bypass (Stage 3.5) ────────────────────────────────────
# If RSI drops below 20, the VPIN filter is bypassed entirely for a micro-lot
# (1% equity) to ensure we never miss the absolute bottom of a move.
DEEP_OVERSOLD_RSI     = 20      # RSI threshold for bypass
MICRO_LOT_EQUITY_PCT  = 0.01   # 1% of equity for the micro-lot

# ── Bear-Regime Position-Sizing Overrides ────────────────────────────────────
# Applied when the Alpaca bot's market_regime.json signals BEAR or RISK-OFF.
BEAR_MAX_POSITIONS       = 5     # Half the normal slot count
BEAR_MAX_POSITION_FRACTION = 0.075  # 7.5% of equity per position

MIN_NET_PROFIT_PCT    = 0.008  # Minimum required gross P&L before a mean-reversion
                               # exit is allowed.  Kraken charges 0.26% per side
                               # (0.52% round-trip).  0.8% gives a 0.28% buffer above
                               # break-even so every closed trade has a real net gain.
                               # The trailing stop and hard stop are unaffected by this
                               # guard — only the z-score mean-reversion exit checks it.


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
# Live trading state (positions, signals, microstructure, thinking_text) is written
# to LIVE_STATE_FILE separately so that STATUS_FILE stays a tiny heartbeat (≤1 KB).
# STATUS_FILE is what the auto-heal monitor checks; LIVE_STATE_FILE is what the
# dashboard panels read for real-time position/signal data.
LIVE_STATE_FILE       = "kraken-bot/live_state.json"
PAPER_PORTFOLIO_FILE  = "kraken-bot/paper_portfolio.json"
CONTROL_FILE          = "kraken-bot/control.json"
