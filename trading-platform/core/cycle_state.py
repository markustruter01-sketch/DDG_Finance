"""
trading-platform/core/cycle_state.py  —  Stateful Cycle Memory
===============================================================
Maintains a rolling window of analysis-cycle outcomes and computes a
dynamic confidence multiplier that tightens when consecutive failures
accumulate.

The multiplier is intended to be read by callers before invoking the
LLM so they can scale conviction or kelly thresholds conservatively
after a run of bad cycles — without requiring human intervention.

Outcome taxonomy
----------------
  "success"  — cycle completed, allocations placed normally.
  "warning"  — cycle completed but with notable issues
               (fallback regime used, partial data, etc.)
  "failure"  — cycle aborted (data gap, LLM error, validation failed,
               kill-switch trip, etc.)

Multiplier calculation
----------------------
  start at 1.0
  subtract failure_step (default 0.10) for each "failure" in window
  subtract half failure_step for each "warning"
  clamp to [floor, 1.0]

  → 0 failures  → multiplier = 1.00
  → 3 failures  → multiplier = 0.70
  → 5 failures  → multiplier = 0.50 (floor)

State persistence
-----------------
  Serialised to trading-platform/logs/cycle_state.json so the bot
  retains memory across restarts.  Written atomically via a .tmp file.

Usage
-----
    from core.cycle_state import get_tracker

    tracker = get_tracker()               # module-level singleton
    tracker.record_outcome("success")     # after each pipeline cycle
    mult = tracker.get_confidence_multiplier()  # → 0.50 … 1.00
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Literal

from loguru import logger

OUTCOME = Literal["success", "warning", "failure"]

# ── Tunables ──────────────────────────────────────────────────────────────────
_DEFAULT_WINDOW   = 10     # number of recent cycles to remember
_FAILURE_STEP     = 0.10   # multiplier reduction per "failure"
_MULTIPLIER_FLOOR = 0.50   # never go below 50 %
_MULTIPLIER_CEIL  = 1.00

# State file lives in trading-platform/logs/ (created if absent)
_STATE_FILE = Path(__file__).parent.parent / "logs" / "cycle_state.json"


class CycleStateTracker:
    """
    Stateful rolling-window tracker for analysis-cycle outcomes.

    Parameters
    ----------
    window_size : int
        Number of recent outcomes to retain (default 10).
    failure_step : float
        Multiplier reduction per "failure" outcome (default 0.10).
    floor : float
        Minimum multiplier value (default 0.50).
    state_file : Path | None
        Persistence path. None disables file I/O (useful in tests).
    """

    def __init__(
        self,
        window_size:  int   = _DEFAULT_WINDOW,
        failure_step: float = _FAILURE_STEP,
        floor:        float = _MULTIPLIER_FLOOR,
        state_file:   Path | None = _STATE_FILE,
    ) -> None:
        self.window_size  = window_size
        self.failure_step = failure_step
        self.floor        = floor
        self.state_file   = state_file
        self._lock        = threading.Lock()
        self._history: deque[str] = deque(maxlen=window_size)
        self._load_state()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_outcome(self, status: OUTCOME) -> None:
        """
        Append the outcome of the most recently completed cycle.

        Parameters
        ----------
        status : "success" | "warning" | "failure"
        """
        with self._lock:
            self._history.append(status)
            mult = self._compute_multiplier_locked()
            logger.debug(
                f"CycleState | Recorded '{status}' "
                f"window={list(self._history)} multiplier={mult:.2f}"
            )
            self._save_state()

    def get_confidence_multiplier(self) -> float:
        """
        Return the current confidence multiplier in [floor, 1.0].

        1.00 → all recent cycles succeeded (fully confident)
        floor → system is consistently failing (maximum conservatism)
        """
        with self._lock:
            return self._compute_multiplier_locked()

    def recent_outcomes(self) -> list[str]:
        """Return a copy of the outcome window, oldest first."""
        with self._lock:
            return list(self._history)

    def failure_count(self) -> int:
        """Number of "failure" outcomes in the current window."""
        with self._lock:
            return sum(1 for o in self._history if o == "failure")

    def warning_count(self) -> int:
        """Number of "warning" outcomes in the current window."""
        with self._lock:
            return sum(1 for o in self._history if o == "warning")

    def reset(self) -> None:
        """Clear all history and return multiplier to 1.0."""
        with self._lock:
            self._history.clear()
            self._save_state()
        logger.info("CycleState | History cleared — multiplier reset to 1.00")

    def to_dict(self) -> dict:
        """Serialise current state for status endpoints or dashboards."""
        return {
            "recent_outcomes":       self.recent_outcomes(),
            "confidence_multiplier": self.get_confidence_multiplier(),
            "failure_count":         self.failure_count(),
            "warning_count":         self.warning_count(),
            "window_size":           self.window_size,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _compute_multiplier_locked(self) -> float:
        """Compute multiplier; caller must hold self._lock."""
        penalty = 0.0
        for outcome in self._history:
            if outcome == "failure":
                penalty += self.failure_step
            elif outcome == "warning":
                penalty += self.failure_step * 0.5
        return round(max(self.floor, _MULTIPLIER_CEIL - penalty), 4)

    def _save_state(self) -> None:
        if self.state_file is None:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "history":     list(self._history),
                "saved_at":    time.time(),
                "window_size": self.window_size,
            }
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self.state_file)
        except Exception as exc:
            logger.warning(f"CycleState | State save failed (non-fatal): {exc}")

    def _load_state(self) -> None:
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text())
            valid = {"success", "warning", "failure"}
            for outcome in payload.get("history", []):
                if outcome in valid:
                    self._history.append(outcome)
            logger.debug(
                f"CycleState | Loaded {len(self._history)} outcome(s) "
                f"from {self.state_file.name}"
            )
        except Exception as exc:
            logger.warning(
                f"CycleState | State load failed — starting fresh: {exc}"
            )


# ── Module-level singleton ─────────────────────────────────────────────────────
_tracker_lock    = threading.Lock()
_tracker_singleton: CycleStateTracker | None = None


def get_tracker() -> CycleStateTracker:
    """
    Return the module-level CycleStateTracker singleton.
    Creates the instance on first call (thread-safe).
    """
    global _tracker_singleton
    if _tracker_singleton is None:
        with _tracker_lock:
            if _tracker_singleton is None:
                _tracker_singleton = CycleStateTracker()
    return _tracker_singleton
