"""
Economic Calendar — Blackout Window Logic
--------------------------------------------
Maintains a schedule of high-impact US economic releases that can cause
extreme volatility. Trading is suppressed during a configurable window
around each event.

Data sources:
  - Hardcoded recurring schedule (FOMC, CPI, NFP, PCE, GDP, PPI)
  - Known dates are refreshed monthly

The blackout window is +-30 minutes around the scheduled release time.
The pipeline checks is_blackout_active() before placing orders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, date, time
from typing import Any

from loguru import logger

try:
    import pytz
    ET = pytz.timezone("America/New_York")
except ImportError:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")

BLACKOUT_WINDOW_MINUTES = 30

RECURRING_EVENTS: list[dict[str, Any]] = [
    {"name": "FOMC Rate Decision",       "time_et": time(14, 0),  "frequency": "8x/year"},
    {"name": "Non-Farm Payrolls (NFP)",   "time_et": time(8, 30), "frequency": "monthly_first_friday"},
    {"name": "CPI Release",              "time_et": time(8, 30), "frequency": "monthly"},
    {"name": "Core PCE Price Index",     "time_et": time(8, 30), "frequency": "monthly"},
    {"name": "GDP (Advance/Final)",      "time_et": time(8, 30), "frequency": "quarterly"},
    {"name": "PPI Release",             "time_et": time(8, 30), "frequency": "monthly"},
    {"name": "Retail Sales",            "time_et": time(8, 30), "frequency": "monthly"},
    {"name": "Initial Jobless Claims",  "time_et": time(8, 30), "frequency": "weekly_thursday"},
]

_KNOWN_DATES_2025: list[dict[str, Any]] = [
    {"name": "FOMC Rate Decision", "date": date(2025, 1, 29), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 3, 19), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 5, 7),  "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 6, 18), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 7, 30), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 9, 17), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 10, 29), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2025, 12, 17), "time_et": time(14, 0)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 1, 10), "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 2, 7),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 3, 7),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 4, 4),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 5, 2),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 6, 6),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 7, 3),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 8, 1),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 9, 5),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 10, 3), "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 11, 7), "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2025, 12, 5), "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 1, 15),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 2, 12),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 3, 12),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 4, 10),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 5, 13),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 6, 11),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 7, 10),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 8, 12),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 9, 10),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 10, 14), "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 11, 12), "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2025, 12, 10), "time_et": time(8, 30)},
]

_KNOWN_DATES_2026: list[dict[str, Any]] = [
    {"name": "FOMC Rate Decision", "date": date(2026, 1, 28), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 3, 18), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 5, 6),  "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 6, 17), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 7, 29), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 9, 16), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 10, 28), "time_et": time(14, 0)},
    {"name": "FOMC Rate Decision", "date": date(2026, 12, 16), "time_et": time(14, 0)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 1, 9),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 2, 6),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 3, 6),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 4, 3),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 5, 1),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 6, 5),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 7, 2),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 8, 7),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 9, 4),  "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 10, 2), "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 11, 6), "time_et": time(8, 30)},
    {"name": "Non-Farm Payrolls", "date": date(2026, 12, 4), "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 1, 14),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 2, 11),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 3, 11),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 4, 14),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 5, 12),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 6, 10),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 7, 14),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 8, 12),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 9, 15),  "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 10, 13), "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 11, 10), "time_et": time(8, 30)},
    {"name": "CPI Release", "date": date(2026, 12, 10), "time_et": time(8, 30)},
]

_ALL_KNOWN_EVENTS = _KNOWN_DATES_2025 + _KNOWN_DATES_2026


def _generate_weekly_claims(year: int) -> list[dict]:
    events = []
    d = date(year, 1, 1)
    while d.weekday() != 3:
        d += timedelta(days=1)
    while d.year == year:
        events.append({"name": "Initial Jobless Claims", "date": d, "time_et": time(8, 30)})
        d += timedelta(days=7)
    return events


def get_upcoming_events(days_ahead: int = 7) -> list[dict]:
    now = datetime.now(ET)
    today = now.date()
    cutoff = today + timedelta(days=days_ahead)

    events = []
    for ev in _ALL_KNOWN_EVENTS:
        if today <= ev["date"] <= cutoff:
            events.append({
                "name": ev["name"],
                "date": ev["date"].isoformat(),
                "time_et": ev["time_et"].strftime("%H:%M"),
                "days_away": (ev["date"] - today).days,
            })

    for claim in _generate_weekly_claims(today.year):
        if today <= claim["date"] <= cutoff:
            events.append({
                "name": claim["name"],
                "date": claim["date"].isoformat(),
                "time_et": claim["time_et"].strftime("%H:%M"),
                "days_away": (claim["date"] - today).days,
            })

    events.sort(key=lambda e: e["date"])
    return events


def is_blackout_active() -> dict:
    now = datetime.now(ET)
    today = now.date()
    window = timedelta(minutes=BLACKOUT_WINDOW_MINUTES)

    for ev in _ALL_KNOWN_EVENTS:
        if ev["date"] != today:
            continue
        event_dt = datetime.combine(ev["date"], ev["time_et"])
        if hasattr(ET, 'localize'):
            event_dt = ET.localize(event_dt)
        else:
            event_dt = event_dt.replace(tzinfo=ET)
        if (event_dt - window) <= now <= (event_dt + window):
            logger.warning(
                f"BLACKOUT ACTIVE | {ev['name']} at {ev['time_et']} ET | "
                f"Window: {BLACKOUT_WINDOW_MINUTES}min before/after"
            )
            return {
                "active": True,
                "event": ev["name"],
                "event_time_et": ev["time_et"].strftime("%H:%M"),
                "window_minutes": BLACKOUT_WINDOW_MINUTES,
                "message": f"Trading paused: {ev['name']} release window",
            }

    for claim in _generate_weekly_claims(today.year):
        if claim["date"] != today:
            continue
        event_dt = datetime.combine(claim["date"], claim["time_et"])
        if hasattr(ET, 'localize'):
            event_dt = ET.localize(event_dt)
        else:
            event_dt = event_dt.replace(tzinfo=ET)
        if (event_dt - window) <= now <= (event_dt + window):
            return {
                "active": True,
                "event": claim["name"],
                "event_time_et": claim["time_et"].strftime("%H:%M"),
                "window_minutes": BLACKOUT_WINDOW_MINUTES,
                "message": f"Trading paused: {claim['name']} release window",
            }

    return {"active": False}
