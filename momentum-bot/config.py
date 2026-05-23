"""Momentum bot config. BOT_ID from env — fail fast if missing."""
import os

BOT_ID = os.environ["BOT_ID"]
if BOT_ID not in ("momentum_alpha", "momentum_beta", "momentum_gamma"):
    raise ValueError(f"Invalid BOT_ID: {BOT_ID}")

RANK_PICK = {
    "momentum_alpha": 1,
    "momentum_beta":  2,
    "momentum_gamma": 3,
}[BOT_ID]

STARTING_CAPITAL       = 100_000
POSITION_SIZE_PCT      = 0.30
EMA_FAST               = 20
EMA_SLOW               = 50
ADX_PERIOD             = 14
ADX_THRESHOLD          = 25
ATR_PERIOD             = 14
TRAILING_STOP_ATR_MULT = 2.0
MAX_HOLD_DAYS          = 180
UNIVERSE_SIZE          = 50
ENTRY_RANK_THRESHOLD   = 3
EXIT_RANK_THRESHOLD    = 10
CYCLE_HOUR_UTC         = 0
CYCLE_MINUTE_UTC       = 5
