"""
Tests for Task #25 — Data Integrity Layer + Stateful Cycle Memory

Covers:
  1. MarketSnapshotValidator  — validate_snapshot()
  2. CycleStateTracker        — outcome recording + multiplier decay
  3. VetoEnforcer             — load_active_vetoes() / is_vetoed()
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Ensure trading-platform packages are importable ───────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# ── Ensure shared/ is importable ─────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.market_snapshot_validator import validate_snapshot, ValidationResult
from core.cycle_state import CycleStateTracker
from core.veto_enforcer import (
    load_active_vetoes,
    is_vetoed,
    get_veto_status,
    _VETO_FILE,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _healthy_snapshot(**overrides) -> dict:
    """Build a minimal but valid market snapshot."""
    snap = {
        "market_data": {
            "by_ticker": {
                "SPY": {
                    "bars": [{"c": 500, "o": 499, "h": 501, "l": 498, "v": 1e6}],
                    "latest_price": 500.0,
                },
            },
            "spy_price": 500.0,
        },
        "macro_data": {"DGS10": {"value": 4.2}},
        "news_data":  {"all_headlines": ["[MACRO] Some headline — Some description"]},
        "_snapshot_ts": time.time(),
    }
    snap.update(overrides)
    return snap


def _write_veto_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ══════════════════════════════════════════════════════════════════════════════
# 1. MarketSnapshotValidator
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketSnapshotValidator(unittest.TestCase):

    def test_healthy_snapshot_passes(self):
        result = validate_snapshot(_healthy_snapshot())
        self.assertTrue(result.ok, f"Expected ok=True but got: {result.reason}")
        self.assertEqual(result.reason, "")
        self.assertGreater(result.checks_passed, 0)
        self.assertEqual(result.checks_failed, 0)

    def test_missing_market_data_key_fails(self):
        snap = _healthy_snapshot()
        snap.pop("market_data")
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertIn("market_data", result.reason)

    def test_missing_news_data_key_fails(self):
        snap = _healthy_snapshot()
        snap.pop("news_data")
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertIn("news_data", result.reason)

    def test_none_market_data_fails(self):
        snap = _healthy_snapshot(market_data=None)
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)

    def test_empty_by_ticker_fails(self):
        snap = _healthy_snapshot()
        snap["market_data"]["by_ticker"] = {}
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertIn("empty", result.reason.lower())

    def test_all_tickers_errored_fails(self):
        snap = _healthy_snapshot()
        snap["market_data"]["by_ticker"] = {
            "SPY": {"error": "fetch failed", "bars": []},
            "QQQ": {"error": "timeout",      "bars": []},
        }
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertIn("error", result.reason.lower())

    def test_at_least_one_healthy_ticker_passes(self):
        snap = _healthy_snapshot()
        snap["market_data"]["by_ticker"]["QQQ"] = {"error": "fetch failed", "bars": []}
        result = validate_snapshot(snap)
        self.assertTrue(result.ok)

    def test_news_data_not_a_list_fails(self):
        snap = _healthy_snapshot()
        snap["news_data"]["all_headlines"] = "not_a_list"
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)

    def test_empty_headlines_list_passes(self):
        """Empty headlines is allowed — LLM runs with less news context."""
        snap = _healthy_snapshot()
        snap["news_data"]["all_headlines"] = []
        result = validate_snapshot(snap)
        self.assertTrue(result.ok)

    def test_stale_snapshot_ts_fails(self):
        """Timestamp older than max_staleness_minutes should fail."""
        snap = _healthy_snapshot()
        snap["_snapshot_ts"] = time.time() - (25 * 60)   # 25 min old
        result = validate_snapshot(snap, max_staleness_minutes=20)
        self.assertFalse(result.ok)
        self.assertIn("stale", result.reason.lower())

    def test_fresh_snapshot_ts_passes(self):
        snap = _healthy_snapshot()
        snap["_snapshot_ts"] = time.time() - (5 * 60)    # 5 min old
        result = validate_snapshot(snap, max_staleness_minutes=20)
        self.assertTrue(result.ok)

    def test_no_snapshot_ts_skips_staleness_check(self):
        """If _snapshot_ts is absent the staleness check is skipped (no failure)."""
        snap = _healthy_snapshot()
        snap.pop("_snapshot_ts", None)
        result = validate_snapshot(snap)
        self.assertTrue(result.ok)

    def test_validation_result_is_frozen(self):
        result = validate_snapshot(_healthy_snapshot())
        with self.assertRaises(Exception):
            result.ok = False    # type: ignore[misc]

    def test_missing_macro_data_key_fails(self):
        """macro_data is a required key — None should fail."""
        snap = _healthy_snapshot()
        snap.pop("macro_data")
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertIn("macro_data", result.reason)

    def test_none_macro_data_fails(self):
        """Explicitly passing macro_data=None should fail."""
        snap = _healthy_snapshot(macro_data=None)
        result = validate_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertIn("macro_data", result.reason)

    def test_crypto_only_empty_macro_data_passes(self):
        """Crypto-only cycles pass an empty dict {}, not None — must pass."""
        snap = _healthy_snapshot()
        snap["macro_data"] = {}   # empty dict is valid (no FRED data for crypto)
        result = validate_snapshot(snap)
        self.assertTrue(result.ok)


# ══════════════════════════════════════════════════════════════════════════════
# 2. CycleStateTracker
# ══════════════════════════════════════════════════════════════════════════════

class TestCycleStateTracker(unittest.TestCase):

    def _make_tracker(self, window: int = 10) -> CycleStateTracker:
        """Create a tracker with no file persistence (isolated from disk)."""
        return CycleStateTracker(window_size=window, state_file=None)

    def test_initial_multiplier_is_1(self):
        tracker = self._make_tracker()
        self.assertAlmostEqual(tracker.get_confidence_multiplier(), 1.0)

    def test_success_does_not_reduce_multiplier(self):
        tracker = self._make_tracker()
        tracker.record_outcome("success")
        tracker.record_outcome("success")
        self.assertAlmostEqual(tracker.get_confidence_multiplier(), 1.0)

    def test_failure_reduces_multiplier(self):
        tracker = self._make_tracker()
        tracker.record_outcome("failure")
        mult = tracker.get_confidence_multiplier()
        self.assertLess(mult, 1.0)
        self.assertAlmostEqual(mult, 0.90, places=2)

    def test_warning_reduces_multiplier_half_step(self):
        tracker = self._make_tracker()
        tracker.record_outcome("warning")
        mult = tracker.get_confidence_multiplier()
        self.assertAlmostEqual(mult, 0.95, places=2)

    def test_multiple_failures_floor_at_configured_floor(self):
        tracker = self._make_tracker(window=10)
        for _ in range(10):
            tracker.record_outcome("failure")
        mult = tracker.get_confidence_multiplier()
        self.assertGreaterEqual(mult, tracker.floor)
        self.assertAlmostEqual(mult, tracker.floor, places=2)

    def test_five_failures_reduces_to_0_5(self):
        tracker = self._make_tracker(window=10)
        for _ in range(5):
            tracker.record_outcome("failure")
        mult = tracker.get_confidence_multiplier()
        self.assertAlmostEqual(mult, 0.50, places=2)

    def test_window_rolls_over(self):
        """After filling the window with failures and then successes, multiplier recovers."""
        tracker = self._make_tracker(window=5)
        for _ in range(5):
            tracker.record_outcome("failure")
        self.assertAlmostEqual(tracker.get_confidence_multiplier(), tracker.floor, places=2)
        # Replace all failures with successes
        for _ in range(5):
            tracker.record_outcome("success")
        self.assertAlmostEqual(tracker.get_confidence_multiplier(), 1.0, places=2)

    def test_reset_clears_history(self):
        tracker = self._make_tracker()
        tracker.record_outcome("failure")
        tracker.record_outcome("failure")
        tracker.reset()
        self.assertAlmostEqual(tracker.get_confidence_multiplier(), 1.0)
        self.assertEqual(len(tracker.recent_outcomes()), 0)

    def test_recent_outcomes_returns_list(self):
        tracker = self._make_tracker()
        tracker.record_outcome("success")
        tracker.record_outcome("warning")
        outcomes = tracker.recent_outcomes()
        self.assertEqual(outcomes, ["success", "warning"])

    def test_failure_count(self):
        tracker = self._make_tracker()
        tracker.record_outcome("failure")
        tracker.record_outcome("success")
        tracker.record_outcome("failure")
        self.assertEqual(tracker.failure_count(), 2)

    def test_to_dict_is_serialisable(self):
        import json
        tracker = self._make_tracker()
        tracker.record_outcome("success")
        d = tracker.to_dict()
        self.assertIsInstance(json.dumps(d), str)
        self.assertIn("confidence_multiplier", d)
        self.assertIn("recent_outcomes", d)

    def test_state_persists_to_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = Path(f.name)
        try:
            tracker = CycleStateTracker(window_size=5, state_file=state_path)
            tracker.record_outcome("failure")
            tracker.record_outcome("warning")
            # Re-load from file
            tracker2 = CycleStateTracker(window_size=5, state_file=state_path)
            self.assertEqual(tracker2.recent_outcomes(), ["failure", "warning"])
        finally:
            state_path.unlink(missing_ok=True)

    def test_invalid_outcomes_not_loaded_from_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            state_path = Path(f.name)
            json.dump({"history": ["success", "INVALID", "failure"]}, f)
        try:
            tracker = CycleStateTracker(window_size=5, state_file=state_path)
            self.assertEqual(tracker.recent_outcomes(), ["success", "failure"])
        finally:
            state_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 3. VetoEnforcer
# ══════════════════════════════════════════════════════════════════════════════

class TestVetoEnforcer(unittest.TestCase):
    """Tests for veto_enforcer.py using a patched _VETO_FILE path."""

    def setUp(self):
        """Reset module-level cache before each test."""
        import core.veto_enforcer as _ve
        _ve._cache_ts      = 0.0
        _ve._cached_vetoes = _ve._EMPTY_VETOES
        _ve._cached_conditions = []

    def _patch_veto_file(self, tmp_path: Path):
        """Patch _VETO_FILE to point at a test file."""
        import core.veto_enforcer as _ve
        return patch.object(_ve, "_VETO_FILE", tmp_path)

    def test_absent_file_returns_empty_set(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            with self._patch_veto_file(fake_path):
                result = load_active_vetoes()
        self.assertEqual(len(result), 0)

    def test_ticker_not_in_empty_vetoes(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            with self._patch_veto_file(fake_path):
                self.assertFalse(is_vetoed("SPY"))

    def test_ticker_in_vetoes_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            _write_veto_file(fake_path, {
                "generated_at":   "2026-03-30T04:15:00Z",
                "vetoed_tickers": ["TSLA", "AAPL"],
                "conditions":     [],
            })
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0  # force cache miss
            with self._patch_veto_file(fake_path):
                self.assertTrue(is_vetoed("TSLA"))
                self.assertTrue(is_vetoed("aapl"))    # case-insensitive
                self.assertFalse(is_vetoed("MSFT"))

    def test_ticker_in_conditions_is_also_vetoed(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            _write_veto_file(fake_path, {
                "generated_at":   "2026-03-30T04:15:00Z",
                "vetoed_tickers": [],
                "conditions":     [{"type": "news_blacklist", "ticker": "META"}],
            })
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0
            with self._patch_veto_file(fake_path):
                self.assertTrue(is_vetoed("META"))

    def test_expired_vetoes_return_empty(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            _write_veto_file(fake_path, {
                "generated_at":   "2026-03-29T04:15:00Z",
                "valid_until":    "2026-03-29T23:59:00Z",   # yesterday
                "vetoed_tickers": ["SPY", "QQQ"],
                "conditions":     [],
            })
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0
            with self._patch_veto_file(fake_path):
                result = load_active_vetoes()
        self.assertEqual(len(result), 0)

    def test_unparseable_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            fake_path.write_text("{ INVALID JSON }")
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0
            with self._patch_veto_file(fake_path):
                result = load_active_vetoes()
        self.assertEqual(len(result), 0)

    def test_crypto_pair_slash_normalised(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            _write_veto_file(fake_path, {
                "vetoed_tickers": ["BTCUSD"],
                "conditions":     [],
            })
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0
            with self._patch_veto_file(fake_path):
                self.assertTrue(is_vetoed("BTC/USD"))
                self.assertTrue(is_vetoed("BTCUSD"))

    def test_cache_hit_does_not_reread_file(self):
        """Once loaded, subsequent calls within TTL must not re-read the file."""
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            _write_veto_file(fake_path, {"vetoed_tickers": ["TSLA"], "conditions": []})
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0
            with self._patch_veto_file(fake_path):
                load_active_vetoes()  # prime cache
                # Overwrite file — should NOT be re-read within TTL
                _write_veto_file(fake_path, {"vetoed_tickers": [], "conditions": []})
                result = load_active_vetoes()
            # Still sees old cached data
            self.assertIn("TSLA", result)

    def test_get_veto_status_structure(self):
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "veto_conditions.json"
            _write_veto_file(fake_path, {
                "vetoed_tickers": ["NVDA"],
                "conditions":     [{"type": "vpin_threshold", "value": 0.7}],
            })
            import core.veto_enforcer as _ve
            _ve._cache_ts = 0.0
            with self._patch_veto_file(fake_path):
                status = get_veto_status()
        self.assertIn("active_veto_count", status)
        self.assertIn("vetoed_tickers", status)
        self.assertIn("condition_count", status)
        self.assertIn("file_exists", status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
