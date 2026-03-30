"""
Tests for Task #27 — Kraken Microstructure Alpha + VaR Circuit Breaker

Covers:
  1. compute_ofi()           — order-flow imbalance (pure function)
  2. compute_vamp()          — volume-adjusted momentum price (pure function)
  3. compute_vpin()          — VPIN adverse-selection proxy (pure function)
  4. MicrostructureSignal    — dataclass factory, entry_filter, to_dict
  5. compute_parametric_var  — VaR math (pure function)
  6. VaRCircuitBreaker       — stateful VaR CB: record, check_and_trip, reset
"""

from __future__ import annotations

import os
import sys
import math
import unittest
from datetime import datetime, timezone, timedelta

# ── Ensure repo root on path ──────────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..", "..")
_KRAKEN    = os.path.join(_REPO_ROOT, "kraken-bot")

for p in (_REPO_ROOT, _KRAKEN):
    if p not in sys.path:
        sys.path.insert(0, p)

from microstructure import (
    compute_ofi,
    compute_vamp,
    compute_vpin,
    MicrostructureSignal,
    OFI_LONG_MIN,
    OFI_SHORT_MAX,
    VPIN_BLOCK_THRESH,
)
from shared.var_circuit_breaker import (
    VaRCircuitBreaker,
    compute_parametric_var,
    _normal_quantile,
)


# ── Candle helpers ────────────────────────────────────────────────────────────

def _bar(o: float, h: float, l: float, c: float, v: float, ts: int = 0) -> list:
    return [ts, o, h, l, c, v]


def _bullish_candles(n: int = 20, base: float = 100.0, vol: float = 1000.0) -> list:
    """N candles where close > open (buy pressure)."""
    return [_bar(base, base + 2, base - 0.5, base + 1.5, vol, i * 3600_000) for i in range(n)]


def _bearish_candles(n: int = 20, base: float = 100.0, vol: float = 1000.0) -> list:
    """N candles where close < open (sell pressure)."""
    return [_bar(base + 1.5, base + 2, base - 0.5, base - 0.5, vol, i * 3600_000) for i in range(n)]


def _balanced_candles(n: int = 20, base: float = 100.0, vol: float = 1000.0) -> list:
    """N candles alternating bullish/bearish (balanced flow)."""
    bars = []
    for i in range(n):
        if i % 2 == 0:
            bars.append(_bar(base, base + 2, base - 0.5, base + 1.5, vol, i * 3600_000))
        else:
            bars.append(_bar(base + 1.5, base + 2, base - 0.5, base - 0.5, vol, i * 3600_000))
    return bars


# ══════════════════════════════════════════════════════════════════════════════
# 1. compute_ofi
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeOFI(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(compute_ofi([]), 0.0)

    def test_single_bar_returns_zero(self):
        self.assertEqual(compute_ofi([_bar(100, 101, 99, 100.5, 1000)]), 0.0)

    def test_all_bullish_returns_positive_one(self):
        candles = _bullish_candles(10)
        ofi = compute_ofi(candles, window=10)
        self.assertAlmostEqual(ofi, 1.0, places=4)

    def test_all_bearish_returns_negative_one(self):
        candles = _bearish_candles(10)
        ofi = compute_ofi(candles, window=10)
        self.assertAlmostEqual(ofi, -1.0, places=4)

    def test_balanced_near_zero(self):
        candles = _balanced_candles(10)
        ofi = compute_ofi(candles, window=10)
        self.assertAlmostEqual(ofi, 0.0, places=4)

    def test_range_in_minus_one_to_plus_one(self):
        for _ in range(20):
            candles = _bullish_candles(15)
            ofi = compute_ofi(candles, window=15)
            self.assertGreaterEqual(ofi, -1.0)
            self.assertLessEqual(ofi, 1.0)

    def test_window_respected(self):
        # Last 5 candles are bearish; earlier 10 are bullish
        candles = _bullish_candles(10) + _bearish_candles(5)
        ofi_full = compute_ofi(candles, window=15)
        ofi_recent = compute_ofi(candles, window=5)
        # recent-only window should be more bearish
        self.assertLess(ofi_recent, ofi_full)

    def test_zero_volume_bars_skipped(self):
        candles = [_bar(100, 101, 99, 101, 0)] * 10 + [_bar(100, 102, 98, 99, 500)]
        ofi = compute_ofi(candles, window=11)
        # Only last bar contributes — close < open → bearish
        self.assertLess(ofi, 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 2. compute_vamp
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVAMP(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(compute_vamp([]), 0.0)

    def test_single_bar_returns_zero(self):
        self.assertEqual(compute_vamp([_bar(100, 101, 99, 100.5, 500)]), 0.0)

    def test_positive_when_close_above_vwap(self):
        # All bars identical except last is higher close
        candles = [_bar(100, 102, 98, 100, 1000)] * 19 + [_bar(100, 102, 98, 110, 1000)]
        vamp = compute_vamp(candles, window=20)
        self.assertGreater(vamp, 0.0)

    def test_negative_when_close_below_vwap(self):
        candles = [_bar(100, 102, 98, 100, 1000)] * 19 + [_bar(100, 102, 98, 90, 1000)]
        vamp = compute_vamp(candles, window=20)
        self.assertLess(vamp, 0.0)

    def test_zero_when_close_equals_vwap(self):
        # Uniform candles: typical = (h+l+c)/3 = (102+98+100)/3 = 100; close = 100
        candles = [_bar(100, 102, 98, 100, 1000)] * 10
        vamp = compute_vamp(candles, window=10)
        self.assertAlmostEqual(vamp, 0.0, places=6)

    def test_zero_volume_skipped(self):
        # Only valid bar contributes; close = vwap → 0
        candles = [_bar(100, 102, 98, 100, 0)] * 9 + [_bar(100, 102, 98, 100, 1000)]
        vamp = compute_vamp(candles, window=10)
        self.assertAlmostEqual(vamp, 0.0, places=6)


# ══════════════════════════════════════════════════════════════════════════════
# 3. compute_vpin
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVPIN(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(compute_vpin([]), 0.0)

    def test_single_bar_returns_zero(self):
        self.assertEqual(compute_vpin([_bar(100, 101, 99, 100.5, 500)]), 0.0)

    def test_one_sided_buy_returns_high_vpin(self):
        # close = high → buy_vol = volume, sell_vol = 0
        candles = [_bar(100, 102, 98, 102, 1000)] * 20
        vpin = compute_vpin(candles, window=20)
        self.assertGreater(vpin, 0.9)

    def test_one_sided_sell_returns_high_vpin(self):
        # close = low → sell_vol = volume, buy_vol = 0
        candles = [_bar(100, 102, 98, 98, 1000)] * 20
        vpin = compute_vpin(candles, window=20)
        self.assertGreater(vpin, 0.9)

    def test_balanced_returns_low_vpin(self):
        # close = midpoint → 50/50 split → VPIN ≈ 0
        candles = [_bar(98, 102, 98, 100, 1000)] * 20
        vpin = compute_vpin(candles, window=20)
        self.assertAlmostEqual(vpin, 0.0, places=4)

    def test_vpin_in_range_zero_to_one(self):
        candles = _bullish_candles(20)
        vpin = compute_vpin(candles, window=20)
        self.assertGreaterEqual(vpin, 0.0)
        self.assertLessEqual(vpin, 1.0)

    def test_zero_range_candle_split_fifty_fifty(self):
        # h == l → zero-range → 50/50 split → VPIN ≈ 0
        candles = [_bar(100, 100, 100, 100, 1000)] * 10
        vpin = compute_vpin(candles, window=10)
        self.assertAlmostEqual(vpin, 0.0, places=4)


# ══════════════════════════════════════════════════════════════════════════════
# 4. MicrostructureSignal
# ══════════════════════════════════════════════════════════════════════════════

class TestMicrostructureSignal(unittest.TestCase):

    def _make_signal(self, ofi=0.0, vamp=0.0, vpin=0.0):
        return MicrostructureSignal(symbol="BTC/USD", ofi=ofi, vamp=vamp, vpin=vpin)

    def test_from_ohlcv_creates_signal(self):
        candles = _bullish_candles(20)
        ms = MicrostructureSignal.from_ohlcv(candles, symbol="ETH/USD")
        self.assertEqual(ms.symbol, "ETH/USD")
        self.assertIsInstance(ms.ofi,  float)
        self.assertIsInstance(ms.vamp, float)
        self.assertIsInstance(ms.vpin, float)

    def test_entry_filter_long_allowed_positive_ofi(self):
        ms = self._make_signal(ofi=0.3, vpin=0.2)
        allowed, reason = ms.entry_filter(side="long")
        self.assertTrue(allowed)
        self.assertIn("confirmed", reason)

    def test_entry_filter_long_blocked_negative_ofi(self):
        ms = self._make_signal(ofi=-0.3, vpin=0.2)
        allowed, reason = ms.entry_filter(side="long")
        self.assertFalse(allowed)
        self.assertIn("OFI", reason)

    def test_entry_filter_short_allowed_negative_ofi(self):
        ms = self._make_signal(ofi=-0.3, vpin=0.2)
        allowed, reason = ms.entry_filter(side="short")
        self.assertTrue(allowed)
        self.assertIn("confirmed", reason)

    def test_entry_filter_short_blocked_positive_ofi(self):
        ms = self._make_signal(ofi=0.3, vpin=0.2)
        allowed, reason = ms.entry_filter(side="short")
        self.assertFalse(allowed)
        self.assertIn("OFI", reason)

    def test_entry_filter_blocked_by_high_vpin(self):
        ms = self._make_signal(ofi=0.5, vpin=VPIN_BLOCK_THRESH + 0.01)
        allowed_long,  r_l = ms.entry_filter(side="long")
        allowed_short, r_s = ms.entry_filter(side="short")
        self.assertFalse(allowed_long)
        self.assertFalse(allowed_short)
        self.assertIn("VPIN", r_l)
        self.assertIn("VPIN", r_s)

    def test_is_elevated_vpin_true(self):
        ms = self._make_signal(vpin=0.70)
        self.assertTrue(ms.is_elevated_vpin(threshold=0.65))

    def test_is_elevated_vpin_false(self):
        ms = self._make_signal(vpin=0.40)
        self.assertFalse(ms.is_elevated_vpin(threshold=0.65))

    def test_to_dict_keys(self):
        ms = self._make_signal(ofi=0.1, vamp=0.002, vpin=0.3)
        d = ms.to_dict()
        for key in ("symbol", "ofi", "vamp", "vpin"):
            self.assertIn(key, d)

    def test_to_dict_values_rounded(self):
        ms = self._make_signal(ofi=0.123456789, vpin=0.999999)
        d = ms.to_dict()
        # ofi is rounded to 4 dp
        self.assertEqual(d["ofi"], round(ms.ofi, 4))

    def test_repr(self):
        ms = self._make_signal(ofi=0.1, vamp=0.002, vpin=0.3)
        self.assertIn("MicrostructureSignal", repr(ms))

    def test_neutral_signal_long_just_above_threshold(self):
        # OFI just above the minimum → allowed
        ms = self._make_signal(ofi=OFI_LONG_MIN + 0.001, vpin=0.1)
        allowed, _ = ms.entry_filter(side="long")
        self.assertTrue(allowed)

    def test_neutral_signal_long_just_below_threshold(self):
        # OFI just below the minimum → blocked
        ms = self._make_signal(ofi=OFI_LONG_MIN - 0.001, vpin=0.1)
        allowed, _ = ms.entry_filter(side="long")
        self.assertFalse(allowed)


# ══════════════════════════════════════════════════════════════════════════════
# 5. compute_parametric_var (pure function)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeParametricVar(unittest.TestCase):

    def test_known_returns(self):
        # Returns: 10 × +1% + 10 × -1%; mean=0, std=0.01
        returns = [0.01] * 10 + [-0.01] * 10
        var_usd, var_pct = compute_parametric_var(returns, portfolio_usd=100_000, confidence=0.99)
        # VaR(99%) ≈ z_{0.99} × σ × portfolio = 2.3263 × 0.01 × 100_000 ≈ 2326.30
        self.assertAlmostEqual(var_usd, 2326.30, delta=1.0)
        self.assertAlmostEqual(var_pct, 0.023263, delta=0.0001)

    def test_higher_confidence_higher_var(self):
        returns = [0.01, -0.02, 0.005, -0.015, 0.008] * 4
        _, var_99 = compute_parametric_var(returns, 100_000, confidence=0.99)
        _, var_95 = compute_parametric_var(returns, 100_000, confidence=0.95)
        self.assertGreater(var_99, var_95)

    def test_higher_portfolio_usd_scales_linearly(self):
        returns = [0.01, -0.02, 0.005] * 5
        var_100k, _ = compute_parametric_var(returns, 100_000, confidence=0.99)
        var_200k, _ = compute_parametric_var(returns, 200_000, confidence=0.99)
        self.assertAlmostEqual(var_200k, var_100k * 2, delta=0.01)

    def test_zero_variance_returns_zero_var(self):
        returns = [0.01] * 10  # all same → std = 0 → VaR = max(0, -(μ - 0)) = 0 if μ > 0
        var_usd, var_pct = compute_parametric_var(returns, 100_000, confidence=0.99)
        self.assertEqual(var_usd, 0.0)   # mean > 0, no downside at all
        self.assertEqual(var_pct, 0.0)

    def test_raises_on_insufficient_data(self):
        with self.assertRaises(ValueError):
            compute_parametric_var([0.01], 100_000)

    def test_raises_on_zero_portfolio(self):
        with self.assertRaises(ValueError):
            compute_parametric_var([0.01, -0.02], 0.0)

    def test_normal_quantile_table(self):
        # z_0.99 ≈ 2.3263, z_0.95 ≈ 1.6449
        self.assertAlmostEqual(_normal_quantile(0.99), 2.3263, places=3)
        self.assertAlmostEqual(_normal_quantile(0.95), 1.6449, places=3)


# ══════════════════════════════════════════════════════════════════════════════
# 6. VaRCircuitBreaker — stateful class
# ══════════════════════════════════════════════════════════════════════════════

class TestVaRCircuitBreaker(unittest.TestCase):

    def _vcb(self, var_limit_pct=0.05, min_obs=3, **kwargs):
        return VaRCircuitBreaker(var_limit_pct=var_limit_pct, min_obs=min_obs, **kwargs)

    def test_not_triggered_initially(self):
        vcb = self._vcb()
        self.assertFalse(vcb.is_triggered())

    def test_insufficient_obs_never_trips(self):
        vcb = self._vcb(min_obs=5)
        for _ in range(4):
            vcb.record_return(-0.10)
        triggered, _ = vcb.check_and_trip(100_000)
        self.assertFalse(triggered)

    def test_trips_on_high_variance(self):
        vcb = self._vcb(var_limit_pct=0.01, min_obs=3)
        # Very volatile returns → high VaR → should trip at limit=1%
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        triggered, var_pct = vcb.check_and_trip(100_000)
        self.assertTrue(triggered)
        self.assertGreater(var_pct, 0.01)

    def test_does_not_trip_on_low_variance(self):
        vcb = self._vcb(var_limit_pct=0.99, min_obs=3)
        for r in [0.001, -0.001, 0.001, -0.001]:
            vcb.record_return(r)
        triggered, _ = vcb.check_and_trip(100_000)
        self.assertFalse(triggered)

    def test_reset_clears_pause(self):
        vcb = self._vcb(var_limit_pct=0.01, min_obs=3)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        triggered, _ = vcb.check_and_trip(100_000)
        self.assertTrue(triggered)
        vcb.reset()
        self.assertFalse(vcb.is_triggered())

    def test_idempotent_while_paused(self):
        vcb = self._vcb(var_limit_pct=0.01, min_obs=3)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        vcb.check_and_trip(100_000)
        paused_until_first = vcb.paused_until
        vcb.check_and_trip(100_000)
        # Second call should not re-trip (idempotent)
        self.assertEqual(vcb.paused_until, paused_until_first)

    def test_pause_expires(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, min_obs=3, pause_hours=0.0)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        vcb.check_and_trip(100_000)
        import time as _t
        _t.sleep(0.01)
        self.assertFalse(vcb.is_triggered())

    def test_paused_until_none_when_inactive(self):
        vcb = self._vcb()
        self.assertIsNone(vcb.paused_until)

    def test_minutes_remaining_zero_when_inactive(self):
        vcb = self._vcb()
        self.assertEqual(vcb.minutes_remaining(), 0.0)

    def test_minutes_remaining_positive_when_active(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, min_obs=3, pause_hours=2.0)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        vcb.check_and_trip(100_000)
        self.assertGreater(vcb.minutes_remaining(), 0.0)

    def test_observation_count(self):
        vcb = self._vcb()
        for r in [0.01, -0.01, 0.02]:
            vcb.record_return(r)
        self.assertEqual(vcb.observation_count(), 3)

    def test_to_dict_keys(self):
        vcb = self._vcb()
        d = vcb.to_dict()
        for key in (
            "active", "paused_until", "minutes_remaining",
            "last_var_pct", "last_var_usd", "var_limit_pct",
            "confidence_pct", "window", "observation_count", "pause_hours",
        ):
            self.assertIn(key, d, f"Missing key in to_dict(): {key}")

    def test_to_dict_active(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, min_obs=3, pause_hours=1.0)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        vcb.check_and_trip(100_000)
        d = vcb.to_dict()
        self.assertTrue(d["active"])
        self.assertIsNotNone(d["paused_until"])

    def test_repr(self):
        vcb = self._vcb()
        self.assertIn("VaRCircuitBreaker", repr(vcb))

    def test_window_rolling(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, window=3, min_obs=3, pause_hours=0.01)
        # Feed volatile returns to trip the breaker
        for r in [0.10, -0.10, 0.10]:
            vcb.record_return(r)
        triggered, _ = vcb.check_and_trip(100_000)
        self.assertTrue(triggered)
        # Reset and re-feed calm returns after the window fills up
        vcb.reset()
        # Now add calm returns — they replace the volatile ones in the rolling window
        for r in [0.0001, -0.0001, 0.0001]:
            vcb.record_return(r)
        triggered_calm, _ = vcb.check_and_trip(100_000)
        self.assertFalse(triggered_calm)

    def test_shared_import(self):
        """VaRCircuitBreaker is importable from shared package."""
        from shared import VaRCircuitBreaker as _VCB
        self.assertTrue(callable(_VCB))


if __name__ == "__main__":
    unittest.main(verbosity=2)
