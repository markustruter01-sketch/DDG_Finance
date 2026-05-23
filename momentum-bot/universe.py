"""Weekly top-50 universe refresh. Race-safe via week-boundary ts + ON CONFLICT.

CoinGecko rate-limit guard:
- Deterministic per-bot jitter (alpha=0s, beta=12s, gamma=24s) staggers the
  three simultaneous startup requests so only one bot actually hits the API.
- After jitter, re-checks the table — if another bot already populated it, skip.
- 3-attempt retry with exponential backoff (30s, 60s) on any HTTP error.
- Falls back to the most recent stored universe if all retries fail.
"""
import logging
import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_TP   = os.path.abspath(os.path.join(_HERE, "..", "trading-platform"))
if _TP not in sys.path: sys.path.insert(0, _TP)
sys.path.insert(0, _HERE)
from db.postgres import get_conn

logger = logging.getLogger("universe")

COINGECKO_TOP50 = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"
)

# Deterministic per-bot jitter — spreads the 3 concurrent startup fetches
_JITTER_SECONDS = {
    "momentum_alpha": 0,
    "momentum_beta":  12,
    "momentum_gamma": 24,
}


def _week_boundary_utc() -> datetime:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=now.weekday())


def _binance_pair(symbol: str) -> str:
    sym = symbol.upper()
    for candidate in [f"{sym}/USDT", f"1000{sym}/USDT", f"{sym}/USD"]:
        return candidate
    return f"{sym}/USDT"


def _read_universe(cur, refresh_ts) -> list:
    cur.execute(
        "SELECT symbol, binance_pair FROM momentum_universe WHERE refresh_ts = %s",
        (refresh_ts,),
    )
    return [{"symbol": r[0], "binance_pair": r[1]} for r in cur.fetchall()]


def _read_any_universe(cur) -> list:
    """Fallback: return the most recent stored universe regardless of week."""
    cur.execute(
        "SELECT symbol, binance_pair FROM momentum_universe "
        "WHERE refresh_ts = (SELECT MAX(refresh_ts) FROM momentum_universe)"
    )
    return [{"symbol": r[0], "binance_pair": r[1]} for r in cur.fetchall()]


def _fetch_coingecko() -> list:
    """Fetch top-50 from CoinGecko with 3-attempt exponential backoff."""
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.get(COINGECKO_TOP50, timeout=25)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_exc = exc
            wait = 30 * (2 ** attempt)   # 30s, 60s, 120s
            if attempt < 2:
                logger.warning(f"CoinGecko attempt {attempt + 1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
    raise last_exc


def refresh_if_needed() -> list:
    week_ts = _week_boundary_utc()

    # Fast path — table already populated for this week
    with get_conn() as conn:
        with conn.cursor() as cur:
            rows = _read_universe(cur, week_ts)
            if rows:
                return rows

    # Apply per-bot jitter OUTSIDE the DB connection so we don't hold a slot
    from config import BOT_ID
    jitter = _JITTER_SECONDS.get(BOT_ID, 0)
    if jitter:
        logger.info(f"Universe jitter: sleeping {jitter}s before CoinGecko fetch")
        time.sleep(jitter)

    # Re-check after jitter — another bot may have populated the table already
    with get_conn() as conn:
        with conn.cursor() as cur:
            rows = _read_universe(cur, week_ts)
            if rows:
                logger.info(f"Universe already populated by peer bot ({len(rows)} symbols)")
                return rows

            # This bot won the race — fetch CoinGecko and insert
            try:
                coins = _fetch_coingecko()
                for c in coins:
                    sym  = c["symbol"].upper()
                    pair = _binance_pair(sym)
                    cur.execute(
                        "INSERT INTO momentum_universe "
                        "    (refresh_ts, symbol, market_cap_usd, binance_pair) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (week_ts, sym, c.get("market_cap"), pair),
                    )
                rows = _read_universe(cur, week_ts)
                logger.info(f"Universe refreshed — {len(rows)} symbols for week {week_ts.date()}")
                return rows
            except Exception as exc:
                # All retries failed — fall back to most recent stored universe
                fallback = _read_any_universe(cur)
                if fallback:
                    logger.error(
                        f"CoinGecko fetch failed ({exc}). "
                        f"Using stale universe ({len(fallback)} symbols)."
                    )
                    return fallback
                logger.error(f"CoinGecko fetch failed and no fallback universe available: {exc}")
                raise
