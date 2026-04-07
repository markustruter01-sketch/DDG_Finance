"""
Regression tests for ClaudeBudget (paid-tier no-op semantics).
Previously tested GroqBudget free-tier enforcement; updated for Claude
migration (Task #66).  The groq_budget module is now a shim that re-exports
ClaudeBudget — all tests verify paid-tier no-op behavior.

Run from trading-platform/:
    python3 -m pytest tests/test_groq_budget.py -v
"""

import importlib
import sys
import unittest
from unittest.mock import patch, MagicMock


def _fresh_budget():
    """Return a fresh ClaudeBudget instance (via the shim) with clean state."""
    for mod in list(sys.modules):
        if mod in ("analysis.claude_budget", "analysis.groq_budget"):
            del sys.modules[mod]
    gb_mod = importlib.import_module("analysis.groq_budget")
    instance = gb_mod.GroqBudget()
    return instance, gb_mod


class TestPaidTierNoOps(unittest.TestCase):
    """All gating methods must be no-ops on Claude's paid tier."""

    def setUp(self):
        self.gb, _ = _fresh_budget()

    def test_budget_exhausted_always_false(self):
        """budget_exhausted() must always return False on paid tier."""
        self.assertFalse(self.gb.budget_exhausted())

    def test_can_call_regime_always_true(self):
        """can_call_regime() must always return True regardless of call count."""
        for _ in range(20):
            self.assertTrue(self.gb.can_call_regime())
            self.gb.record_regime_call()

    def test_can_call_crypto_always_true(self):
        """can_call_crypto() must always return True regardless of call count."""
        for _ in range(20):
            self.assertTrue(self.gb.can_call_crypto())
            self.gb.record_crypto_call()

    def test_can_call_commentary_always_true(self):
        """can_call_commentary() must always return True regardless of cap."""
        ep = "alpaca"
        for _ in range(50):
            self.assertTrue(self.gb.can_call_commentary(ep))
            self.gb.record_commentary_call(ep)

    def test_can_call_commentary_force_always_true(self):
        """force=True must always return True on paid tier."""
        for _ in range(10):
            self.assertTrue(self.gb.can_call_commentary("alpaca", force=True))

    def test_next_regime_eligible_at_iso_always_none(self):
        """No interval throttle on paid tier — should always return None."""
        self.assertIsNone(self.gb.next_regime_eligible_at_iso())
        self.gb.record_regime_call()
        self.assertIsNone(self.gb.next_regime_eligible_at_iso())


class TestTokenTracking(unittest.TestCase):
    """Token consumption must still be tracked for monitoring."""

    def setUp(self):
        self.gb, _ = _fresh_budget()

    def test_consume_accumulates(self):
        """consume() must accumulate token counts."""
        self.gb.consume(1_000, call_type="regime")
        self.gb.consume(500,   call_type="commentary")
        usage = self.gb.get_usage()
        self.assertEqual(usage["tokens_used"], 1_500)

    def test_consume_tracks_by_type(self):
        """consume() must record tokens per call_type."""
        self.gb.consume(2_000, call_type="regime")
        self.gb.consume(800,   call_type="audit")
        usage = self.gb.get_usage()
        self.assertEqual(usage["by_type"].get("regime", 0), 2_000)
        self.assertEqual(usage["by_type"].get("audit", 0), 800)

    def test_budget_status_provider_claude(self):
        """budget_status() must report provider='claude'."""
        status = self.gb.budget_status()
        self.assertEqual(status["provider"], "claude")

    def test_budget_status_tokens_remaining_none(self):
        """tokens_remaining must be None — no hard budget on paid tier."""
        status = self.gb.budget_status()
        self.assertIsNone(status["tokens_remaining"])

    def test_budget_status_regime_call_eligible_true(self):
        """regime_call_eligible must always be True on paid tier."""
        status = self.gb.budget_status()
        self.assertTrue(status["regime_call_eligible"])


class TestResetAndGetUsage(unittest.TestCase):
    """reset() and get_usage() must work as documented."""

    def setUp(self):
        self.gb, _ = _fresh_budget()

    def test_reset_clears_all_counters(self):
        """reset() must zero all tracking counters."""
        self.gb.consume(5_000, call_type="regime")
        self.gb.record_regime_call()
        self.gb.record_commentary_call("kraken")
        self.gb.reset()
        usage = self.gb.get_usage()
        self.assertEqual(usage["tokens_used"], 0)
        self.assertEqual(usage["regime_calls"], 0)
        self.assertEqual(usage["commentary_calls"], {})
        self.assertEqual(usage["by_type"], {})

    def test_get_usage_has_required_keys(self):
        """get_usage() must return all required monitoring keys."""
        usage = self.gb.get_usage()
        for key in ("date", "tokens_used", "regime_calls", "crypto_calls",
                    "commentary_calls", "by_type", "provider"):
            self.assertIn(key, usage, f"Missing key: {key}")

    def test_get_usage_provider_claude(self):
        """get_usage() must report provider='claude'."""
        self.assertEqual(self.gb.get_usage()["provider"], "claude")


class TestShimIdentity(unittest.TestCase):
    """groq_budget shim must re-export ClaudeBudget without wrapping."""

    def test_groq_budget_is_claude_budget(self):
        from analysis.groq_budget import GroqBudget
        from analysis.claude_budget import ClaudeBudget
        self.assertIs(GroqBudget, ClaudeBudget)

    def test_groq_budget_singleton_is_claude_singleton(self):
        from analysis.groq_budget import budget as g_budget
        from analysis.claude_budget import budget as c_budget
        self.assertIs(g_budget, c_budget)


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
