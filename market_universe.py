"""
market_universe.py — Dynamic market universe from CoinGecko + Kraken
Fetches top N cryptocurrencies by market cap from CoinGecko and cross-references
against available USD pairs on Kraken exchange (ccxt).

Caches results locally for 24 hours to avoid API rate limits.
"""
from __future__ import annotations

import json
import os
import time

import requests
from loguru import logger

_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_universe_cache.json")
_CACHE_TTL = 86400  # 24 hours

_COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"

# Stablecoins and wrapped tokens to exclude from trading universe
_EXCLUDE_SYMBOLS = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USDD", "GUSD",
    "WBTC", "WETH", "WBNB", "STETH", "CBETH", "RETH",
    "PAXG", "XAUT",  # gold tokens
}


def _fetch_coingecko_top(n: int = 250) -> list[str]:
    """
    Fetch top N coins by market cap from CoinGecko (free API, no key needed).
    Returns list of uppercase ticker symbols (e.g. ["BTC", "ETH", ...]).
    """
    symbols: list[str] = []
    per_page = 250
    page = 1

    while len(symbols) < n:
        try:
            resp = requests.get(
                _COINGECKO_URL,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": per_page,
                    "page": page,
                    "sparkline": "false",
                },
                timeout=20,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 429:
                logger.warning("Market universe | CoinGecko rate-limited — sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                logger.warning(f"Market universe | CoinGecko HTTP {resp.status_code}")
                break
            data = resp.json()
            if not data:
                break
            for coin in data:
                sym = coin.get("symbol", "").upper().strip()
                if sym and sym not in _EXCLUDE_SYMBOLS:
                    symbols.append(sym)
            if len(data) < per_page:
                break
            page += 1

        except Exception as e:
            logger.error(f"Market universe | CoinGecko fetch error: {e}")
            break

    logger.info(f"Market universe | CoinGecko returned {len(symbols)} non-stable symbols")
    return symbols[:n]


def _get_kraken_usd_pairs(exchange) -> set[str]:
    """Return set of ccxt symbols on Kraken with USD quote (e.g. 'BTC/USD')."""
    try:
        markets = exchange.load_markets()
        pairs = set()
        for sym, mkt in markets.items():
            if (
                mkt.get("quote") == "USD"
                and mkt.get("active", True)
                and "/" in sym
                and not mkt.get("info", {}).get("altname", "").endswith(".d")  # skip dark pool
            ):
                pairs.add(sym)
        logger.info(f"Market universe | Kraken has {len(pairs)} active USD pairs")
        return pairs
    except Exception as e:
        logger.error(f"Market universe | Kraken markets load error: {e}")
        return set()


def get_kraken_universe(exchange, n: int = 250) -> list[str]:
    """
    Get top N crypto assets by CoinGecko market cap that trade as USD pairs on Kraken.

    Args:
        exchange: ccxt Kraken exchange instance
        n: number of top coins to fetch from CoinGecko

    Returns:
        List of ccxt-format symbols: ['BTC/USD', 'ETH/USD', ...]
        Ordered by CoinGecko market cap rank (largest first).
        Cached for 24 hours.
    """
    # Try cache first
    if os.path.exists(_CACHE_FILE):
        try:
            cache = json.loads(open(_CACHE_FILE).read())
            age = time.time() - cache.get("timestamp", 0)
            if age < _CACHE_TTL:
                syms = cache.get("symbols", [])
                if syms:
                    logger.info(
                        f"Market universe | Cache hit: {len(syms)} symbols "
                        f"(age={age / 3600:.1f}h, refreshes in {(_CACHE_TTL - age) / 3600:.1f}h)"
                    )
                    return syms
        except Exception:
            pass

    # Fetch fresh data
    logger.info(f"Market universe | Building fresh universe (top {n} by market cap)...")
    cg_symbols = _fetch_coingecko_top(n)
    kraken_pairs = _get_kraken_usd_pairs(exchange)

    # Cross-reference: keep only CoinGecko symbols that exist on Kraken as /USD
    universe: list[str] = []
    seen: set[str] = set()
    for cg_sym in cg_symbols:
        candidate = f"{cg_sym}/USD"
        if candidate in kraken_pairs and candidate not in seen:
            universe.append(candidate)
            seen.add(candidate)

    logger.info(
        f"Market universe | Final universe: {len(universe)} symbols "
        f"(from top {n} CoinGecko ∩ Kraken USD pairs)"
    )

    # Persist cache
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump({"timestamp": time.time(), "n_requested": n, "symbols": universe}, f, indent=2)
    except Exception as e:
        logger.warning(f"Market universe | Cache write failed: {e}")

    return universe


def invalidate_cache():
    """Force a fresh market universe fetch on the next call."""
    try:
        if os.path.exists(_CACHE_FILE):
            os.remove(_CACHE_FILE)
            logger.info("Market universe | Cache invalidated")
    except Exception:
        pass
