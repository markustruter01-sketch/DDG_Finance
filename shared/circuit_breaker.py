"""
shared/circuit_breaker.py  —  Flash-Crash Detector
===================================================
Wraps the stateless check_circuit_breaker() logic from kraken-bot/logic.py
in a stateful class that both bots can instantiate.

The detector looks at a rolling deque of (timestamp, price) observations
and triggers a pause if price drops more than *drop_threshold* within the
last *window_minutes* minutes.

Usage:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from shared.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(
        drop_threshold=0.10,   # 10 % drop triggers the breaker
        window_minutes=5,      # look back 5 minutes
        pause_hours=4,         # pause trading for 4 hours after trigger
    )

    # Called each cycle with the latest (utc_timestamp, price) tuple:
    cb.record(datetime.now(timezone.utc), current_price)

    if cb.is_triggered():
        logger.warning(f"Circuit breaker active until {cb.paused_until}")
    elif cb.should_trigger():
        cb.trip()              # manually trip after taking protective action

    cb.reset()                 # clear the pause (e.g. on bot restart)
    cb.to_dict()               # → dict for status.json / dashboard

The stateless helper function check_circuit_breaker() is also re-exported
here so callers that already have a populated deque can use it directly
without instantiating CircuitBreaker:

    from shared.circuit_breaker import check_circuit_breaker
    triggered = check_circuit_breaker(price_history, drop_threshold=0.10)
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional


# ── Stateless helper (mirrors kraken-bot/logic.py exactly) ───────────────────

def check_circuit_breaker(
    price_history: deque,
    drop_threshold: float = 0.10,
    window_minutes: int   = 5,
) -> bool:
    """
    Detect a flash crash by checking if price has dropped more than
    *drop_threshold* within the last *window_minutes* minutes.

    Parameters
    ----------
    price_history : collections.deque
        Deque of (datetime_utc, price) tuples, oldest first.

    drop_threshold : float
        Fractional price drop that triggers the breaker (default 10 %).

    window_minutes : int
        Rolling look-back window in minutes (default 5).

    Returns
    -------
    bool
        True  → flash crash detected — stop trading.
        False → no crash detected — safe to trade.

    Notes
    -----
    This is a pure function: it has no side effects and does not modify
    the deque.  The same logic lives in kraken-bot/logic.py; this copy
    is the canonical shared version.
    """
    if len(price_history) < 2:
        return False

    now_utc = datetime.now(tz=timezone.utc)
    current_price = price_history[-1][1]

    high_price_in_window: Optional[float] = None
    for ts, price in price_history:
        age_minutes = (now_utc - ts).total_seconds() / 60.0
        if age_minutes <= window_minutes:
            if high_price_in_window is None or price > high_price_in_window:
                high_price_in_window = price

    if high_price_in_window is None or high_price_in_window == 0:
        return False

    drop_pct = (high_price_in_window - current_price) / high_price_in_window
    return drop_pct >= drop_threshold


# ── Stateful wrapper ──────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Stateful flash-crash detector with automatic pause bookkeeping.

    The caller must call record() every cycle to feed price observations.
    Call check() every cycle; it returns True if trading should be paused.

    Parameters
    ----------
    drop_threshold : float
        Fractional price drop that triggers the breaker (default 0.10 = 10 %).

    window_minutes : int
        Rolling look-back window for detecting the drop (default 5).

    pause_hours : float
        How long to pause trading after the breaker fires (default 4 hours).

    history_maxlen : int
        Maximum number of price observations to keep in memory (default 200).
        At a 30-second cycle interval this covers ~100 minutes of history.
    """

    def __init__(
        self,
        drop_threshold:  float = 0.10,
        window_minutes:  int   = 5,
        pause_hours:     float = 4.0,
        history_maxlen:  int   = 200,
    ) -> None:
        self.drop_threshold  = drop_threshold
        self.window_minutes  = window_minutes
        self.pause_hours     = pause_hours
        self._history: deque = deque(maxlen=history_maxlen)
        self._paused_until: Optional[datetime] = None

    # ── Data ingestion ─────────────────────────────────────────────────────────

    def record(self, timestamp: datetime, price: float) -> None:
        """
        Add a (timestamp, price) observation to the rolling history.

        *timestamp* must be timezone-aware (UTC recommended).
        """
        if not isinstance(timestamp, datetime):
            raise TypeError(f"timestamp must be datetime, got {type(timestamp)}")
        self._history.append((timestamp, price))

    # ── Trigger logic ──────────────────────────────────────────────────────────

    def should_trigger(self) -> bool:
        """
        Return True if the current price history satisfies the crash
        detection rule, regardless of whether the breaker is already active.

        Use this to decide whether to call trip().
        """
        return check_circuit_breaker(
            price_history=self._history,
            drop_threshold=self.drop_threshold,
            window_minutes=self.window_minutes,
        )

    def trip(self, at: Optional[datetime] = None) -> datetime:
        """
        Manually activate the circuit breaker pause.

        Parameters
        ----------
        at : datetime | None
            The time at which the breaker trips (default: now UTC).

        Returns
        -------
        datetime
            The UTC time at which the pause expires.
        """
        now = at or datetime.now(tz=timezone.utc)
        self._paused_until = now + timedelta(hours=self.pause_hours)
        return self._paused_until

    def check_and_trip(self) -> bool:
        """
        Combined check-and-trip: calls should_trigger(); if True, calls trip()
        and returns True.  Idempotent while already paused.

        Returns
        -------
        bool
            True if the breaker is active (just tripped or already paused).
        """
        if self.is_triggered():
            return True
        if self.should_trigger():
            self.trip()
            return True
        return False

    def is_triggered(self) -> bool:
        """
        Return True if the breaker is currently in its pause window.
        Returns False once the pause window expires.
        """
        if self._paused_until is None:
            return False
        return datetime.now(tz=timezone.utc) < self._paused_until

    def reset(self) -> None:
        """Clear the pause immediately (e.g. manual override from dashboard)."""
        self._paused_until = None

    # ── Introspection ──────────────────────────────────────────────────────────

    @property
    def paused_until(self) -> Optional[datetime]:
        """The UTC datetime when the pause expires, or None if not paused."""
        return self._paused_until if self.is_triggered() else None

    def minutes_remaining(self) -> float:
        """
        Return the number of minutes left in the current pause.
        Returns 0.0 if the breaker is not active.
        """
        if not self.is_triggered():
            return 0.0
        delta = (self._paused_until - datetime.now(tz=timezone.utc)).total_seconds()
        return round(max(delta / 60.0, 0.0), 1)

    def observation_count(self) -> int:
        """Number of price observations currently in the rolling history."""
        return len(self._history)

    def to_dict(self) -> dict:
        """
        Serialise the current state for status.json / admin endpoint.
        """
        active = self.is_triggered()
        return {
            "active":          active,
            "paused_until":    self._paused_until.isoformat() if active else None,
            "minutes_remaining": self.minutes_remaining() if active else 0.0,
            "drop_threshold_pct": round(self.drop_threshold * 100, 1),
            "window_minutes":  self.window_minutes,
            "pause_hours":     self.pause_hours,
            "observation_count": self.observation_count(),
        }

    def __repr__(self) -> str:
        state = f"paused until {self._paused_until.isoformat()}" if self.is_triggered() else "inactive"
        return (
            f"CircuitBreaker(threshold={self.drop_threshold:.0%}, "
            f"window={self.window_minutes}min, pause={self.pause_hours}h, "
            f"state={state})"
        )
