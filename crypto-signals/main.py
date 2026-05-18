import time
import logging
import requests

from config import (
    LISTING_POLL_INTERVAL, DEPEG_POLL_INTERVAL, MEMECOIN_POLL_INTERVAL,
    EVENT_POLL_INTERVAL, PRICE_CACHE_INTERVAL, LOOP_SLEEP_SECONDS, SERVICE_NAME,
    COINGECKO_BASE, COINGECKO_MAX_RPM,
    COINBASE_LISTINGS, BINANCE_LISTINGS,
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
DEPEG_THRESHOLD  = 0.985
SEVERITY_HIGH    = 0.97
SEVERITY_EXTREME = 0.95


import re
from bs4 import BeautifulSoup

_seen_listings: set = set()
_listings_initialized = False

LISTING_KEYWORDS = ["listing", "listed", "launches", "announcing support", "now trading"]
_ASSET_PATTERN = re.compile(r'\b([A-Z]{2,8})\b')
_STRIP_WORDS = re.compile(
    r"\b(USD|USDT|USDC|BTC|ETH|THE|FOR|ARE|WAS|AND|NOW|ON|TO|WILL|IS)\b",
    re.I,
)


def _extract_assets_from_title(title: str) -> list:
    """Extract candidate token tickers from announcement title."""
    title = _STRIP_WORDS.sub("", title)
    matches = _ASSET_PATTERN.findall(title)
    return [m for m in matches if 2 <= len(m) <= 8 and m not in ("THE", "FOR", "ARE", "WAS")]


def _scrape_coinbase_listings() -> list:
    """Scrape coinbase.com/blog/category/listing for recent announcements."""
    try:
        resp = _http.get("coinbase", COINBASE_LISTINGS, max_rpm=10)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        listings = []
        for article in soup.find_all(["article", "a"], limit=20):
            title_el = article.find(["h2", "h3", "h4"])
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not any(kw in title.lower() for kw in LISTING_KEYWORDS):
                continue
            assets = _extract_assets_from_title(title)
            if not assets:
                continue
            listings.append({
                "exchange": "coinbase",
                "title": title,
                "assets": assets,
                "url": COINBASE_LISTINGS,
            })
        return listings
    except Exception as e:
        logger.error(f"coinbase scrape error: {e}")
        return []


def _scrape_binance_listings() -> list:
    """Scrape binance.com/en/support/announcement/c-48 for recent listings."""
    try:
        resp = _http.get("binance", BINANCE_LISTINGS, max_rpm=10)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        listings = []
        for link in soup.find_all("a", limit=30):
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            if not any(kw in title.lower() for kw in LISTING_KEYWORDS):
                continue
            assets = _extract_assets_from_title(title)
            if not assets:
                continue
            listings.append({
                "exchange": "binance",
                "title": title,
                "assets": assets,
                "url": BINANCE_LISTINGS,
            })
        return listings
    except Exception as e:
        logger.error(f"binance scrape error: {e}")
        return []


def detect_listings():
    """Scan exchange announcement pages for new listings, emit signals."""
    global _listings_initialized
    coinbase = _scrape_coinbase_listings()
    binance  = _scrape_binance_listings()
    all_listings = coinbase + binance

    if not _listings_initialized:
        for listing in all_listings:
            for asset in listing["assets"]:
                _seen_listings.add(f"{listing['exchange']}:{asset}")
        _listings_initialized = True
        logger.info(f"listings initialized: {len(_seen_listings)} pre-existing seen")
        return

    for listing in all_listings:
        for asset in listing["assets"]:
            key = f"{listing['exchange']}:{asset}"
            if key in _seen_listings:
                continue
            _seen_listings.add(key)
            write_signal(
                signal_type="listing_announced",
                asset=asset,
                severity="high",
                payload={
                    "exchange": listing["exchange"],
                    "title": listing["title"],
                    "tier": "tier1",
                    "url": listing["url"],
                },
            )
            logger.warning(f"NEW LISTING: {listing['exchange']} {asset} — {listing['title'][:60]}")


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
