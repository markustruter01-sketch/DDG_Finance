"""
Market Clock — US Eastern Time Guard  (v2 — Holiday-Aware)
------------------------------------------------------------
Determines whether the US stock market is currently open for trading.
Alpaca paper trading follows the NYSE calendar: 9:30 AM – 4:00 PM ET,
Monday–Friday, excluding US market holidays and early-close days.

Primary source : Alpaca's /v2/clock endpoint (authoritative, handles
                 half-days and holidays automatically).
Fallback        : Local computation using pytz + the `holidays` library
                 for NYSE holiday detection, including known early-close
                 days (day after Thanksgiving, Christmas Eve, etc.).

Early-close days (market closes at 1:00 PM ET)
-------------------------------------------------
  • The Friday after Thanksgiving
  • Christmas Eve (Dec 24) — when it falls on a weekday
  • New Year's Eve (Dec 31) — when it falls on a weekday (not always)
  NYSE officially announces these; we enumerate the common pattern.
"""

from datetime import date, datetime, timedelta

import pytz
from loguru import logger

from config.settings import settings

ET = pytz.timezone("America/New_York")

MARKET_OPEN_HOUR       = 9
MARKET_OPEN_MIN        = 30
MARKET_CLOSE_HOUR      = 16
MARKET_CLOSE_MIN       = 0
EARLY_CLOSE_HOUR       = 13   # 1:00 PM ET
EARLY_CLOSE_MIN        = 0

_HEADERS = {
    "APCA-API-KEY-ID":     settings.alpaca_api_key,
    "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
}


# ── NYSE holiday set ───────────────────────────────────────────────────────

def _nyse_holidays(year: int) -> set[date]:
    """
    Return the set of NYSE market holidays for *year*.
    Uses the `holidays` library (US market subset) and adds the
    Good Friday early observance that the standard US set omits.
    """
    try:
        import holidays as hol
        us = hol.NYSE(years=year)
        return {d for d in us.keys()}
    except ImportError:
        logger.warning("Market clock | `holidays` package not installed — holiday detection limited")
        return _manual_nyse_holidays(year)


def is_nyse_session_date(check_date: date) -> bool:
    """Return whether *check_date* is a regular NYSE session date.

    This is deliberately date-only and does not call Alpaca.  It is shared by
    historical/reporting jobs where a broker clock request would be both
    nondeterministic and unnecessarily expensive.
    """
    return check_date.weekday() < 5 and check_date not in _nyse_holidays(check_date.year)


def previous_nyse_session_date(check_date: date) -> date:
    """Return the most recent NYSE session before *check_date*."""
    candidate = check_date - timedelta(days=1)
    while not is_nyse_session_date(candidate):
        candidate -= timedelta(days=1)
    return candidate


def _manual_nyse_holidays(year: int) -> set[date]:
    """Minimal hardcoded NYSE holidays when the `holidays` package is absent."""
    holidays = set()
    # New Year's Day
    ny = date(year, 1, 1)
    if ny.weekday() == 6:
        ny += timedelta(days=1)
    elif ny.weekday() == 5:
        ny -= timedelta(days=1)
    holidays.add(ny)
    # MLK Day (3rd Monday Jan)
    holidays.add(_nth_weekday(year, 1, 0, 3))
    # Presidents' Day (3rd Monday Feb)
    holidays.add(_nth_weekday(year, 2, 0, 3))
    # Memorial Day (last Monday May)
    holidays.add(_last_weekday(year, 5, 0))
    # Juneteenth (Jun 19)
    jt = date(year, 6, 19)
    if jt.weekday() == 6:
        jt += timedelta(days=1)
    elif jt.weekday() == 5:
        jt -= timedelta(days=1)
    holidays.add(jt)
    # Independence Day (Jul 4)
    ind = date(year, 7, 4)
    if ind.weekday() == 6:
        ind += timedelta(days=1)
    elif ind.weekday() == 5:
        ind -= timedelta(days=1)
    holidays.add(ind)
    # Labor Day (1st Monday Sep)
    holidays.add(_nth_weekday(year, 9, 0, 1))
    # Thanksgiving (4th Thursday Nov)
    holidays.add(_nth_weekday(year, 11, 3, 4))
    # Christmas (Dec 25)
    xmas = date(year, 12, 25)
    if xmas.weekday() == 6:
        xmas += timedelta(days=1)
    elif xmas.weekday() == 5:
        xmas -= timedelta(days=1)
    holidays.add(xmas)
    return holidays


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


# ── Early-close detection ──────────────────────────────────────────────────

def _nyse_early_close_dates(year: int) -> set[date]:
    """
    Return known NYSE early-close (1:00 PM ET) dates for *year*.
    Pattern: Friday after Thanksgiving, Christmas Eve (weekday), and
    occasionally New Year's Eve — all officially announced by NYSE.
    """
    early: set[date] = set()

    # Friday after Thanksgiving (4th Thursday of November + 1 day)
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    black_friday = thanksgiving + timedelta(days=1)
    if black_friday.weekday() < 5:
        early.add(black_friday)

    # Christmas Eve
    xmas_eve = date(year, 12, 24)
    if xmas_eve.weekday() < 5:
        early.add(xmas_eve)

    # New Year's Eve (NYSE discretionary — add when it falls on a weekday
    # and Christmas is not observed on Dec 26)
    nye = date(year, 12, 31)
    xmas = date(year, 12, 25)
    if nye.weekday() < 5 and xmas.weekday() not in (5, 6):
        early.add(nye)

    return early


def is_early_close_day(check_date: date | None = None) -> bool:
    """
    Return True if *check_date* (defaults to today ET) is a NYSE
    early-close (1:00 PM ET) day.
    """
    if check_date is None:
        check_date = datetime.now(ET).date()
    return check_date in _nyse_early_close_dates(check_date.year)


# ── Core market-open logic ─────────────────────────────────────────────────

def is_market_open() -> bool:
    """
    Return True if the US equity market is currently open.
    Uses Alpaca's live clock endpoint for accuracy.
    Falls back to local ET time check (with holiday detection) on failure.
    """
    try:
        import requests
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/clock",
            headers=_HEADERS,
            timeout=5,
        )
        r.raise_for_status()
        data    = r.json()
        is_open = data.get("is_open", False)
        next_open  = data.get("next_open", "")
        next_close = data.get("next_close", "")
        logger.info(
            f"Market clock: {'OPEN' if is_open else 'CLOSED'} | "
            f"next_open={next_open[:16]} | next_close={next_close[:16]}"
        )
        return is_open
    except Exception as exc:
        logger.warning(f"Market clock API failed ({exc}) — using local ET fallback")
        return _local_et_fallback()


def _local_et_fallback() -> bool:
    """
    Holiday-aware local fallback.
    Returns True only if:
      • Today is Monday–Friday
      • Today is NOT a NYSE holiday
      • Current ET time is within trading hours
        (09:30–16:00 normal days; 09:30–13:00 early-close days)
    """
    now    = datetime.now(ET)
    today  = now.date()

    if today.weekday() >= 5:
        logger.debug("Market clock fallback | Weekend — closed")
        return False

    if today in _nyse_holidays(today.year):
        logger.debug(f"Market clock fallback | NYSE holiday {today} — closed")
        return False

    open_time = now.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0
    )
    if is_early_close_day(today):
        close_time = now.replace(
            hour=EARLY_CLOSE_HOUR, minute=EARLY_CLOSE_MIN, second=0, microsecond=0
        )
        logger.debug(f"Market clock fallback | Early-close day {today} — closes 13:00 ET")
    else:
        close_time = now.replace(
            hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0
        )

    return open_time <= now < close_time


def is_alpaca_maintenance_window() -> bool:
    """
    Return True if now falls within Alpaca's scheduled monthly maintenance window.
    Alpaca performs maintenance on the 2nd Saturday of each month, 9:00–11:00 AM EDT.
    During this window the API may be unavailable — all Alpaca-dependent operations
    (stock trading, account queries, crypto via Alpaca) should be paused.
    """
    now = datetime.now(ET)
    if now.weekday() != 5:
        return False
    day = now.day
    first_day_weekday = date(now.year, now.month, 1).weekday()
    first_saturday = (5 - first_day_weekday) % 7 + 1
    second_saturday = first_saturday + 7
    if day != second_saturday:
        return False
    maint_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    maint_end = now.replace(hour=11, minute=0, second=0, microsecond=0)
    in_window = maint_start <= now < maint_end
    if in_window:
        logger.warning(
            f"Market clock | ALPACA MAINTENANCE WINDOW active "
            f"(2nd Saturday {now.strftime('%Y-%m-%d')} 09:00–11:00 ET)"
        )
    return in_window


def get_next_open() -> str:
    """Return the ISO timestamp of the next market open (from Alpaca clock)."""
    try:
        import requests
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
    Queries the Alpaca calendar API. Falls back to local holiday check.
    Returns False on weekends and holidays.
    """
    today = datetime.now(ET).date().isoformat()
    try:
        import requests
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
        logger.warning(f"Calendar check failed ({exc}) — using local holiday fallback")
        today_date = datetime.now(ET).date()
        if today_date.weekday() >= 5:
            return False
        if today_date in _nyse_holidays(today_date.year):
            return False
        return True
