"""
Regression tests for GroqBudget: covers zero-budget enforcement with force=True
and the daily commentary cap behaviour.
Run from trading-platform/:
    python3 -m pytest tests/test_groq_budget.py -v
"""

import importlib
import sys
import types
import unittest
from unittest.mock import patch, MagicMock


def _make_budget(tokens_used: int, daily_budget: int = 100_000, daily_cap: int = 10):
    """
    Return a fresh GroqBudget instance with _tokens_used pre-set and
    settings mocked to the supplied limits.
    """
    import threading

    fake_settings = MagicMock()
    fake_settings.groq_daily_token_budget = daily_budget
    fake_settings.groq_commentary_daily_cap = daily_cap

    # Reuse the package module so patch("analysis.groq_budget.settings", ...)
    # patches the same globals used by the class methods.  Each test still gets
    # a fresh, manually initialised instance, so counters cannot leak.
    with patch.dict("sys.modules", {"core.config": MagicMock(settings=fake_settings)}):
        gb_mod = importlib.import_module("analysis.groq_budget")
    gb = gb_mod.GroqBudget.__new__(gb_mod.GroqBudget)
    gb._lock = threading.Lock()
    gb._reset_day = gb_mod.GroqBudget._today_utc()
    gb._tokens_used = tokens_used
    gb._regime_calls = 0
    gb._crypto_calls = 0
    gb._last_regime_call_at = 0.0
    gb._commentary_calls = {}
    gb._budget_warned = set()
    return gb, fake_settings, gb_mod


class TestForceBypassRespectsBudget(unittest.TestCase):
    def test_force_true_blocked_at_zero_budget(self):
        """force=True must NOT bypass the check when remaining tokens == 0."""
        gb, settings, module = _make_budget(tokens_used=100_000, daily_budget=100_000)
        with patch.object(module, "settings", settings):
            result = gb.can_call_commentary("alpaca", force=True)
        self.assertFalse(result, "force=True should NOT allow calls when budget is fully exhausted")

    def test_force_true_allowed_when_budget_remains(self):
        """force=True bypasses the daily call cap when budget has tokens left."""
        gb, settings, module = _make_budget(tokens_used=0, daily_budget=100_000, daily_cap=1)
        with patch.object(module, "settings", settings):
            gb._commentary_calls["alpaca"] = 1  # already hit the cap once
            result = gb.can_call_commentary("alpaca", force=True)
        self.assertTrue(result, "force=True should bypass daily call cap when budget remains")

    def test_budget_exhausted_flag_accurate(self):
        """budget_exhausted() returns True iff tokens_used >= daily_budget."""
        gb_full, s1, module = _make_budget(tokens_used=100_000, daily_budget=100_000)
        gb_part, s2, _ = _make_budget(tokens_used=50_000,  daily_budget=100_000)

        with patch.object(module, "settings", s1):
            self.assertTrue(gb_full.budget_exhausted())
        with patch.object(module, "settings", s2):
            self.assertFalse(gb_part.budget_exhausted())

    def test_cap_reached_does_not_set_budget_exhausted(self):
        """Hitting daily call cap should NOT make budget_exhausted() return True."""
        gb, settings, module = _make_budget(tokens_used=1_000, daily_budget=100_000, daily_cap=5)
        with patch.object(module, "settings", settings):
            gb._commentary_calls["kraken"] = 5  # cap reached, budget fine
            can_call = gb.can_call_commentary("kraken", force=False)
            exhausted = gb.budget_exhausted()
        self.assertFalse(can_call,  "should be blocked by daily cap")
        self.assertFalse(exhausted, "budget_exhausted should be False when blocked by cap, not budget")

    def test_one_shot_warning_per_endpoint(self):
        """Budget-exhausted warning state is recorded exactly once per endpoint."""
        gb, settings, module = _make_budget(tokens_used=100_000, daily_budget=100_000)
        with patch.object(module, "settings", settings):
            self.assertNotIn("alpaca", gb._budget_warned)
            gb.can_call_commentary("alpaca", force=True)
            self.assertIn("alpaca", gb._budget_warned, "_budget_warned should record endpoint after first call")
            gb.can_call_commentary("alpaca", force=True)
            self.assertIn("alpaca", gb._budget_warned, "_budget_warned should still contain endpoint on second call")
            # Also verify a different endpoint gets its own independent entry
            gb.can_call_commentary("kraken", force=True)
            self.assertIn("kraken", gb._budget_warned)


class TestDedupKeyStability(unittest.TestCase):
    def test_key_excludes_message(self):
        """_dedup_key must return the same key regardless of message content."""
        if "core.degradation_tracker" in sys.modules:
            del sys.modules["core.degradation_tracker"]

        fake_pg = MagicMock()
        fake_pg.is_pg_available.return_value = False
        with patch.dict("sys.modules", {
            "db.postgres": fake_pg,
            "loguru": MagicMock(logger=MagicMock()),
        }):
            dt = importlib.import_module("core.degradation_tracker")
            k1 = dt._dedup_key("kraken_api", "stale")
            k2 = dt._dedup_key("kraken_api", "stale")
        self.assertEqual(k1, k2)
        self.assertEqual(k1, "kraken_api::stale")

    def test_mark_resolved_clears_escalation(self):
        """mark_resolved must remove escalation counts for the resolved key."""
        if "core.degradation_tracker" in sys.modules:
            del sys.modules["core.degradation_tracker"]

        fake_pg = MagicMock()
        fake_pg.is_pg_available.return_value = False
        with patch.dict("sys.modules", {
            "db.postgres": fake_pg,
            "loguru": MagicMock(logger=MagicMock()),
        }):
            dt = importlib.import_module("core.degradation_tracker")
            key = dt._dedup_key("kraken_api", "stale")
            dt._escalation_counts[key] = 3
            dt._recent_keys[key] = 9999.0
            dt.mark_resolved("kraken_api", "stale")
        self.assertNotIn(key, dt._escalation_counts)
        self.assertNotIn(key, dt._recent_keys)


if __name__ == "__main__":
    unittest.main()
