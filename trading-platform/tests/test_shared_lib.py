"""
Tests for the shared/ core infrastructure library.

Tests:
  RiskProfile   — construction, ring-fence math, validation, breach detection
  ExitBracket   — long/short exit levels, ATR-based stops, R:R ratio
  CircuitBreaker — stateless helper + stateful class, trip/reset/expire
"""

import sys
import os
import math
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone

# ── Ensure repo root is on the path ───────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..", "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.risk_profile import RiskProfile
from shared.exit_bracket import ExitBracket, compute_exit_levels
from shared.circuit_breaker import CircuitBreaker, check_circuit_breaker


# ══════════════════════════════════════════════════════════════════════════════
# RiskProfile
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskProfile(unittest.TestCase):

    def _make(self, equity=100_000, deployed=0.0, **kwargs):
        defaults = dict(
            ring_fenced_pct=0.60,
            deployable_pct=0.40,
            max_position_pct=0.15,
            daily_loss_limit_pct=0.05,
            reserve_pct=0.18,
            name="test",
        )
        defaults.update(kwargs)
        return RiskProfile(total_equity=equity, deployed_usd=deployed, **defaults)

    def test_construction_valid(self):
        rp = self._make()
        self.assertEqual(rp.total_equity, 100_000)
        self.assertEqual(rp.ring_fenced_pct, 0.60)

    def test_ring_fenced_usd(self):
        rp = self._make(equity=100_000)
        self.assertAlmostEqual(rp.ring_fenced_usd(), 60_000.0)

    def test_deployable_ceiling_usd(self):
        rp = self._make(equity=100_000)
        self.assertAlmostEqual(rp.deployable_ceiling_usd(), 40_000.0)

    def test_active_ceiling_usd(self):
        # deployable=40k, reserve=18% → active = 40k × 0.82 = 32_800
        rp = self._make(equity=100_000)
        self.assertAlmostEqual(rp.active_ceiling_usd(), 32_800.0)

    def test_max_single_position_usd(self):
        rp = self._make(equity=100_000)
        self.assertAlmostEqual(rp.max_single_position_usd(), 15_000.0)

    def test_daily_loss_limit_usd(self):
        rp = self._make(equity=100_000)
        self.assertAlmostEqual(rp.daily_loss_limit_usd(), 5_000.0)

    def test_reserve_buffer_positive(self):
        rp = self._make(equity=100_000, deployed=20_000)
        # active_ceiling = 32_800, deployed = 20_000 → buffer = 12_800
        self.assertAlmostEqual(rp.reserve_buffer_usd(), 12_800.0)

    def test_reserve_buffer_negative_breach(self):
        rp = self._make(equity=100_000, deployed=40_000)
        # deployed (40k) > active_ceiling (32.8k) → negative buffer
        self.assertLess(rp.reserve_buffer_usd(), 0)

    def test_deployed_pct(self):
        rp = self._make(equity=100_000, deployed=16_400)
        # 16_400 / 32_800 = 50 %
        self.assertAlmostEqual(rp.deployed_pct(), 50.0, places=1)

    def test_deployed_pct_zero_when_no_equity(self):
        rp = self._make(equity=0, deployed=0)
        self.assertEqual(rp.deployed_pct(), 0.0)

    def test_validate_no_breach(self):
        rp = self._make(equity=100_000, deployed=10_000)
        rp.validate()  # Should not raise

    def test_validate_breach_raises(self):
        rp = self._make(equity=100_000, deployed=40_000)
        with self.assertRaises(ValueError):
            rp.validate()

    def test_is_breached_false(self):
        rp = self._make(equity=100_000, deployed=10_000)
        self.assertFalse(rp.is_breached())

    def test_is_breached_true(self):
        rp = self._make(equity=100_000, deployed=40_000)
        self.assertTrue(rp.is_breached())

    def test_invalid_ring_fence_sum(self):
        with self.assertRaises(ValueError):
            RiskProfile(
                total_equity=100_000,
                ring_fenced_pct=0.70,
                deployable_pct=0.40,   # 0.70 + 0.40 ≠ 1.0
            )

    def test_negative_equity_raises(self):
        with self.assertRaises(ValueError):
            RiskProfile(total_equity=-1)

    def test_to_dict_keys(self):
        rp = self._make(equity=50_000, deployed=5_000)
        d = rp.to_dict()
        for key in (
            "name", "total_equity_usd", "deployed_usd",
            "ring_fenced_pct", "ring_fenced_usd",
            "deployable_ceiling_pct", "deployable_ceiling_usd",
            "reserve_pct", "active_ceiling_usd",
            "reserve_buffer_usd", "deployed_pct_of_ceiling",
            "max_single_position_usd", "daily_loss_limit_usd",
            "is_breached",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_repr(self):
        rp = self._make()
        self.assertIn("RiskProfile", repr(rp))

    def test_alpaca_profile_values(self):
        """Verify the exact Alpaca defaults used in the admin endpoint."""
        rp = RiskProfile(
            total_equity=100_000,
            deployed_usd=0.0,
            ring_fenced_pct=0.60,
            deployable_pct=0.40,
            max_position_pct=0.15,
            daily_loss_limit_pct=0.05,
            reserve_pct=0.18,
            name="alpaca",
        )
        self.assertAlmostEqual(rp.ring_fenced_usd(), 60_000)
        self.assertAlmostEqual(rp.deployable_ceiling_usd(), 40_000)
        self.assertAlmostEqual(rp.active_ceiling_usd(), 32_800)
        self.assertAlmostEqual(rp.max_single_position_usd(), 15_000)

    def test_kraken_profile_values(self):
        """Verify Kraken-style profile (20% cash reserve, 30% max position)."""
        rp = RiskProfile(
            total_equity=100_000,
            deployed_usd=0.0,
            ring_fenced_pct=0.60,
            deployable_pct=0.40,
            max_position_pct=0.30,
            daily_loss_limit_pct=0.05,
            reserve_pct=0.20,
            name="kraken",
        )
        self.assertAlmostEqual(rp.active_ceiling_usd(), 32_000)
        self.assertAlmostEqual(rp.max_single_position_usd(), 30_000)


# ══════════════════════════════════════════════════════════════════════════════
# ExitBracket
# ══════════════════════════════════════════════════════════════════════════════

class TestExitBracket(unittest.TestCase):

    def test_long_fixed_stop(self):
        b = ExitBracket(entry_price=100.0, direction="long",
                        stop_loss_pct=0.02, take_profit_pct=0.06, trail_pct=0.05)
        sl, tp, trail = b.compute()
        self.assertAlmostEqual(sl,    98.0,   places=4)
        self.assertAlmostEqual(tp,   106.0,   places=4)
        self.assertAlmostEqual(trail, 105.0,  places=4)

    def test_short_fixed_stop(self):
        b = ExitBracket(entry_price=100.0, direction="short",
                        stop_loss_pct=0.02, take_profit_pct=0.06, trail_pct=0.05)
        sl, tp, trail = b.compute()
        self.assertAlmostEqual(sl,   102.0,   places=4)
        self.assertAlmostEqual(tp,    94.0,   places=4)
        self.assertAlmostEqual(trail,  95.0,  places=4)

    def test_long_atr_stop(self):
        # ATR=500, multiplier=2.0 → stop = 50000 - 1000 = 49000
        b = ExitBracket(entry_price=50_000.0, direction="long",
                        stop_loss_pct=0.02, take_profit_pct=0.06, trail_pct=0.05,
                        atr=500.0, atr_multiplier=2.0)
        sl, tp, trail = b.compute()
        self.assertAlmostEqual(sl, 49_000.0, places=2)
        # TP and trail still use fixed pct
        self.assertAlmostEqual(tp,    53_000.0, places=2)
        self.assertAlmostEqual(trail, 52_500.0, places=2)

    def test_short_atr_stop(self):
        # ATR=1000, multiplier=1.5 → stop = 50000 + 1500 = 51500
        b = ExitBracket(entry_price=50_000.0, direction="short",
                        stop_loss_pct=0.02, take_profit_pct=0.06, trail_pct=0.05,
                        atr=1000.0, atr_multiplier=1.5)
        sl, tp, trail = b.compute()
        self.assertAlmostEqual(sl, 51_500.0, places=2)

    def test_atr_zero_fallback_to_fixed(self):
        b = ExitBracket(entry_price=100.0, direction="long",
                        stop_loss_pct=0.02, atr=0.0)
        sl, _, _ = b.compute()
        self.assertAlmostEqual(sl, 98.0, places=4)

    def test_risk_reward_ratio(self):
        b = ExitBracket(entry_price=100.0, direction="long",
                        stop_loss_pct=0.02, take_profit_pct=0.06)
        self.assertAlmostEqual(b.risk_reward_ratio(), 3.0)

    def test_invalid_entry_price(self):
        with self.assertRaises(ValueError):
            ExitBracket(entry_price=0.0, direction="long")

    def test_invalid_direction(self):
        with self.assertRaises(ValueError):
            ExitBracket(entry_price=100.0, direction="sideways")

    def test_to_dict_keys(self):
        b = ExitBracket(entry_price=100.0, direction="long")
        d = b.to_dict()
        for key in ("stop_loss_price", "take_profit_price", "trail_activation_price",
                    "risk_reward_ratio", "entry_price", "direction"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_compute_exit_levels_convenience(self):
        sl, tp, trail = compute_exit_levels(
            entry_price=100.0, direction="long",
            stop_loss_pct=0.02, take_profit_pct=0.06, trail_pct=0.05
        )
        self.assertAlmostEqual(sl,    98.0,  places=4)
        self.assertAlmostEqual(tp,   106.0,  places=4)
        self.assertAlmostEqual(trail, 105.0, places=4)

    def test_compute_exit_levels_with_risk_profile(self):
        """risk_profile is accepted but does NOT change computation (pure metadata)."""
        rp = RiskProfile(
            total_equity=100_000,
            ring_fenced_pct=0.60,
            deployable_pct=0.40,
            max_position_pct=0.15,
            name="test",
        )
        # risk_profile is passed but stop_loss_pct=0.02 is used unchanged
        sl, tp, trail = compute_exit_levels(
            entry_price=100.0, direction="long",
            risk_profile=rp,
            stop_loss_pct=0.02,
            take_profit_pct=0.06, trail_pct=0.05,
        )
        self.assertAlmostEqual(sl, 98.0, places=4)   # 100 × (1 - 0.02)
        self.assertAlmostEqual(tp, 106.0, places=4)
        self.assertAlmostEqual(trail, 105.0, places=4)

    def test_compute_exit_levels_risk_profile_does_not_override_stop_pct(self):
        """Passing risk_profile does NOT override the explicit stop_loss_pct."""
        rp = RiskProfile(
            total_equity=100_000,
            ring_fenced_pct=0.60,
            deployable_pct=0.40,
            max_position_pct=0.20,
            name="test",
        )
        sl, _, _ = compute_exit_levels(
            entry_price=100.0, direction="long",
            risk_profile=rp,
            stop_loss_pct=0.03,  # explicit; must be honoured
        )
        self.assertAlmostEqual(sl, 100.0 * (1.0 - 0.03), places=4)

    def test_repr(self):
        b = ExitBracket(entry_price=100.0, direction="long")
        self.assertIn("ExitBracket", repr(b))

    def test_leveraged_atr_multiplier(self):
        # Leveraged ETF gets 1.5× — tighter stop
        b_std  = ExitBracket(entry_price=100.0, direction="long",
                              atr=2.0, atr_multiplier=2.0)
        b_letf = ExitBracket(entry_price=100.0, direction="long",
                              atr=2.0, atr_multiplier=1.5)
        sl_std,  _, _ = b_std.compute()
        sl_letf, _, _ = b_letf.compute()
        # Tighter stop (1.5×) is HIGHER (closer to entry) for a long
        self.assertGreater(sl_letf, sl_std)


# ══════════════════════════════════════════════════════════════════════════════
# CircuitBreaker — stateless function
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckCircuitBreaker(unittest.TestCase):

    def _make_history(self, prices, minutes_apart=1):
        """Build a deque of (datetime, price) tuples."""
        now = datetime.now(tz=timezone.utc)
        history = deque(maxlen=200)
        for i, price in enumerate(prices):
            ts = now - timedelta(minutes=(len(prices) - 1 - i) * minutes_apart)
            history.append((ts, price))
        return history

    def test_no_crash(self):
        history = self._make_history([100, 101, 102, 103, 104])
        self.assertFalse(check_circuit_breaker(history))

    def test_small_drop_no_trigger(self):
        # 5% drop — below 10% threshold
        history = self._make_history([100, 95])
        self.assertFalse(check_circuit_breaker(history, drop_threshold=0.10))

    def test_exact_threshold_triggers(self):
        # Exactly 10% drop within window
        history = self._make_history([100, 90])
        self.assertTrue(check_circuit_breaker(history, drop_threshold=0.10))

    def test_drop_exceeds_threshold_triggers(self):
        # 15% drop
        history = self._make_history([100, 85])
        self.assertTrue(check_circuit_breaker(history, drop_threshold=0.10))

    def test_too_few_points_safe(self):
        history = deque([(datetime.now(tz=timezone.utc), 100.0)])
        self.assertFalse(check_circuit_breaker(history))

    def test_empty_history_safe(self):
        self.assertFalse(check_circuit_breaker(deque()))

    def test_old_high_outside_window_ignored(self):
        # High price is 10 minutes ago, window is 5 minutes — should NOT trigger
        now = datetime.now(tz=timezone.utc)
        history = deque(maxlen=200)
        history.append((now - timedelta(minutes=10), 200.0))  # old high — outside window
        history.append((now - timedelta(minutes=1),  100.0))  # recent price
        # Only the recent price is in the 5-min window, no comparison possible → safe
        self.assertFalse(check_circuit_breaker(history, drop_threshold=0.10, window_minutes=5))


# ══════════════════════════════════════════════════════════════════════════════
# CircuitBreaker — stateful class
# ══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerClass(unittest.TestCase):

    def test_not_triggered_initially(self):
        cb = CircuitBreaker()
        self.assertFalse(cb.is_triggered())

    def test_trip_sets_pause(self):
        cb = CircuitBreaker(pause_hours=4.0)
        paused_until = cb.trip()
        self.assertTrue(cb.is_triggered())
        expected = datetime.now(tz=timezone.utc) + timedelta(hours=4)
        self.assertAlmostEqual(
            paused_until.timestamp(), expected.timestamp(), delta=2
        )

    def test_reset_clears_pause(self):
        cb = CircuitBreaker()
        cb.trip()
        self.assertTrue(cb.is_triggered())
        cb.reset()
        self.assertFalse(cb.is_triggered())

    def test_paused_until_none_when_not_triggered(self):
        cb = CircuitBreaker()
        self.assertIsNone(cb.paused_until)

    def test_paused_until_set_when_triggered(self):
        cb = CircuitBreaker()
        cb.trip()
        self.assertIsNotNone(cb.paused_until)

    def test_minutes_remaining_zero_when_inactive(self):
        cb = CircuitBreaker()
        self.assertEqual(cb.minutes_remaining(), 0.0)

    def test_minutes_remaining_positive_when_active(self):
        cb = CircuitBreaker(pause_hours=2.0)
        cb.trip()
        self.assertGreater(cb.minutes_remaining(), 0.0)
        self.assertLessEqual(cb.minutes_remaining(), 120.0)

    def test_record_and_observation_count(self):
        cb = CircuitBreaker()
        now = datetime.now(tz=timezone.utc)
        for i in range(5):
            cb.record(now + timedelta(seconds=i), 100.0 + i)
        self.assertEqual(cb.observation_count(), 5)

    def test_should_trigger_true_on_crash(self):
        cb = CircuitBreaker(drop_threshold=0.10, window_minutes=10)
        now = datetime.now(tz=timezone.utc)
        cb.record(now - timedelta(minutes=5), 100.0)
        cb.record(now,                         85.0)  # 15% drop
        self.assertTrue(cb.should_trigger())

    def test_should_trigger_false_no_crash(self):
        cb = CircuitBreaker(drop_threshold=0.10, window_minutes=10)
        now = datetime.now(tz=timezone.utc)
        cb.record(now - timedelta(minutes=5), 100.0)
        cb.record(now,                        98.0)   # 2% drop — fine
        self.assertFalse(cb.should_trigger())

    def test_check_and_trip(self):
        cb = CircuitBreaker(drop_threshold=0.10, window_minutes=10)
        now = datetime.now(tz=timezone.utc)
        cb.record(now - timedelta(minutes=3), 100.0)
        cb.record(now,                         80.0)   # 20% drop
        result = cb.check_and_trip()
        self.assertTrue(result)
        self.assertTrue(cb.is_triggered())

    def test_check_and_trip_no_trigger(self):
        cb = CircuitBreaker(drop_threshold=0.10)
        result = cb.check_and_trip()
        self.assertFalse(result)

    def test_check_and_trip_idempotent_while_paused(self):
        cb = CircuitBreaker()
        cb.trip()
        original_until = cb._paused_until
        cb.check_and_trip()   # already paused — should not re-trip
        self.assertEqual(cb._paused_until, original_until)

    def test_to_dict_inactive(self):
        cb = CircuitBreaker(drop_threshold=0.10, window_minutes=5, pause_hours=4)
        d = cb.to_dict()
        self.assertFalse(d["active"])
        self.assertIsNone(d["paused_until"])
        self.assertEqual(d["drop_threshold_pct"], 10.0)

    def test_to_dict_active(self):
        cb = CircuitBreaker()
        cb.trip()
        d = cb.to_dict()
        self.assertTrue(d["active"])
        self.assertIsNotNone(d["paused_until"])

    def test_repr(self):
        cb = CircuitBreaker()
        self.assertIn("CircuitBreaker", repr(cb))

    def test_record_invalid_type_raises(self):
        cb = CircuitBreaker()
        with self.assertRaises(TypeError):
            cb.record("not-a-datetime", 100.0)

    def test_pause_expires(self):
        cb = CircuitBreaker(pause_hours=0.0)   # 0-hour pause
        cb.trip()
        # Pause of 0 hours should already be expired
        import time as _time
        _time.sleep(0.01)
        self.assertFalse(cb.is_triggered())


# ══════════════════════════════════════════════════════════════════════════════
# Integration — shared/ importable from both bot working directories
# ══════════════════════════════════════════════════════════════════════════════

class TestSharedImport(unittest.TestCase):

    def test_import_from_repo_root(self):
        """Verify the shared package can be imported via the repo root path."""
        import importlib
        spec = importlib.util.find_spec("shared")
        self.assertIsNotNone(spec, "shared package not found on sys.path")

    def test_all_exports_available(self):
        from shared import RiskProfile, ExitBracket, CircuitBreaker
        self.assertTrue(callable(RiskProfile))
        self.assertTrue(callable(ExitBracket))
        self.assertTrue(callable(CircuitBreaker))


# ══════════════════════════════════════════════════════════════════════════════
# Delegation — kraken-bot/logic.py delegates to shared/circuit_breaker.py
# ══════════════════════════════════════════════════════════════════════════════

class TestKrakenLogicDelegation(unittest.TestCase):
    """
    Verify that kraken-bot/logic.py's check_circuit_breaker is a thin
    delegate to shared.circuit_breaker.check_circuit_breaker and produces
    identical results for all input cases.
    """

    @classmethod
    def setUpClass(cls):
        """Import kraken-bot logic from the repo root path."""
        _KRAKEN_ROOT = os.path.join(_REPO_ROOT, "kraken-bot")
        if _KRAKEN_ROOT not in sys.path:
            sys.path.insert(0, _KRAKEN_ROOT)
        import logic as _logic
        # Store as a staticmethod-like reference to avoid Python passing
        # the test instance as the first positional argument.
        cls._logic_cb_fn = staticmethod(_logic.check_circuit_breaker)

    def _cb(self, *args, **kwargs):
        return self._logic_cb_fn(*args, **kwargs)

    def _make_history(self, prices, minutes_apart=1):
        now = datetime.now(tz=timezone.utc)
        history = deque(maxlen=200)
        for i, price in enumerate(prices):
            ts = now - timedelta(minutes=(len(prices) - 1 - i) * minutes_apart)
            history.append((ts, price))
        return history

    def test_no_crash_same_result(self):
        history = self._make_history([100, 101, 102])
        self.assertEqual(
            self._cb(history),
            check_circuit_breaker(history),
        )

    def test_crash_same_result(self):
        history = self._make_history([100, 85])
        self.assertEqual(
            self._cb(history, drop_threshold=0.10),
            check_circuit_breaker(history, drop_threshold=0.10),
        )

    def test_empty_same_result(self):
        history = deque()
        self.assertEqual(
            self._cb(history),
            check_circuit_breaker(history),
        )

    def test_logic_cb_returns_true_on_crash(self):
        """kraken-bot logic.check_circuit_breaker still returns True on crash."""
        history = self._make_history([100, 80])
        self.assertTrue(self._cb(history, drop_threshold=0.10))

    def test_logic_cb_returns_false_on_no_crash(self):
        history = self._make_history([100, 97])
        self.assertFalse(self._cb(history, drop_threshold=0.10))


if __name__ == "__main__":
    unittest.main(verbosity=2)
