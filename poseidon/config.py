"""
config.py — Poseidon Bot (#7)
Strategy: Dual-Timeframe Momentum with Volume Confirmation
Exchange: Kraken (crypto)
Cycle: 15 minutes
Capital: $95,175 paper
"""
import os

BOT_ID           = "poseidon"
DISPLAY_NAME     = "FOMO Fred"
DB_ID            = 7

# ── Capital ───────────────────────────────────────────────────────────────────
PAPER_STARTING_BALANCE = 95_175.84  # current equity after pairs trading losses
PAPER_FEE_PCT          = 0.0026     # Kraken taker fee per leg

# ── Cycle ─────────────────────────────────────────────────────────────────────
LOOP_SLEEP_SECONDS = 900   # 15-minute cycle

# ── Universe ──────────────────────────────────────────────────────────────────
# Top liquid pairs by Kraken USD volume — not CoinGecko market cap.
# These have tight spreads and deep books. Updated manually as market evolves.
SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "DOT/USD", "LINK/USD", "MATIC/USD", "ATOM/USD",
    "UNI/USD", "LTC/USD", "BCH/USD", "NEAR/USD", "APT/USD",
    "OP/USD", "ARB/USD", "INJ/USD", "TIA/USD", "SEI/USD",
]

# ── Position Sizing ───────────────────────────────────────────────────────────
MAX_POSITIONS        = 4      # max 4 concurrent positions
RISK_PER_TRADE       = 0.015  # risk 1.5% of equity per trade
MAX_POSITION_PCT     = 0.20   # hard cap 20% equity per position
MIN_POSITION_USD     = 200.0  # minimum position size

# ── Strategy Parameters — 4H Trend Filter ────────────────────────────────────
EMA_FAST             = 21     # 4h candles: 21 bars = 84h trend
EMA_SLOW             = 55     # 4h candles: 55 bars = 220h trend
EMA_MIN_SPREAD_PCT   = 0.003  # EMAs must be 0.3% apart — no flat-market entries

# ── Strategy Parameters — 1H Entry Timing ────────────────────────────────────
RSI_PERIOD           = 14
RSI_LONG_MIN         = 38    # long entry: RSI must be in this range (pullback zone)
RSI_LONG_MAX         = 58    # not overbought
RSI_SHORT_MIN        = 42    # short entry: RSI must be in this range
RSI_SHORT_MAX        = 62    # not oversold

# ── Strategy Parameters — Volume Confirmation ─────────────────────────────────
VOLUME_MA_PERIOD     = 20    # 20-bar volume moving average
VOLUME_MIN_MULT      = 1.5   # current volume must be 1.5x the MA

# ── Strategy Parameters — ATR Stops ──────────────────────────────────────────
ATR_PERIOD           = 14
ATR_STOP_MULT        = 2.5   # hard stop at 2.5x ATR from entry
ATR_TRAIL_TRIGGER    = 2.0   # trail activates after 2.0x ATR profit
ATR_TRAIL_MULT       = 2.0   # trail sits 2.0x ATR below/above best price

# ── Hold Time ─────────────────────────────────────────────────────────────────
MAX_HOLD_HOURS       = 120   # 5 days max hold — force close regardless of P&L
MIN_HOLD_HOURS       = 4     # no exits checked before 4 hours (noise filter)

# ── Circuit Breaker ───────────────────────────────────────────────────────────
CB_CONSECUTIVE_LOSSES = 4    # pause after 4 consecutive losses
CB_PAUSE_HOURS        = 24   # 24h pause

# ── Shorts ────────────────────────────────────────────────────────────────────
ALLOW_SHORTS         = True  # allow short positions
MAX_SHORTS           = 1     # max 1 short at a time

# ── Exchange ──────────────────────────────────────────────────────────────────
KRAKEN_API_KEY    = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET_KEY = os.environ.get("KRAKEN_SECRET_KEY", "")

# ── State files ───────────────────────────────────────────────────────────────
STATUS_FILE      = "poseidon/poseidon_status.json"
LIVE_STATE_FILE  = "poseidon/poseidon_live_state.json"
PORTFOLIO_FILE   = "poseidon/poseidon_paper_portfolio.json"
