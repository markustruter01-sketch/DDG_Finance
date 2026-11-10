"""Outside heartbeat: tell a monitor that lives OUTSIDE Replit "I am alive".

Every other check (invariants, daily health message, kill switch) runs inside
the platform, so if the platform or Replit is down they all go silent together.
A dead-man's-switch service (e.g. healthchecks.io) expects a ping on a schedule
and alerts when the pings stop (Markus, 11 Nov 2026).

Two signals, each its own secret holding the service's ping URL:
  HEARTBEAT_URL_RUNNER  the bot runner's main loop, after its database heartbeat
                        was written (so a dead database also stops the pings);
  HEARTBEAT_URL_API     the trading API's scheduler, after each invariants run.
No secret set = nothing sent. Published deployment only. A ping never blocks
or raises: it runs on its own short-lived thread with a 5 s timeout, at most
once a minute per signal.
"""
from __future__ import annotations

import os
import threading
import time

MIN_SECONDS_BETWEEN_PINGS = 60
_last: dict[str, float] = {}


def _send(url: str) -> None:
    try:
        import httpx
        httpx.get(url, timeout=5.0)
    except Exception:
        pass  # the monitor alerts on silence; a failed ping needs no handling here


def ping(signal: str) -> bool:
    """signal: 'RUNNER' or 'API'. True when a ping was started."""
    url = os.environ.get(f"HEARTBEAT_URL_{signal}", "").strip()
    if not url.startswith("https://") or os.environ.get("REPLIT_DEPLOYMENT") != "1":
        return False
    now = time.monotonic()
    if now - _last.get(signal, -1e9) < MIN_SECONDS_BETWEEN_PINGS:
        return False
    _last[signal] = now
    threading.Thread(target=_send, args=(url,), name=f"heartbeat-{signal}", daemon=True).start()
    return True
