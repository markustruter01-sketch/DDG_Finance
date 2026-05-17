BOT_ID = "event_trader"
LOOP_SLEEP_SECONDS = 900   # 15 min — event-driven bot, no rush

# Universe — major crypto assets we'll trade events for
UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD"]

# Entry/exit timing
ENTRY_DAYS_BEFORE_EVENT   = 5    # enter long 5 days before high-impact event
PARTIAL_EXIT_HOURS_BEFORE = 24   # exit 50% 24h before event
EVENT_DAY_EXIT_HOURS      = 0    # exit remaining 50% at event time

# Position sizing
RISK_PCT_HIGH_IMPACT   = 0.20  # 20% per high-impact event
MAX_POSITIONS          = 3
MAX_POSITION_FRACTION  = 0.30

# Risk management
HARD_STOP_PCT     = 0.10  # -10% hard stop if anticipation rally fails
TRAILING_STOP_PCT = 0.15  # -15% from peak after entry

# Costs (paper trading)
FEE_PCT      = 0.0026
SLIPPAGE_PCT = 0.001

# Event classification thresholds (Groq output)
CLASSIFICATION_HIGH   = "HIGH"
CLASSIFICATION_MEDIUM = "MEDIUM"
CLASSIFICATION_LOW    = "LOW"

# Refresh intervals
EVENT_CALENDAR_REFRESH_HOURS = 6   # re-fetch events every 6h
