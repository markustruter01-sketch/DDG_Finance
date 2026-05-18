# Polling intervals (seconds)
LISTING_POLL_INTERVAL  = 120     # 2 min
DEPEG_POLL_INTERVAL    = 120     # 2 min
MEMECOIN_POLL_INTERVAL = 600     # 10 min
EVENT_POLL_INTERVAL    = 3600    # 1 hr
PRICE_CACHE_INTERVAL   = 60      # 1 min

# Rate limits (calls per minute, conservative)
COINGECKO_MAX_RPM = 25
REDDIT_MAX_RPM    = 50
CCXT_MAX_RPM      = 60

# Endpoints
COINGECKO_BASE    = "https://api.coingecko.com/api/v3"
REDDIT_CRYPTO     = "https://www.reddit.com/r/cryptocurrency.json"
COINBASE_PRODUCTS_API = "https://api.exchange.coinbase.com/products"
BINANCE_EXCHANGE_INFO = "https://data-api.binance.vision/api/v3/exchangeInfo"
COINGECKO_COINS_LIST  = "https://api.coingecko.com/api/v3/coins/list"

# Service identity
SERVICE_NAME       = "crypto-signals"
LOOP_SLEEP_SECONDS = 60   # main loop checks every minute, dispatches to detectors
