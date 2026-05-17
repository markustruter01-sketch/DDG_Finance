"""
config.py — Kraken Current Bot Configuration
Bot #8: Mean Reversion — BB(20,2σ) + RSI confirmation
$100,000 paper capital | 15-minute cycle
"""
from __future__ import annotations
import os

BOT_ID = "kraken-current"
DISPLAY_NAME = "Kraken Current"
DB_ID = 8
STRATEGY_TYPE = "mean_reversion"
STRATEGY_LABEL = "Mean Reversion"
PAPER_STARTING_BALANCE = 100_000.0
PAPER_FEE_PCT = 0.0026
LOOP_SLEEP_SECONDS = 900   # 15-minute cycle (was 14400)

# ── Asset universe ────────────────────────────────────────────────────────────
SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# ── Data fetch ────────────────────────────────────────────────────────────────
OHLCV_TIMEFRAME = "1h"     # was "4h"
OHLCV_LIMIT = 200          # ~8 days of 1h candles for BB calc

# ── Bollinger Band parameters ─────────────────────────────────────────────────
BB_PERIOD = 20             # SMA window for middle band
BB_STD_DEV = 2.0           # standard deviation multiplier

# ── RSI confirmation ──────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_LONG_MAX = 30          # only go long if RSI < 30 (oversold)
RSI_SHORT_MIN = 70         # only short if RSI > 70 (overbought)

# ── Volume filter ─────────────────────────────────────────────────────────────
VOLUME_MA_PERIOD = 20
VOLUME_MIN_MULT = 1.2      # entry volume must be >= 1.2x rolling avg

# ── Risk + sizing ─────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.02      # 2% of equity per trade
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 2.0  # stop loss = entry ± 2 * ATR
MAX_POSITION_FRACTION = 0.20
MAX_POSITIONS = 3          # one per symbol max

# ── Take profit ───────────────────────────────────────────────────────────────
TAKE_PROFIT_PCT = 0.05     # 5% — mean revert target

# ── Exit thresholds ───────────────────────────────────────────────────────────
EXIT_AT_MID_BAND = True    # exit when price returns to BB middle band
MAX_HOLD_HOURS = 48        # force exit if no resolution after 2 days
MAX_HOLD_DAYS = 2          # 48h max hold (days form for compat)

# ── Backwards compat — kept for main.py imports ───────────────────────────────
EMA_FAST = 20              # unused by strategy
EMA_SLOW = 100             # unused by strategy
ADX_PERIOD = 14            # unused
ADX_ENTRY_MIN = 0          # disabled (was 25)
ADX_EXIT_MIN = 0           # disabled (was 20)
ADX_STRONG = 999           # disabled
ADX_VERY_STRONG = 999      # disabled
ADX_SCALE_WEAK = 1.0       # disabled (flat scaling)
ADX_SCALE_STRONG = 1.0     # disabled
ADX_SCALE_VERY_STRONG = 1.0
HURST_MIN = 0              # disabled
MOMENTUM_DAYS = 10         # unused
VPIN_ENTRY_BLOCK = 999     # disabled
VPIN_EXTREME_EXIT = 999    # disabled
ATR_TRAIL_TRIGGER = 999    # disabled — mean reversion doesn't trail

# ── Regime multipliers (kept for compat) ──────────────────────────────────────
REGIME_BEAR_SHORT_MULT = 1.0
REGIME_BULL_LONG_MULT = 1.0
REGIME_SIDEWAYS_MULT = 1.0

# ── Circuit breaker ───────────────────────────────────────────────────────────
CB_DRAWDOWN_PCT = 0.08
CB_WINDOW_DAYS = 7
CB_PAUSE_HOURS = 48

# ── Kraken exchange ───────────────────────────────────────────────────────────
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

STATUS_FILE = "kraken-current/kc_status.json"
LIVE_STATE_FILE = "kraken-current/kc_live_state.json"
