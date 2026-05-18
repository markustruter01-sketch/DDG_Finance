BOT_ID = "listing_pump"
LOOP_SLEEP_SECONDS = 60   # check signals every minute — time-sensitive

# Position sizing
POSITION_PCT_PER_LISTING = 0.08  # 8% of equity per listing
MAX_POSITIONS            = 5
MAX_POSITION_FRACTION    = 0.15

# Entry rules
MAX_PRE_ENTRY_PUMP_PCT   = 0.50  # skip if already +50% from pre-announcement

# Exit rules
HARD_STOP_PCT      = 0.20  # -20% hard stop
TRAILING_STOP_PCT  = 0.25  # -25% from peak
TAKE_PROFIT_PCT    = 1.00  # +100% take profit
MAX_HOLD_HOURS     = 48

# Costs
FEE_PCT      = 0.0026
SLIPPAGE_PCT = 0.001
