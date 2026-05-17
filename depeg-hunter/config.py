BOT_ID = "depeg_hunter"
LOOP_SLEEP_SECONDS = 60        # check signals every minute

# Universe
STABLECOIN_UNIVERSE = ["USDT", "USDC", "DAI", "FDUSD", "TUSD"]

# Position sizing by severity
POSITION_PCT_MEDIUM  = 0.10   # 10% equity, mild depeg
POSITION_PCT_HIGH    = 0.20   # 20% equity
POSITION_PCT_EXTREME = 0.40   # 40% equity (rare jackpot conditions)

# Exit thresholds
REPEG_THRESHOLD  = 0.999      # exit when price recovers to >= $0.999
MAX_HOLD_HOURS   = 72         # force exit after 72h
HARD_STOP_PRICE  = 0.85       # absolute floor — exit if stable drops below 85¢

# Risk
MAX_POSITIONS = 3             # max concurrent depeg positions
FEE_PCT       = 0.0026        # Kraken-equivalent paper fee
SLIPPAGE_PCT  = 0.001         # 0.1% adverse slippage
