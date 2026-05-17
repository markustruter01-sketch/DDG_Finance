"""
config.py — Kraken Current Bot Configuration
Bot #8: BB Breakout — Bollinger Band breakout with RSI momentum filter
$100,000 paper capital | 15-minute cycle
"""
from __future__ import annotations
import os

BOT_ID = "kraken-current"
DISPLAY_NAME = "Kraken Current"
DB_ID = 8
STRATEGY_TYPE = "bb_breakout"
STRATEGY_LABEL = "BB Breakout"
PAPER_STARTING_BALANCE = 100_000.0
PAPER_FEE_PCT = 0.0026
LOOP_SLEEP_SECONDS = 900   # 15-minute cycle

# ── Asset universe ────────────────────────────────────────────────────────────
SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# ── Data fetch ────────────────────────────────────────────────────────────────
OHLCV_TIMEFRAME = "1h"
OHLCV_LIMIT = 200          # ~8 days of 1h candles for BB calc

# ── Bollinger Band parameters ─────────────────────────────────────────────────
BB_PERIOD = 20             # SMA window
BB_STD_DEV = 2.0           # 2σ band

# ── RSI filter — momentum zone for breakouts ──────────────────────────────────
RSI_PERIOD = 14
RSI_LONG_MIN = 50          # long requires RSI in momentum zone (not oversold)
RSI_LONG_MAX = 75          # but not exhausted/overbought
RSI_SHORT_MIN = 25         # short requires bear-momentum zone
RSI_SHORT_MAX = 50         # but not oversold (exhausted)

# ── Volume filter — breakouts demand conviction ───────────────────────────────
VOLUME_MA_PERIOD = 20
VOLUME_MIN_MULT = 1.5      # entry volume >= 1.5x rolling avg (raised from 1.2)

# ── Risk + sizing ─────────────────────────────────────────────────────────────
RISK_PER_TRADE = 0.02      # 2% of equity per trade
ATR_PERIOD = 14
ATR_STOP_MULTIPLIER = 2.0  # hard stop at 2x ATR
MAX_POSITION_FRACTION = 0.20
MAX_POSITIONS = 3

# ── Take profit ───────────────────────────────────────────────────────────────
TAKE_PROFIT_PCT = 0.05     # 5% gain target

# ── Exit thresholds ───────────────────────────────────────────────────────────
EXIT_AT_MID_BAND = False   # breakout exits at counter-band, not mid-band
MAX_HOLD_HOURS = 48        # force exit after 2 days
MAX_HOLD_DAYS = 2
EXIT_TARGET = "counter_band"  # exit when trend exhausts at opposite band

# ── Backwards compat — kept for main.py imports ───────────────────────────────
EMA_FAST = 20              # unused by strategy
EMA_SLOW = 100             # unused by strategy
ADX_PERIOD = 14            # unused
ADX_ENTRY_MIN = 0          # disabled
ADX_EXIT_MIN = 0           # disabled
ADX_STRONG = 999           # disabled
ADX_VERY_STRONG = 999      # disabled
ADX_SCALE_WEAK = 1.0       # disabled (flat scaling)
ADX_SCALE_STRONG = 1.0     # disabled
ADX_SCALE_VERY_STRONG = 1.0
HURST_MIN = 0              # disabled
MOMENTUM_DAYS = 10         # unused
VPIN_ENTRY_BLOCK = 999     # disabled
VPIN_EXTREME_EXIT = 999    # disabled
ATR_TRAIL_TRIGGER = 1.0    # re-enabled — trail after 1x ATR favorable move
ATR_TRAIL_MULT = 1.5       # trail by 1.5x ATR from peak price

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
