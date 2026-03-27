"""
Market Clock — US Eastern Time Guard
--------------------------------------
Determines whether the US stock market is currently open for trading.
Alpaca paper trading follows NYSE calendar: 9:30 AM – 4:00 PM ET,
Monday–Friday, excluding US market holidays.

We query Alpaca's /v1beta1/calendar endpoint directly rather than
computing locally — this is more reliable as it handles half-days and
holidays automatically.
"""

from datetime import date, datetime

import pytz
import requests
from loguru import logger

from config.settings import settings

ET = pytz.timezone("America/New_York")
MARKET_OPEN_HOUR  = 9
MARKET_OPEN_MIN   = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MIN  = 0

_HEADERS = {
    "APCA-API-KEY-ID":     settings.alpaca_api_key,
    "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
}


def is_market_open() -> bool:
    """
    Return True if the US equity market is currently open.
    Uses Alpaca's live clock endpoint for accuracy.
    Falls back to local ET time check if the API call fails.
    """
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/clock",
            headers=_HEADERS,
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        is_open = data.get("is_open", False)
        next_open  = data.get("next_open", "")
        next_close = data.get("next_close", "")
        logger.info(
            f"Market clock: {'OPEN' if is_open else 'CLOSED'} | "
            f"next_open={next_open[:16]} | next_close={next_close[:16]}"
        )
        return is_open
    except Exception as exc:
        logger.warning(f"Market clock API failed ({exc}) — using local ET time fallback")
        return _local_et_fallback()


def _local_et_fallback() -> bool:
    """
    Local fallback: check if current ET time is within 9:30–16:00
    on a weekday. Does NOT account for US holidays.
    """
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_time  = now.replace(hour=MARKET_OPEN_HOUR,  minute=MARKET_OPEN_MIN,  second=0, microsecond=0)
    close_time = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
    return open_time <= now < close_time


def get_next_open() -> str:
    """Return the ISO timestamp of the next market open (from Alpaca clock)."""
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/clock",
            headers=_HEADERS,
            timeout=5,
        )
        r.raise_for_status()
        return r.json().get("next_open", "unknown")
    except Exception:
        return "unknown"


def market_open_today() -> bool:
    """
    Check if there is a trading session today (US ET date).
    Queries the Alpaca calendar API.
    Returns False on weekends and holidays.
    """
    today = date.today().isoformat()
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/calendar",
            headers=_HEADERS,
            params={"start": today, "end": today},
            timeout=5,
        )
        r.raise_for_status()
        days = r.json()
        if days:
            logger.info(f"Market open today ({today}): YES — {days[0]}")
            return True
        logger.info(f"Market open today ({today}): NO (holiday or weekend)")
        return False
    except Exception as exc:
        logger.warning(f"Calendar check failed ({exc}) — assuming market is open")
        return True
