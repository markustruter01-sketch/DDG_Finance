"""Regression tests for restart-proof regional entry-window scheduling."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest
from datetime import datetime, timezone


_RUNNER_PATH = pathlib.Path(__file__).with_name("runner.py")
_SPEC = importlib.util.spec_from_file_location("runner_window_alignment", _RUNNER_PATH)
assert _SPEC and _SPEC.loader
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


REGIONAL_PROFILE = {
    "display_name": "Regional test bot",
    "ENTRY_WINDOW_START_UTC": (20, 30),
    "ENTRY_WINDOW_DURATION_MINUTES": 30,
}
US_CORE_PROFILE = {"display_name": "US Core"}


def utc(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 20, hour, minute, tzinfo=timezone.utc)


class WindowAlignedCycleTests(unittest.TestCase):
    def test_restart_at_2014_schedules_2030_entry_cycle(self) -> None:
        now = utc(20, 14)

        scheduled = runner._next_window_aligned_cycle(REGIONAL_PROFILE, None, now)

        self.assertEqual(scheduled, utc(20, 30))
        self.assertEqual((scheduled - now).total_seconds(), 16 * 60)

    def test_cycle_before_window_is_followed_by_window_cycle(self) -> None:
        """An hourly run at 20:29 must be followed by a 20:30 run."""
        normal_cycle_end = utc(20, 29)

        scheduled = runner._next_window_aligned_cycle(
            REGIONAL_PROFILE, None, normal_cycle_end
        )

        self.assertEqual(scheduled, utc(20, 30))

    def test_restart_during_window_runs_immediately_once(self) -> None:
        now = utc(20, 43)

        scheduled = runner._next_window_aligned_cycle(REGIONAL_PROFILE, None, now)

        self.assertEqual(scheduled, now)
        self.assertTrue(runner._is_unrecorded_window_cycle(REGIONAL_PROFILE, None, now))
        self.assertFalse(
            runner._is_unrecorded_window_cycle(REGIONAL_PROFILE, now.date(), now)
        )

    def test_after_window_defers_to_tomorrow(self) -> None:
        scheduled = runner._next_window_aligned_cycle(
            REGIONAL_PROFILE, None, utc(21, 14)
        )

        self.assertEqual(scheduled, utc(20, 30).replace(day=21))

    def test_us_core_does_not_get_regional_window_schedule(self) -> None:
        now = utc(20, 14)

        self.assertIsNone(runner._next_window_aligned_cycle(US_CORE_PROFILE, None, now))
        self.assertFalse(runner._is_unrecorded_window_cycle(US_CORE_PROFILE, None, now))


if __name__ == "__main__":
    unittest.main()