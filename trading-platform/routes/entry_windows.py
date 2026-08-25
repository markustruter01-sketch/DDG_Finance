"""
Server-owned ETF entry-window schedule for the fleet dashboard.

The runner owns execution. This route only exposes the configured UTC windows so
the dashboard can render a countdown without duplicating trading-time arithmetic.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter

router = APIRouter()


# Asia/EM match their strategy constants (ENTRY_HOUR_UTC=20,
# ENTRY_MIN_START=30, ENTRY_MIN_END=60). US Core has no fixed entry gate:
# its runner invokes the strategy once per configured hourly cycle.
ENTRY_WINDOWS = {
    "spy_qqq_trend": {
        "label": "US Core",
        "mode": "runner_interval",
        "entry_interval_seconds": 3600,
        "source": "bot2_spy_qqq runner: no fixed entry gate; scans on each hourly cycle",
    },
    "oracle": {
        "label": "Asia",
        "mode": "fixed_window",
        "start": time(20, 30),
        "end": time(21, 0),
        "source": "asia_trend_strategy ENTRY_HOUR_UTC / ENTRY_MIN_START / ENTRY_MIN_END",
    },
    "jerome_macro": {
        "label": "EM",
        "mode": "fixed_window",
        "start": time(20, 30),
        "end": time(21, 0),
        "source": "server-owned fixed UTC window: 20:30–21:00",
    },
}


def _next_window(start: time, end: time, now: datetime) -> tuple[datetime, datetime, bool]:
    """Return the current/next weekday window in UTC."""
    day = now.date()
    while True:
        window_start = datetime.combine(day, start, tzinfo=timezone.utc)
        window_end = datetime.combine(day, end, tzinfo=timezone.utc)
        if day.weekday() < 5:
            if window_start <= now < window_end:
                return window_start, window_end, True
            if now < window_start:
                return window_start, window_end, False
        day += timedelta(days=1)


@router.get("/fleet/entry-windows", tags=["Fleet"])
async def get_entry_windows() -> dict:
    """Next UTC entry window per active fleet bot, excluding weekends."""
    now = datetime.now(timezone.utc)
    windows = {}
    for bot_id, config in ENTRY_WINDOWS.items():
        if config["mode"] == "runner_interval":
            windows[bot_id] = {
                "label": config["label"],
                "timezone": "UTC",
                "mode": config["mode"],
                "is_open": False,
                "entry_interval_seconds": config["entry_interval_seconds"],
                "window_start_utc": None,
                "window_end_utc": None,
                "next_window_start_utc": None,
                "source": config["source"],
            }
            continue

        start, end, is_open = _next_window(config["start"], config["end"], now)
        windows[bot_id] = {
            "label": config["label"],
            "timezone": "UTC",
            "mode": config["mode"],
            "is_open": is_open,
            "window_start_utc": start.isoformat(),
            "window_end_utc": end.isoformat(),
            "next_window_start_utc": start.isoformat(),
            "source": config["source"],
        }
    return {
        "server_time_utc": now.isoformat(),
        "windows": windows,
    }