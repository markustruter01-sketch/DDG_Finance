import os
import time
import logging
import requests

from config import (
    LISTING_POLL_INTERVAL, DEPEG_POLL_INTERVAL, MEMECOIN_POLL_INTERVAL,
    EVENT_POLL_INTERVAL, PRICE_CACHE_INTERVAL, LOOP_SLEEP_SECONDS, SERVICE_NAME,
    COINGECKO_BASE, COINGECKO_MAX_RPM, REDDIT_MAX_RPM,
    COINBASE_PRODUCTS_API, BINANCE_EXCHANGE_INFO, COINGECKO_COINS_LIST,
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
import sys as _sys
import os as _os

# Ensure trading-platform db module is importable (signal_writer sets this up too,
# but we reference it explicitly here for clarity).
_REPO_ROOT = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..")
_TRADING_PLATFORM = _os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in _sys.path:
    _sys.path.insert(0, _TRADING_PLATFORM)

# DB-backed dedup — loaded once from listing_dedup table at first detect_listings() call.
# CoinGecko-source keys are added to the in-memory set only (no DB write — they're
# always rejected by the exchange filter so no need to persist them).
_listing_dedup_cache: set = set()
_listing_dedup_loaded: bool = False

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
    """Poll Coinbase exchange products API — returns all online USD-quoted pairs.
    detect_listings() diffs against _seen_listings to fire signals for new ones.
    """
    try:
        resp = _http.get("coinbase", COINBASE_PRODUCTS_API, max_rpm=10)
        if resp.status_code != 200:
            logger.warning(f"coinbase products API {resp.status_code}")
            return []
        listings = []
        for p in resp.json():
            if p.get("quote_currency") not in ("USD", "USDT", "USDC"):
                continue
            if p.get("status") != "online":
                continue
            base = p.get("base_currency", "").upper()
            if not base or len(base) > 10:
                continue
            listings.append({
                "exchange": "coinbase",
                "title": f"Coinbase listing: {base}/{p.get('quote_currency')}",
                "assets": [base],
                "url": f"https://www.coinbase.com/advanced-trade/spot/{p.get('id', '')}",
            })
        return listings
    except Exception as e:
        logger.error(f"coinbase products API error: {e}")
        return []


def _scrape_binance_listings() -> list:
    """Poll Binance Vision exchange info — returns all TRADING USDT/USDC pairs.
    detect_listings() diffs against _seen_listings to fire signals for new ones.
    """
    try:
        resp = _http.get("binance", BINANCE_EXCHANGE_INFO, max_rpm=5)
        if resp.status_code != 200:
            logger.warning(f"binance exchangeInfo {resp.status_code}")
            return []
        listings = []
        for sym in resp.json().get("symbols", []):
            if sym.get("quoteAsset") not in ("USDT", "USDC"):
                continue
            if sym.get("status") != "TRADING":
                continue
            base = sym.get("baseAsset", "").upper()
            if not base or len(base) > 10:
                continue
            quote = sym.get("quoteAsset", "USDT")
            listings.append({
                "exchange": "binance",
                "title": f"Binance listing: {base}/{quote}",
                "assets": [base],
                "url": f"https://www.binance.com/en/trade/{base}_{quote}",
            })
        return listings
    except Exception as e:
        logger.error(f"binance exchangeInfo API error: {e}")
        return []


def _scrape_coingecko_new_coins() -> list:
    """Poll CoinGecko /coins/list — full coin catalogue.
    detect_listings() diffs coin IDs against _seen_listings to fire signals for new ones.
    Uses coin ID as the unique asset key to avoid symbol collisions across forks.
    """
    try:
        resp = _http.get("coingecko", COINGECKO_COINS_LIST, COINGECKO_MAX_RPM)
        if resp.status_code != 200:
            logger.warning(f"coingecko /coins/list {resp.status_code}")
            return []
        listings = []
        for coin in resp.json():
            coin_id = coin.get("id", "")
            symbol  = coin.get("symbol", "").upper()
            name    = coin.get("name", symbol)
            if not coin_id or not symbol or len(symbol) > 10:
                continue
            listings.append({
                "exchange": "coingecko",
                "title": f"CoinGecko listed: {name} ({symbol})",
                # Use coin_id as the dedup key so symbol clashes across forks don't cross-fire
                "assets": [coin_id],
                "url": f"https://www.coingecko.com/en/coins/{coin_id}",
                # Stash the real ticker so listing-pump can use it for price lookups
                "symbol": symbol,
            })
        return listings
    except Exception as e:
        logger.error(f"coingecko /coins/list error: {e}")
        return []


def _load_listing_dedup() -> None:
    """Load all persisted dedup keys from DB into _listing_dedup_cache. Called once."""
    global _listing_dedup_cache, _listing_dedup_loaded
    if _listing_dedup_loaded:
        return
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            logger.warning("listing_dedup load skipped — DB unavailable")
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM listing_dedup")
                for (key,) in cur.fetchall():
                    _listing_dedup_cache.add(key)
        logger.info(f"listing_dedup loaded: {len(_listing_dedup_cache)} known keys")
    except Exception as e:
        logger.warning(f"listing_dedup load failed (non-fatal): {e}")
    finally:
        _listing_dedup_loaded = True


def _persist_listing_key(key: str) -> None:
    """Persist a new dedup key to listing_dedup. Silently ignores conflicts/failures."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO listing_dedup (key) VALUES (%s) ON CONFLICT DO NOTHING",
                    (key,),
                )
    except Exception as e:
        logger.debug(f"listing_dedup persist failed (non-fatal): {e}")


def _lookup_price(asset: str):
    """Try CoinGecko simple/price for a listing candidate (by CG coin ID or symbol)."""
    cached = get_price(asset)
    if cached is not None:
        return cached
    try:
        url = f"{COINGECKO_BASE}/simple/price?ids={asset.lower()}&vs_currencies=usd"
        resp = _http.get("coingecko", url, COINGECKO_MAX_RPM)
        if resp.status_code != 200:
            return None
        data = resp.json()
        for v in data.values():
            if "usd" in v:
                return float(v["usd"])
        return None
    except Exception:
        return None


def detect_listings():
    """Scan exchange announcement pages for new listings, emit signals.

    Filter order (upstream, before write_signal):
      1. Dedup — skip if key already in DB-backed cache
      2. Exchange — reject coingecko-source entirely (no tradeable exchange)
      3. Price — reject if price found and below $0.001 threshold
         (None price for Binance/Coinbase assets is allowed — CG ID ≠ ticker)
    """
    _load_listing_dedup()
    coinbase  = _scrape_coinbase_listings()
    binance   = _scrape_binance_listings()
    coingecko = _scrape_coingecko_new_coins()
    all_listings = coinbase + binance + coingecko

    for listing in all_listings:
        exchange = listing["exchange"]
        for asset in listing["assets"]:
            key = f"{exchange}:{asset}"

            if key in _listing_dedup_cache:
                continue

            # === Filter 1: reject CoinGecko-source (not tradeable on any real exchange) ===
            if exchange.lower() == "coingecko":
                logger.info(f"skipped coingecko-source: {asset}")
                _listing_dedup_cache.add(key)  # in-memory only — no DB write for CG noise
                continue

            # === Filter 2: price check for Binance/Coinbase candidates ===
            # None = price unknown (CG ID ≠ ticker for exchange-listed assets) → allow through.
            # Only reject if we can confirm the price is sub-penny trash.
            price = _lookup_price(asset)
            if price is not None and price < 0.001:
                logger.info(f"skipped sub-threshold: {asset} @ ${price:.8f}")
                continue

            # === All filters passed — persist dedup, emit signal ===
            _listing_dedup_cache.add(key)
            _persist_listing_key(key)
            write_signal(
                signal_type="listing_announced",
                asset=asset,
                severity="high",
                payload={
                    "exchange": exchange,
                    "title": listing["title"],
                    "tier": "tier1",
                    "url": listing["url"],
                },
            )
            logger.warning(f"NEW LISTING: {exchange} {asset} — {listing['title'][:60]}")


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


MEMECOIN_UNIVERSE = [
    "DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI", "MEME", "BRETT",
    "POPCAT", "MEW", "TURBO", "DOGS", "NEIRO", "MOG", "PNUT", "GOAT",
    "FARTCOIN", "ACT", "MOODENG", "BABYDOGE",
]

_trending_history: list = []
TRENDING_CONSECUTIVE_REQUIRED = 2

_reddit_mentions_history: dict = {}
_last_signal_time: dict = {}
COOLDOWN_HOURS = 24


def _fetch_trending_coins() -> set:
    """Fetch current top trending from CoinGecko, return set of symbols."""
    try:
        url = f"{COINGECKO_BASE}/search/trending"
        resp = _http.get("coingecko", url, COINGECKO_MAX_RPM)
        if resp.status_code != 200:
            return set()
        data = resp.json()
        coins = data.get("coins", [])
        return {c.get("item", {}).get("symbol", "").upper() for c in coins[:7]}
    except Exception as e:
        logger.error(f"trending fetch error: {e}")
        return set()


def _fetch_reddit_mention_count(symbol: str) -> int:
    """Count occurrences of $symbol or symbol token in recent r/cryptocurrency posts."""
    try:
        url = "https://www.reddit.com/r/cryptocurrency/new.json?limit=100"
        resp = _http.get("reddit", url, REDDIT_MAX_RPM,
                         headers={"User-Agent": "crypto-signals/1.0"})
        if resp.status_code != 200:
            return 0
        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        count = 0
        sym_upper = symbol.upper()
        sym_dollar = f"${sym_upper}"
        for post in posts:
            text = (post["data"].get("title", "") + " " +
                    post["data"].get("selftext", "")).upper()
            if sym_dollar in text or f" {sym_upper} " in f" {text} ":
                count += 1
        return count
    except Exception as e:
        logger.error(f"reddit fetch error for {symbol}: {e}")
        return 0


def _check_price_volume_breakout(symbol: str) -> dict:
    """Check if coin has new 30d high + volume 2x avg via Binance ccxt."""
    try:
        import ccxt
        exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
                "fetchMarkets": ["spot"],
            },
            "urls": {
                "api": {
                    "public":  "https://data-api.binance.vision/api/v3",
                    "private": "https://data-api.binance.vision/api/v3",
                    "v1":      "https://data-api.binance.vision/api/v1",
                }
            }
        })
        pair_attempts = [f"{symbol}/USDT", f"{symbol}/USD", f"1000{symbol}/USDT"]
        bars = None
        used_pair = None
        for pair in pair_attempts:
            try:
                bars = exchange.fetch_ohlcv(pair, "1d", limit=35)
                used_pair = pair
                if bars:
                    break
            except Exception:
                continue
        if not bars or len(bars) < 30:
            return {"valid": False, "reason": "no_data"}
        closes  = [b[4] for b in bars]
        volumes = [b[5] for b in bars]
        current_price   = closes[-1]
        prior_30d_high  = max(closes[:-1])
        current_volume  = volumes[-1]
        avg_volume      = sum(volumes[-8:-1]) / 7 if len(volumes) >= 8 else 1
        return {
            "valid": True,
            "is_new_high": current_price > prior_30d_high,
            "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 0,
            "current_price": current_price,
            "pair": used_pair,
        }
    except Exception as e:
        return {"valid": False, "reason": str(e)}


def detect_memecoin_velocity():
    """Triple-gated memecoin breakout detection."""
    import time as _t

    # === Gate 1: CoinGecko trending ===
    current_trending = _fetch_trending_coins()
    _trending_history.append(current_trending)
    if len(_trending_history) > 5:
        _trending_history.pop(0)

    if len(_trending_history) < TRENDING_CONSECUTIVE_REQUIRED:
        return

    recent_trending = _trending_history[-TRENDING_CONSECUTIVE_REQUIRED:]
    consistently_trending = set.intersection(*recent_trending)
    candidates = consistently_trending & set(MEMECOIN_UNIVERSE)
    if not candidates:
        return

    logger.info(f"trending candidates: {candidates}")

    for symbol in candidates:
        last_signal = _last_signal_time.get(symbol, 0)
        if _t.time() - last_signal < COOLDOWN_HOURS * 3600:
            continue

        # === Gate 2: Reddit mention velocity ===
        mention_count = _fetch_reddit_mention_count(symbol)
        history = _reddit_mentions_history.setdefault(symbol, [])
        history.append((_t.time(), mention_count))
        cutoff = _t.time() - 86400
        history[:] = [(t, c) for t, c in history if t >= cutoff]
        if len(history) < 3:
            logger.info(f"{symbol}: insufficient reddit history ({len(history)} samples)")
            continue
        prior_counts = [c for t, c in history[:-1]]
        avg_mentions = sum(prior_counts) / len(prior_counts) if prior_counts else 0
        if mention_count < avg_mentions * 2 or mention_count < 3:
            logger.info(f"{symbol}: reddit velocity too low (curr={mention_count} avg={avg_mentions:.1f})")
            continue

        # === Gate 3: Price/volume breakout ===
        breakout = _check_price_volume_breakout(symbol)
        if not breakout["valid"]:
            logger.info(f"{symbol}: price/volume check failed ({breakout.get('reason')})")
            continue
        if not breakout["is_new_high"] or breakout["volume_ratio"] < 2.0:
            logger.info(f"{symbol}: not breakout (new_high={breakout['is_new_high']}, vol={breakout['volume_ratio']:.2f}x)")
            continue

        # ALL THREE GATES PASSED — emit signal
        _last_signal_time[symbol] = _t.time()
        write_signal(
            signal_type="memecoin_breakout",
            asset=symbol,
            severity="high",
            payload={
                "current_price": breakout["current_price"],
                "pair": breakout["pair"],
                "volume_ratio": breakout["volume_ratio"],
                "reddit_mentions": mention_count,
                "reddit_avg": avg_mentions,
            },
        )
        logger.warning(f"MEMECOIN BREAKOUT: {symbol} @ ${breakout['current_price']:.6f} vol={breakout['volume_ratio']:.1f}x reddit={mention_count}")


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


import socket as _ka_socket
import threading as _ka_threading

def _keep_alive_listener():
    """Bind to $PORT to satisfy Replit's port-readiness check."""
    try:
        port = int(os.environ.get("PORT", "8095"))
        s = _ka_socket.socket(_ka_socket.AF_INET, _ka_socket.SOCK_STREAM)
        s.setsockopt(_ka_socket.SOL_SOCKET, _ka_socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(5)
        while True:
            conn, _ = s.accept()
            conn.close()
    except Exception as _e:
        pass

_ka_threading.Thread(target=_keep_alive_listener, daemon=True).start()


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
