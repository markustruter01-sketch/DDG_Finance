"""
http_client.py — Rate-limited HTTP wrapper for crypto-signals service.
Tracks calls per source over a rolling 60-second window and sleeps when
the per-source budget would be exceeded.
"""
from __future__ import annotations

import time
from typing import Optional

import requests


class RateLimitedClient:
    def __init__(self) -> None:
        self._call_log: dict[str, list[float]] = {}

    def get(
        self,
        source: str,
        url: str,
        max_rpm: int,
        headers: Optional[dict] = None,
        timeout: int = 10,
    ) -> requests.Response:
        """GET with per-source rate limiting. Sleeps if budget is exhausted."""
        self._wait_if_needed(source, max_rpm)
        self._call_log.setdefault(source, []).append(time.time())
        return requests.get(url, headers=headers or {}, timeout=timeout)

    def _wait_if_needed(self, source: str, max_rpm: int) -> None:
        """Trim log to the last 60 s; if at capacity, sleep until a slot opens."""
        now = time.time()
        window_start = now - 60.0
        log = self._call_log.get(source, [])
        log = [t for t in log if t >= window_start]
        self._call_log[source] = log

        if len(log) >= max_rpm:
            oldest = log[0]
            sleep_for = 60.0 - (now - oldest) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            window_start = now - 60.0
            self._call_log[source] = [t for t in self._call_log[source] if t >= window_start]
