"""
penalty_tracker.py  —  Kraken REST API Leaky-Bucket Penalty Counter
=====================================================================
Kraken's REST API enforces a penalty-point system to prevent abuse.
Each call consumes points; the bucket refills at a fixed rate.

Kraken Starter-tier defaults:
  * Counter ceiling  : 15 points (MAX_POINTS)
  * Order placement  : +1 point  (PLACEMENT_COST)
  * Order cancel     : +2 points (CANCELLATION_COST)
  * Decay rate       : ~1 point per second (DECAY_RATE_PER_SEC)
  * Throttle at      : 80% of ceiling (THROTTLE_THRESHOLD)

Penalty state is persisted to ``penalty_state.json`` next to this file
so the counter survives a bot restart within the same session.

Usage
-----
    from penalty_tracker import PenaltyTracker

    tracker = PenaltyTracker()

    # Before placing an order
    if tracker.is_throttled():
        logger.info("Throttled — skipping order placement")
    else:
        exchange.create_market_order(...)
        tracker.record_placement()

    # After cancelling a stop order
    tracker.record_cancellation()

    # Status for dashboard / logs
    logger.debug(f"Penalty bucket: {tracker.current_points():.1f}/{tracker.MAX_POINTS} points")
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from loguru import logger


class PenaltyTracker:
    """
    Leaky-bucket penalty tracker for Kraken REST API rate limiting.

    The bucket fills when orders are placed or cancelled, and drains
    continuously at ``DECAY_RATE_PER_SEC`` points per wall-clock second.
    When the bucket exceeds ``THROTTLE_THRESHOLD × MAX_POINTS``, the bot
    enters read-only polling mode (no new entries or cancellations).
    """

    MAX_POINTS:         float = 15.0
    PLACEMENT_COST:     float = 1.0
    CANCELLATION_COST:  float = 2.0
    DECAY_RATE_PER_SEC: float = 1.0     # points drained per second
    THROTTLE_THRESHOLD: float = 0.80    # throttle at 80 % of ceiling

    def __init__(self, state_file: str | None = None) -> None:
        self._state_file: str = state_file or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "penalty_state.json"
        )
        self._points:    float = 0.0
        self._last_tick: float = time.monotonic()
        self._load()
        logger.debug(
            f"PenaltyTracker | Loaded — points={self._points:.1f}/{self.MAX_POINTS} "
            f"(throttle at {self.THROTTLE_THRESHOLD*self.MAX_POINTS:.1f})"
        )

    # ── Public interface ───────────────────────────────────────────────────────

    def record_placement(self) -> None:
        """Record a new order placement (+1 point)."""
        self._decay()
        self._points = min(self._points + self.PLACEMENT_COST, self.MAX_POINTS)
        logger.debug(
            f"PenaltyTracker | +placement → {self._points:.1f}/{self.MAX_POINTS}"
        )
        self._save()

    def record_cancellation(self) -> None:
        """Record an order cancellation (+2 points)."""
        self._decay()
        self._points = min(self._points + self.CANCELLATION_COST, self.MAX_POINTS)
        logger.debug(
            f"PenaltyTracker | +cancellation → {self._points:.1f}/{self.MAX_POINTS}"
        )
        self._save()

    def is_throttled(self) -> bool:
        """
        Return True when the penalty bucket exceeds the throttle threshold.

        When throttled the bot should skip new order placement and cancellation
        and poll only (read-only mode) until the bucket recovers.
        """
        self._decay()
        throttle_limit = self.THROTTLE_THRESHOLD * self.MAX_POINTS
        throttled = self._points >= throttle_limit
        if throttled:
            logger.debug(
                f"PenaltyTracker | THROTTLED — {self._points:.1f}/{self.MAX_POINTS} "
                f"(limit {throttle_limit:.1f}); waiting for bucket recovery"
            )
        return throttled

    def remaining_capacity(self) -> float:
        """
        Return the remaining capacity as a percentage [0, 100].

        100 % = empty bucket (no penalties accumulated).
        0 %   = bucket is full / at ceiling.
        """
        self._decay()
        used_pct = self._points / self.MAX_POINTS
        return round(max(0.0, (1.0 - used_pct)) * 100.0, 1)

    def current_points(self) -> float:
        """Return the current point total (after decay)."""
        self._decay()
        return round(self._points, 2)

    def reset(self) -> None:
        """Reset the bucket to zero (used in tests / after extended downtime)."""
        self._points    = 0.0
        self._last_tick = time.monotonic()
        self._save()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _decay(self) -> None:
        """Drain points proportional to elapsed wall-clock time."""
        now     = time.monotonic()
        elapsed = now - self._last_tick
        drain   = elapsed * self.DECAY_RATE_PER_SEC
        self._points    = max(0.0, self._points - drain)
        self._last_tick = now

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Persist current state to JSON (atomic write)."""
        state: dict[str, Any] = {
            "points":         self._points,
            "last_wall_time": time.time(),
        }
        tmp = self._state_file + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(state, f)
            os.replace(tmp, self._state_file)
        except Exception as exc:
            logger.warning(f"PenaltyTracker | Failed to persist state: {exc}")

    def _load(self) -> None:
        """
        Load persisted state from disk.

        Applies time-based decay since the last save so that the bucket
        reflects the actual elapsed time even across process restarts.
        """
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            saved_points     = float(state.get("points", 0.0))
            saved_wall_time  = float(state.get("last_wall_time", 0.0))
            elapsed_since    = max(0.0, time.time() - saved_wall_time)
            drain            = elapsed_since * self.DECAY_RATE_PER_SEC
            self._points     = max(0.0, saved_points - drain)
            self._last_tick  = time.monotonic()
        except Exception as exc:
            logger.warning(f"PenaltyTracker | Could not load state — starting fresh: {exc}")
            self._points    = 0.0
            self._last_tick = time.monotonic()

    def __repr__(self) -> str:
        self._decay()
        return (
            f"PenaltyTracker(points={self._points:.1f}/{self.MAX_POINTS}, "
            f"throttled={self.is_throttled()}, "
            f"capacity={self.remaining_capacity():.1f}%)"
        )
