"""When the forex market is shut, and what that means for OANDA alarms.

One place for the forex week (Sunday 17:00 to Friday 17:00, New York). Over the
weekend OANDA's API often answers 5xx (maintenance), and a read failure then is
expected, not an incident: the alarm paths ask ``oanda_weekend()`` and record a
quiet note instead. From the Sunday open, a failing OANDA read alarms as before.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
FOREX_DAY_CLOSE = time(17, 0)   # New York; the forex week ends Friday and starts Sunday at this time
WEEKEND_NOTE = "Forex market closed for the weekend: OANDA offline is expected, not an alarm"


def forex_open(now: datetime) -> bool:
    """Sunday 17:00 to Friday 17:00, New York."""
    ny = now.astimezone(NEW_YORK)
    wd, t = ny.weekday(), ny.time()
    if wd == 5:
        return False
    if wd == 6:
        return t >= FOREX_DAY_CLOSE
    if wd == 4:
        return t < FOREX_DAY_CLOSE
    return True


def oanda_weekend(now: datetime | float | None = None) -> bool:
    """True while the forex market is closed. ``now`` may be a datetime or epoch seconds."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif not isinstance(now, datetime):
        now = datetime.fromtimestamp(float(now), timezone.utc)
    return not forex_open(now)


def mentions_oanda(value: Any) -> bool:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return "oanda" in text.lower()


FOREX_BOT = "forex_ai"


def forex_bot_resting(bot_id: str, now: datetime | float | None = None) -> bool:
    """The Forex bot over the weekend: its cycles fail or pause while OANDA is offline,
    so "stale" or "cycles failing" is expected then, not an alarm."""
    return bot_id == FOREX_BOT and oanda_weekend(now)
