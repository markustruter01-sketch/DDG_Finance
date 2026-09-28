"""Regression tests for restart-proof regional entry-window scheduling."""

from __future__ import annotations

import importlib.util
import pathlib
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


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


class RunnerPortfolioCycleTests(unittest.TestCase):
    BOT_ID = "spy_qqq_trend"

    def _run_cycles(self, profile, portfolio_writer, cycle_limit):
        shutdown_event = Event()
        strategy_calls = []
        order_calls = []
        status_updates = []
        liveness_writes = []
        portfolio_events = []
        logger = MagicMock()
        sleep_calls = 0
        clock = [0.0]

        def strategy_cycle(**_kwargs):
            strategy_calls.append(self.BOT_ID)
            order_calls.append("submit_order")

        def update_status(_bot_id, **fields):
            status_updates.append(fields)

        def record_cycle_liveness(*args, **kwargs):
            liveness_writes.append((args, kwargs))

        def stop_after_cycles(_seconds):
            nonlocal sleep_calls
            clock[0] += _seconds
            sleep_calls += 1
            if sleep_calls >= cycle_limit:
                shutdown_event.set()

        def tracked_portfolio_writer(*args, **kwargs):
            portfolio_events.append("portfolio")
            return portfolio_writer(*args, **kwargs)

        profile = {
            **profile,
            "LOOP_SLEEP_SECONDS": 1,
            "db_id": "runner-test-db",
        }
        strategy_module = SimpleNamespace(cycle=strategy_cycle)
        patches = [
            patch.multiple(
                runner,
                _runner_can_trade=True,
                _pause_alignment_ok=True,
                _owned_lock_bot_ids={self.BOT_ID},
                _shutdown_event=shutdown_event,
                _heartbeat_ok=True,
            ),
            patch.object(runner, "_canonical_lock_bot_id", side_effect=lambda bot_id: bot_id),
            patch.object(runner, "_profile_for_bot", return_value=profile),
            patch.object(runner.importlib, "import_module", return_value=strategy_module),
            patch.object(runner, "_refresh_bot_lock", return_value=True),
            patch.object(runner, "_bs_is_paused", return_value=False),
            patch.object(runner, "_bs_normalise", side_effect=lambda bot_id: bot_id),
            patch.object(runner, "_bs_touch"),
            patch.object(runner, "_update_status", side_effect=update_status),
            patch.object(runner, "_record_cycle_liveness", side_effect=record_cycle_liveness),
            patch.object(runner, "_is_unrecorded_window_cycle", return_value=False),
            patch.object(runner, "_next_window_aligned_cycle", return_value=None),
            patch.object(runner, "_write_portfolio_from_alpaca", side_effect=tracked_portfolio_writer),
            patch.object(runner, "logger", logger),
            patch.object(runner.time, "time", side_effect=lambda: clock[0]),
            patch.object(runner.time, "sleep", side_effect=stop_after_cycles),
        ]

        with ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            runner._run_bot_loop(self.BOT_ID, "runner_test_strategy", "cycle")

        return {
            "strategy_calls": strategy_calls,
            "order_calls": order_calls,
            "status_updates": status_updates,
            "liveness_writes": liveness_writes,
            "portfolio_events": portfolio_events,
            "logger": logger,
        }

    def test_paused_bot_refreshes_portfolio_each_cycle_without_strategy_or_orders(self):
        writer = MagicMock(return_value=True)

        result = self._run_cycles(
            {"BOT_PAUSED": True},
            writer,
            cycle_limit=2,
        )

        self.assertEqual(writer.call_count, 2)
        self.assertEqual(result["portfolio_events"], ["portfolio", "portfolio"])
        self.assertEqual(result["strategy_calls"], [])
        self.assertEqual(result["order_calls"], [])
        self.assertEqual(
            [fields["status"] for fields in result["status_updates"]].count("paused"),
            2,
        )
        self.assertEqual(
            [args[4] for args, _kwargs in result["liveness_writes"]],
            ["paused", "paused"],
        )

    def test_active_bot_keeps_strategy_then_portfolio_cycle_flow(self):
        writer = MagicMock(return_value=True)

        result = self._run_cycles(
            {"BOT_PAUSED": False},
            writer,
            cycle_limit=1,
        )

        self.assertEqual(result["strategy_calls"], [self.BOT_ID])
        self.assertEqual(result["order_calls"], ["submit_order"])
        self.assertEqual(result["portfolio_events"], ["portfolio"])
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(result["liveness_writes"][0][0][4], "success")
        self.assertTrue(result["liveness_writes"][0][1]["success"])

    def test_paused_portfolio_failure_logs_error_without_changing_cycle_health(self):
        writer = MagicMock(
            side_effect=[
                False,
                RuntimeError("portfolio write unavailable"),
            ]
        )

        result = self._run_cycles(
            {"BOT_PAUSED": True},
            writer,
            cycle_limit=2,
        )

        self.assertEqual(writer.call_count, 2)
        self.assertEqual(result["strategy_calls"], [])
        self.assertEqual(result["order_calls"], [])
        self.assertEqual(
            [args[4] for args, _kwargs in result["liveness_writes"]],
            ["paused", "paused"],
        )
        self.assertTrue(
            all(
                kwargs.get("consecutive_failures") == 0
                and not kwargs.get("success", False)
                and "last_error" not in kwargs
                for _args, kwargs in result["liveness_writes"]
            )
        )
        self.assertNotIn(
            "error",
            [fields["status"] for fields in result["status_updates"]],
        )
        error_messages = [
            str(call.args[0])
            for call in result["logger"].error.call_args_list
        ]
        self.assertEqual(len(error_messages), 2)
        self.assertTrue(all("paused portfolio refresh" in message for message in error_messages))


if __name__ == "__main__":
    unittest.main()