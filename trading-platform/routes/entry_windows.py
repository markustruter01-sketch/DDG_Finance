"""
Server-owned ETF entry-window schedule for the fleet dashboard.

The runner owns execution. This route only exposes the configured UTC windows so
the dashboard can render a countdown without duplicating trading-time arithmetic.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from loguru import logger
from core.bot_config import load_bot_profiles
from core.bot_registry import display_label

router = APIRouter()


def _load_bot_profiles() -> dict[str, dict[str, Any]]:
    """Compatibility wrapper for the shared runner config loader."""
    return load_bot_profiles()


def _profile_window(profile: dict[str, Any]) -> tuple[time, time]:
    configured_start = profile.get("ENTRY_WINDOW_START_UTC")
    if not configured_start:
        raise ValueError("profile has no fixed entry window")
    hour, minute = (int(value) for value in configured_start)
    start = time(hour, minute)
    duration = int(profile.get("ENTRY_WINDOW_DURATION_MINUTES", 30))
    end_minutes = hour * 60 + minute + duration
    if end_minutes > 24 * 60:
        raise ValueError("entry window crosses midnight")
    return start, time(end_minutes // 60, end_minutes % 60)


def _build_entry_windows() -> dict[str, dict[str, Any]]:
    profiles = _load_bot_profiles()
    oracle_start, oracle_end = _profile_window(profiles["oracle"])
    return {
    "spy_qqq_trend": {
        "label": display_label("spy_qqq_trend"),
        "mode": "runner_interval",
        "entry_interval_seconds": 3600,
        "source": "bot2_spy_qqq runner: no fixed entry gate; scans on each hourly cycle",
    },
    "oracle": {
        "label": display_label("oracle"),
        "mode": "fixed_window",
        "start": oracle_start,
        "end": oracle_end,
        "source": "kraken-bot/config.py BOT_PROFILES['oracle']",
    },
    "jerome_macro": {
        "label": display_label("jerome_macro"),
        "mode": "event_driven",
        "source": (
            "bot3_hard_assets_strategy: initial entry, partial-entry recovery, "
            "and quarterly rebalance dates; no fixed daily window"
        ),
    },
    }


ENTRY_WINDOWS = _build_entry_windows()


def assert_entry_window_alignment() -> bool:
    """Log a critical report/config mismatch without affecting trading."""
    aligned = True
    try:
        profiles = _load_bot_profiles()
        expected_start, expected_end = _profile_window(profiles["oracle"])
        reported = ENTRY_WINDOWS["oracle"]
        if reported.get("start") != expected_start or reported.get("end") != expected_end:
            aligned = False
            logger.critical(
                "Entry-window alignment disagreement | bot=oracle "
                f"reported={reported.get('start')}–{reported.get('end')} "
                f"config={expected_start}–{expected_end}"
            )

        if ENTRY_WINDOWS["jerome_macro"].get("mode") != "event_driven":
            aligned = False
            logger.critical(
                "Entry-window alignment disagreement | bot=jerome_macro "
                "reported a fixed window although Bot 3 is event-driven"
            )
    except Exception as exc:
        aligned = False
        logger.critical(f"Entry-window alignment check failed: {exc}")
    logger.info(
        f"Entry-window alignment assertion: {'PASS' if aligned else 'FAIL'}"
    )
    return aligned


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
        if config["mode"] == "event_driven":
            windows[bot_id] = {
                "label": config["label"],
                "timezone": "UTC",
                "mode": config["mode"],
                "is_open": False,
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