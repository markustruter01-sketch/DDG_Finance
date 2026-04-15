"""
config.py — Kraken Current Bot Configuration
Bot #8: Trend Following / Time-Series Momentum on Kraken
$100,000 paper capital | 4-hour cycle
"""
from __future__ import annotations
import os

BOT_ID = "kraken-current"
DISPLAY_NAME = "Kraken Current"
DB_ID = 8
STRATEGY_TYPE = "trend_following"
STRATEGY_LABEL = "Trend Following"
PAPER_STARTING_BALANCE = 100_000.0
PAPER_FEE_PCT = 0.0026
LOOP_SLEEP_SECONDS = 14400  # 4 hours

# ── Asset universe ────────────────────────────────────────────────────────────
SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD", "LTC/USD",
]

# ── EMA crossover parameters ──────────────────────────────────────────────────
EMA_FAST = 20     # ~3.3 days on 4h candles
EMA_SLOW = 100    # ~16.7 days on 4h candles
OHLCV_TIMEFRAME = "4h"
OHLCV_LIMIT = 200  # enough for EMA_SLOW + buffer

# ── ADX trend strength ────────────────────────────────────────────────────────
ADX_PERIOD = 20
ADX_ENTRY_MIN = 25      # minimum ADX to enter
ADX_EXIT_MIN = 20       # exit if ADX drops below this
ADX_STRONG = 35         # full position size above this
ADX_VERY_STRONG = 50    # trail stop immediately above this

# ── Hurst exponent ────────────────────────────────────────────────────────────
HURST_MIN = 0.5   # must be > 0.5 (trending) — opposite of mean reversion bots

# ── Momentum confirmation ─────────────────────────────────────────────────────
MOMENTUM_DAYS = 10  # 10-day return for direction confirmation

# ── VPIN ─────────────────────────────────────────────────────────────────────
VPIN_ENTRY_BLOCK = 0.88     # block entry if VPIN above this
VPIN_EXTREME_EXIT = 0.95    # emergency exit if VPIN spikes above this

# ── Position sizing ───────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.02       # 2% of equity per trade
ATR_STOP_MULTIPLIER = 2.0   # stop placed 2x ATR from entry
ATR_TRAIL_TRIGGER = 1.5     # trail triggers at 1.5x ATR profit
MAX_POSITION_FRACTION = 0.20  # cap at 20% of equity per position
MAX_POSITIONS = 5            # maximum simultaneous positions

# ── ADX-based position scaling ────────────────────────────────────────────────
ADX_SCALE_WEAK = 0.70    # ADX 25-35: 70% of calculated size
ADX_SCALE_STRONG = 1.00  # ADX 35-50: 100%
ADX_SCALE_VERY_STRONG = 1.00  # ADX 50+: 100% but trail from entry

# ── Exit conditions ───────────────────────────────────────────────────────────
MAX_HOLD_DAYS = 21  # maximum position age

# ── Regime multipliers ────────────────────────────────────────────────────────
REGIME_BEAR_SHORT_MULT = 1.2   # scale up shorts in bear
REGIME_BULL_LONG_MULT = 1.2    # scale up longs in bull
REGIME_SIDEWAYS_MULT = 0.7     # scale down in sideways/crypto regimes

# ── Circuit breaker ───────────────────────────────────────────────────────────
CB_DRAWDOWN_PCT = 0.08      # 8% drawdown from starting capital
CB_WINDOW_DAYS = 7          # within any 7-day window
CB_PAUSE_HOURS = 48         # pause duration

# ── Kraken exchange ───────────────────────────────────────────────────────────
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

STATUS_FILE = "kraken-current/kc_status.json"
LIVE_STATE_FILE = "kraken-current/kc_live_state.json"
