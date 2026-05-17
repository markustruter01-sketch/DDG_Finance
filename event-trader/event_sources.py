"""Fetches events from 3 free sources:
1. Static JSON file (manually maintained)
2. CoinGecko /events endpoint
3. Hardcoded Fed FOMC schedule
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CS_PATH = os.path.normpath(os.path.join(_HERE, '..', 'crypto-signals'))
if _CS_PATH not in sys.path:
    sys.path.append(_CS_PATH)  # append, not insert(0), to avoid shadowing event-trader modules

from datetime import datetime, timedelta, timezone
from typing import List, Dict
from http_client import RateLimitedClient

# Constants from crypto-signals/config.py — inlined to avoid sys.path collision
# with trading-platform/config/__init__.py when both are on sys.path.
COINGECKO_BASE    = "https://api.coingecko.com/api/v3"
COINGECKO_MAX_RPM = 25

_http = RateLimitedClient()

# Hardcoded Fed FOMC meetings for 2026 (published years in advance)
FED_FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


def load_static_events() -> List[Dict]:
    """Load manually-maintained event JSON."""
    path = os.path.join(_HERE, "events_calendar.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    return data.get("static_events", [])


def fetch_coingecko_events() -> List[Dict]:
    """CoinGecko /events endpoint (free tier)."""
    try:
        url = f"{COINGECKO_BASE}/events"
        resp = _http.get("coingecko", url, COINGECKO_MAX_RPM)
        if resp.status_code != 200:
            return []
        data = resp.json().get("data", [])
        events = []
        for e in data:
            events.append({
                "id": f"cg_{e.get('id')}",
                "date": e.get("start_date"),
                "title": e.get("title"),
                "asset": (e.get("coins", [{}])[0] or {}).get("symbol", "BTC"),
                "category": e.get("type", "general"),
                "description": e.get("description", "")[:200],
            })
        return events
    except Exception:
        return []


def fed_fomc_events() -> List[Dict]:
    """Hardcoded Fed meeting dates."""
    events = []
    now = datetime.now(tz=timezone.utc)
    for date_str in FED_FOMC_2026:
        dt = datetime.fromisoformat(date_str + "T18:00:00+00:00")
        if dt < now:
            continue  # past event
        events.append({
            "id": f"fed_{date_str.replace('-', '')}",
            "date": dt.isoformat(),
            "title": f"FOMC {dt.strftime('%B %Y')} Rate Decision",
            "asset": "BTC",
            "category": "macro",
            "description": "Federal Reserve interest rate decision",
        })
    return events


def get_all_upcoming_events(days_ahead: int = 30) -> List[Dict]:
    """Aggregate events from all sources within next N days."""
    all_events = []
    all_events.extend(load_static_events())
    all_events.extend(fetch_coingecko_events())
    all_events.extend(fed_fomc_events())

    cutoff = datetime.utcnow() + timedelta(days=days_ahead)
    seen = set()
    upcoming = []
    for e in all_events:
        if not e.get("id") or not e.get("date"):
            continue
        if e["id"] in seen:
            continue
        try:
            event_dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            if event_dt.tzinfo:
                event_dt = event_dt.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if event_dt < datetime.utcnow() or event_dt > cutoff:
            continue
        seen.add(e["id"])
        upcoming.append(e)

    return sorted(upcoming, key=lambda x: x["date"])
