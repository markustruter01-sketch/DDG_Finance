BOT_ID = "memecoin_velocity"
LOOP_SLEEP_SECONDS = 120  # check signals every 2 min

# Position sizing
POSITION_PCT_PER_TRADE = 0.05   # 5% per memecoin
MAX_POSITIONS          = 5
MAX_POSITION_FRACTION  = 0.10

# Exit rules
HARD_STOP_PCT     = 0.20   # -20% hard stop
TRAILING_STOP_PCT = 0.25   # -25% from peak
TAKE_PROFIT_PCT   = 1.00   # +100% take profit
MAX_HOLD_HOURS    = 72     # 3 days max

# Anti-FOMO / cooldown
COOLDOWN_DAYS = 7          # don't re-enter same coin for 7 days

# Costs
FEE_PCT      = 0.0026
SLIPPAGE_PCT = 0.002       # higher slippage for memecoins (less liquid)
