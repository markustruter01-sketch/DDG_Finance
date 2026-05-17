import time
import logging
import requests

from config import (
    LISTING_POLL_INTERVAL, DEPEG_POLL_INTERVAL, MEMECOIN_POLL_INTERVAL,
    EVENT_POLL_INTERVAL, PRICE_CACHE_INTERVAL, LOOP_SLEEP_SECONDS, SERVICE_NAME,
    COINGECKO_BASE, COINGECKO_MAX_RPM,
)
from http_client import RateLimitedClient
from price_cache import update_price as _cache_update, get_price
from signal_writer import write_signal

logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

_http = RateLimitedClient()

# CoinGecko IDs → canonical symbol
STABLECOIN_IDS = {
    "tether":            "USDT",
    "usd-coin":          "USDC",
    "dai":               "DAI",
    "first-digital-usd": "FDUSD",
    "true-usd":          "TUSD",
}

STABLECOIN_LIST  = ["USDT", "USDC", "DAI", "FDUSD", "TUSD"]
DEPEG_THRESHOLD  = 0.995
SEVERITY_HIGH    = 0.99
SEVERITY_EXTREME = 0.98


def detect_listings():
    """Stub — implemented in Session 4."""
    pass


def detect_depegs():
    """Check cached stablecoin prices for depegs, emit signals."""
    for stable in STABLECOIN_LIST:
        price = get_price(stable)
        if price is None:
            continue
        if price >= DEPEG_THRESHOLD:
            continue
        if price < SEVERITY_EXTREME:
            severity = "extreme"
        elif price < SEVERITY_HIGH:
            severity = "high"
        else:
            severity = "medium"
        write_signal(
            signal_type="stablecoin_depegged",
            asset=stable,
            severity=severity,
            payload={"price_usd": price, "threshold": DEPEG_THRESHOLD},
        )
        logger.warning(f"DEPEG DETECTED: {stable} at ${price:.4f} (severity={severity})")


def detect_memecoin_velocity():
    """Stub — implemented in Session 5."""
    pass


def refresh_event_calendar():
    """Stub — implemented in Session 3."""
    pass


def update_price_cache():
    """Poll CoinGecko for stablecoin prices, update cache."""
    try:
        ids = ",".join(STABLECOIN_IDS.keys())
        url = f"{COINGECKO_BASE}/simple/price?ids={ids}&vs_currencies=usd"
        resp = _http.get("coingecko", url, COINGECKO_MAX_RPM)
        if resp.status_code != 200:
            logger.warning(f"coingecko price fetch failed: {resp.status_code}")
            return
        data = resp.json()
        for cg_id, symbol in STABLECOIN_IDS.items():
            price = data.get(cg_id, {}).get("usd")
            if price is not None:
                _cache_update(symbol, float(price))
        logger.info(f"price cache updated: {len(data)} stables")
    except Exception as e:
        logger.error(f"update_price_cache error: {e}")


def main():
    logger.info(f"{SERVICE_NAME} | starting up")
    last_run = {
        "listings": 0, "depegs": 0, "memecoin": 0, "events": 0, "prices": 0,
    }
    while True:
        now = time.time()
        try:
            if now - last_run["prices"]   >= PRICE_CACHE_INTERVAL:
                update_price_cache();        last_run["prices"]   = now
            if now - last_run["listings"] >= LISTING_POLL_INTERVAL:
                detect_listings();           last_run["listings"] = now
            if now - last_run["depegs"]   >= DEPEG_POLL_INTERVAL:
                detect_depegs();             last_run["depegs"]   = now
            if now - last_run["memecoin"] >= MEMECOIN_POLL_INTERVAL:
                detect_memecoin_velocity();  last_run["memecoin"] = now
            if now - last_run["events"]   >= EVENT_POLL_INTERVAL:
                refresh_event_calendar();    last_run["events"]   = now
        except Exception as e:
            logger.error(f"main loop error: {e}")
        time.sleep(LOOP_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
