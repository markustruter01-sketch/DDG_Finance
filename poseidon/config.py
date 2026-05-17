"""
config.py — Poseidon Bot (#7)
Strategy: Trend-Adaptive Regime Classifier (Breakout + Mean Reversion)
Exchange: Kraken (paper trading) | Cycle: 15 minutes
"""
import os

BOT_ID           = "poseidon"
DISPLAY_NAME     = "FOMO Fred"
DB_ID            = 7

# ── Capital ───────────────────────────────────────────────────────────────────
PAPER_STARTING_BALANCE = 95_175.84
PAPER_FEE_PCT          = 0.0026     # Kraken taker fee per leg

# ── Cycle ─────────────────────────────────────────────────────────────────────
LOOP_SLEEP_SECONDS = 900   # 15-minute cycle

# ── Universe ──────────────────────────────────────────────────────────────────
SYMBOLS = ["BTC/USD", "ETH/USD"]   # was 3 — SOL removed (drag in 6mo backtest)

# ── Data fetch ────────────────────────────────────────────────────────────────
OHLCV_TIMEFRAME    = "4h"
OHLCV_LIMIT        = 200   # ~33 days of 4h candles
OHLCV_TIMEFRAME_1H = "1h"  # secondary timeframe for ATR percentile baseline
OHLCV_LIMIT_1H     = 540   # ~22 days of 1h candles

# ── REGIME CLASSIFIER (ADX + ATR percentile) ──────────────────────────────────
ADX_PERIOD          = 14
ADX_TRENDING_MIN    = 999  # effectively disabled — never enter TRENDING
ADX_RANGING_MAX     = 25   # was 20 — accepts moderate-ADX as ranging
ATR_PERCENTILE_HIGH = 40   # ATR > 40th percentile → elevated vol (unused now)
ATR_PERCENTILE_LOW  = 70   # was 60 — allows slightly elevated vol as ranging
ATR_BASELINE_WINDOW = 90   # days of history for ATR percentile baseline

# ── BREAKOUT MODE (trending regime) ──────────────────────────────────────────
BREAKOUT_BB_PERIOD         = 20
BREAKOUT_BB_STD            = 2.0
BREAKOUT_RSI_LONG_MIN      = 50
BREAKOUT_RSI_LONG_MAX      = 75
BREAKOUT_RSI_SHORT_MIN     = 25
BREAKOUT_RSI_SHORT_MAX     = 50
BREAKOUT_VOLUME_MULT       = 1.5
BREAKOUT_ATR_STOP_MULT     = 2.0
BREAKOUT_ATR_TRAIL_TRIGGER = 1.5
BREAKOUT_ATR_TRAIL_MULT    = 1.5
BREAKOUT_TP_PCT            = 0.08   # 8% take profit
BREAKOUT_MAX_HOLD_HOURS    = 120    # 5 days

# ── MEAN REVERSION MODE (ranging regime) ──────────────────────────────────────
MEANREV_BB_PERIOD      = 20
MEANREV_BB_STD         = 2.0
MEANREV_RSI_LONG_MAX   = 30    # was 25 — slightly wider long entry zone
MEANREV_RSI_SHORT_MIN  = 70    # was 75 — slightly wider short entry zone
MEANREV_VOLUME_MULT    = 1.2
MEANREV_ATR_STOP_MULT  = 1.5   # was 2.0 — tighter stop improves breakeven math
MEANREV_TP_PCT         = 0.04  # 4% take profit
MEANREV_MAX_HOLD_HOURS = 72    # 3 days

# ── RISK ──────────────────────────────────────────────────────────────────────
RISK_PER_TRADE        = 0.015  # 1.5% per trade
MAX_POSITIONS         = 3
MAX_POSITION_FRACTION = 0.25

# ── LEGACY COMPAT (kept so main.py doesn't break on old config refs) ──────────
EMA_FAST           = 21
EMA_SLOW           = 55
EMA_MIN_SPREAD_PCT = 0.003
RSI_PERIOD         = 14
RSI_LONG_MIN       = 38
RSI_LONG_MAX       = 58
RSI_SHORT_MIN      = 42
RSI_SHORT_MAX      = 62
VOLUME_MA_PERIOD   = 20
VOLUME_MIN_MULT    = 1.5
ATR_PERIOD         = 14
ATR_STOP_MULT      = 2.5
ATR_TRAIL_TRIGGER  = 2.0
ATR_TRAIL_MULT     = 2.0
MAX_HOLD_HOURS     = 120
MIN_HOLD_HOURS     = 4

# ── Legacy position sizing compat ─────────────────────────────────────────────
MAX_POSITION_PCT   = MAX_POSITION_FRACTION
MIN_POSITION_USD   = 200.0

# ── Circuit breaker ───────────────────────────────────────────────────────────
CB_CONSECUTIVE_LOSSES = 4
CB_PAUSE_HOURS        = 24

# ── Shorts ────────────────────────────────────────────────────────────────────
ALLOW_SHORTS = True
MAX_SHORTS   = 1

# ── Exchange ──────────────────────────────────────────────────────────────────
KRAKEN_API_KEY    = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

# ── State files ───────────────────────────────────────────────────────────────
STATUS_FILE     = "poseidon/poseidon_status.json"
LIVE_STATE_FILE = "poseidon/poseidon_live_state.json"
PORTFOLIO_FILE  = "poseidon/poseidon_paper_portfolio.json"
