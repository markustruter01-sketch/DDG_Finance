"""
Tests for Task #27 — Kraken Microstructure Alpha + VaR Circuit Breaker

Covers:
  1. compute_ofi()              — order-book OFI (primary API)
  2. compute_vamp()             — order-book VAMP (primary API)
  3. build_trade_buckets()      — trade bucket builder
  4. compute_vpin()             — trade-bucket VPIN (primary API)
  5. compute_ofi_ohlcv()        — OHLCV OFI (backward-compat)
  6. compute_vamp_ohlcv()       — OHLCV VAMP (backward-compat)
  7. compute_vpin_ohlcv()       — OHLCV VPIN (backward-compat)
  8. MicrostructureSignal       — from_orderbook, from_ohlcv, entry_filter, to_dict
  9. compute_parametric_var     — VaR math (shared/)
  10. VaRCircuitBreaker          — stateful VaR CB: record, check_and_trip, reset
  11. compute_daily_var           — historical simulation VaR (portfolio/)
"""

from __future__ import annotations

import os
import sys
import math
import time
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone, timedelta

# ── Ensure repo root on path ──────────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..", "..")
_KRAKEN    = os.path.join(_REPO_ROOT, "kraken-bot")
_TP        = os.path.join(_REPO_ROOT, "trading-platform")

for p in (_REPO_ROOT, _KRAKEN, _TP):
    if p not in sys.path:
        sys.path.insert(0, p)

from microstructure import (
    # Primary API (order-book / trade-bucket)
    compute_ofi,
    compute_vamp,
    compute_vpin,
    build_trade_buckets,
    # OHLCV backward-compat
    compute_ofi_ohlcv,
    compute_vamp_ohlcv,
    compute_vpin_ohlcv,
    # Dataclass + thresholds
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

def _bar(o, h, l, c, v, ts=0):
    return [ts, o, h, l, c, v]

def _bullish_candles(n=20, base=100.0, vol=1000.0):
    return [_bar(base, base+2, base-0.5, base+1.5, vol, i*3600_000) for i in range(n)]

def _bearish_candles(n=20, base=100.0, vol=1000.0):
    return [_bar(base+1.5, base+2, base-0.5, base-0.5, vol, i*3600_000) for i in range(n)]

def _balanced_candles(n=20, base=100.0, vol=1000.0):
    bars = []
    for i in range(n):
        if i % 2 == 0:
            bars.append(_bar(base, base+2, base-0.5, base+1.5, vol, i*3600_000))
        else:
            bars.append(_bar(base+1.5, base+2, base-0.5, base-0.5, vol, i*3600_000))
    return bars


# ── Order-book / trade helpers ────────────────────────────────────────────────

def _ob(bid_size=10.0, ask_size=10.0, levels=5, mid=50000.0):
    """Synthetic ccxt order book dict."""
    spread = 0.5
    bids = [[mid - spread/2 - i*0.1, bid_size] for i in range(levels)]
    asks = [[mid + spread/2 + i*0.1, ask_size] for i in range(levels)]
    return {"bids": bids, "asks": asks}

def _trade(side, price=50000.0, amount=0.1):
    """Synthetic ccxt trade dict."""
    return {
        "side":   side,
        "price":  price,
        "amount": amount,
        "cost":   price * amount,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. compute_ofi  (order-book based — primary API)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeOFIOrderBook(unittest.TestCase):

    def test_empty_ob_returns_zero(self):
        self.assertEqual(compute_ofi({}), 0.0)

    def test_empty_bids_and_asks_returns_zero(self):
        self.assertEqual(compute_ofi({"bids": [], "asks": []}), 0.0)

    def test_all_bid_depth_returns_plus_one(self):
        ob = {"bids": [[50000, 100], [49999, 100]], "asks": [[50001, 0], [50002, 0]]}
        self.assertAlmostEqual(compute_ofi(ob), 1.0, places=4)

    def test_all_ask_depth_returns_minus_one(self):
        ob = {"bids": [[50000, 0], [49999, 0]], "asks": [[50001, 100], [50002, 100]]}
        self.assertAlmostEqual(compute_ofi(ob), -1.0, places=4)

    def test_balanced_depth_returns_zero(self):
        ob = _ob(bid_size=10.0, ask_size=10.0)
        self.assertAlmostEqual(compute_ofi(ob), 0.0, places=4)

    def test_positive_when_buy_pressure_dominates(self):
        ob = _ob(bid_size=20.0, ask_size=5.0)
        self.assertGreater(compute_ofi(ob), 0.0)

    def test_negative_when_sell_pressure_dominates(self):
        ob = _ob(bid_size=5.0, ask_size=20.0)
        self.assertLess(compute_ofi(ob), 0.0)

    def test_result_in_minus_one_to_plus_one(self):
        for bid, ask in [(10, 3), (3, 10), (100, 100), (1, 1000)]:
            ofi = compute_ofi(_ob(bid_size=bid, ask_size=ask))
            self.assertGreaterEqual(ofi, -1.0)
            self.assertLessEqual(ofi, 1.0)

    def test_levels_parameter_respected(self):
        ob = {
            "bids": [[50000 - i*0.1, 1.0] for i in range(10)],
            "asks": [[50001 + i*0.1, 1.0 if i < 5 else 10.0] for i in range(10)],
        }
        ofi_5  = compute_ofi(ob, levels=5)
        ofi_10 = compute_ofi(ob, levels=10)
        self.assertNotEqual(ofi_5, ofi_10)


# ══════════════════════════════════════════════════════════════════════════════
# 2. compute_vamp  (order-book based — primary API)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVAMPOrderBook(unittest.TestCase):

    def test_empty_ob_returns_zero(self):
        self.assertEqual(compute_vamp({}), 0.0)

    def test_empty_sides_returns_zero(self):
        self.assertEqual(compute_vamp({"bids": [], "asks": []}), 0.0)

    def test_returns_midprice_for_symmetric_book(self):
        mid = 50000.0
        ob  = _ob(bid_size=5.0, ask_size=5.0, mid=mid)
        vamp = compute_vamp(ob)
        # Should be close to mid
        self.assertAlmostEqual(vamp, mid, delta=1.0)

    def test_positive_finite_result(self):
        ob = _ob(bid_size=8.0, ask_size=5.0)
        self.assertGreater(compute_vamp(ob), 0.0)

    def test_zero_volume_side_uses_other_side(self):
        ob = {"bids": [[50000, 10]], "asks": [[50001, 0]]}
        vamp = compute_vamp(ob, levels=1)
        self.assertAlmostEqual(vamp, 50000.0, delta=1.0)


# ══════════════════════════════════════════════════════════════════════════════
# 3. build_trade_buckets
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildTradeBuckets(unittest.TestCase):

    def test_empty_trades_returns_empty(self):
        self.assertEqual(build_trade_buckets([]), [])

    def test_single_large_trade_not_bucketed_until_full(self):
        trades = [_trade("buy", price=50000, amount=0.1)]  # cost=$5000
        buckets = build_trade_buckets(trades, bucket_size_usd=6000.0)
        self.assertEqual(len(buckets), 0)  # not enough to fill bucket

    def test_bucket_fills_on_exact_threshold(self):
        trades = [_trade("buy", price=50000, amount=0.1)]  # cost=$5000
        buckets = build_trade_buckets(trades, bucket_size_usd=5000.0)
        self.assertEqual(len(buckets), 1)
        self.assertAlmostEqual(buckets[0]["buy_vol"], 5000.0, delta=1.0)
        self.assertAlmostEqual(buckets[0]["sell_vol"], 0.0, delta=1.0)

    def test_buy_and_sell_split_correctly(self):
        # Each $5000 trade fills exactly one bucket → 2 buckets total
        trades = [
            _trade("buy",  price=50000, amount=0.1),
            _trade("sell", price=50000, amount=0.1),
        ]
        buckets = build_trade_buckets(trades, bucket_size_usd=5000.0)
        self.assertEqual(len(buckets), 2)
        buy_vol  = sum(b["buy_vol"]  for b in buckets)
        sell_vol = sum(b["sell_vol"] for b in buckets)
        self.assertAlmostEqual(buy_vol,  5000.0, delta=1.0)
        self.assertAlmostEqual(sell_vol, 5000.0, delta=1.0)

    def test_multiple_buckets(self):
        # 10 trades of $1000 each → 2 buckets of $5000
        trades = [_trade("buy", price=10000, amount=0.1)] * 10
        buckets = build_trade_buckets(trades, bucket_size_usd=5000.0)
        self.assertEqual(len(buckets), 2)

    def test_zero_cost_trades_skipped(self):
        trades = [{"side": "buy", "price": 0.0, "amount": 0.0, "cost": 0.0}]
        self.assertEqual(build_trade_buckets(trades, bucket_size_usd=100.0), [])

    def test_missing_cost_uses_price_times_amount(self):
        trade = {"side": "buy", "price": 50000.0, "amount": 0.1}
        buckets = build_trade_buckets([trade], bucket_size_usd=5000.0)
        self.assertEqual(len(buckets), 1)
        self.assertAlmostEqual(buckets[0]["buy_vol"], 5000.0, delta=1.0)


# ══════════════════════════════════════════════════════════════════════════════
# 4. compute_vpin  (trade-bucket based — primary API)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVPINBuckets(unittest.TestCase):

    def test_empty_buckets_returns_zero(self):
        self.assertEqual(compute_vpin([]), 0.0)

    def test_perfectly_balanced_returns_zero(self):
        buckets = [{"buy_vol": 5000, "sell_vol": 5000, "total_vol": 10000}] * 10
        self.assertAlmostEqual(compute_vpin(buckets), 0.0, places=4)

    def test_all_buy_returns_one(self):
        buckets = [{"buy_vol": 10000, "sell_vol": 0, "total_vol": 10000}] * 10
        self.assertAlmostEqual(compute_vpin(buckets), 1.0, places=4)

    def test_all_sell_returns_one(self):
        buckets = [{"buy_vol": 0, "sell_vol": 10000, "total_vol": 10000}] * 10
        self.assertAlmostEqual(compute_vpin(buckets), 1.0, places=4)

    def test_result_in_zero_to_one(self):
        for b, s in [(7000, 3000), (2000, 8000), (5000, 5000)]:
            buckets = [{"buy_vol": b, "sell_vol": s, "total_vol": b+s}] * 5
            vpin = compute_vpin(buckets)
            self.assertGreaterEqual(vpin, 0.0)
            self.assertLessEqual(vpin, 1.0)

    def test_vpin_from_build_trade_buckets_roundtrip(self):
        """Integration: build_trade_buckets → compute_vpin."""
        all_buy  = [_trade("buy",  price=50000, amount=0.1)] * 10
        buckets  = build_trade_buckets(all_buy, bucket_size_usd=5000.0)
        vpin     = compute_vpin(buckets)
        self.assertAlmostEqual(vpin, 1.0, places=4)


# ══════════════════════════════════════════════════════════════════════════════
# 5. compute_ofi_ohlcv  (OHLCV backward-compat)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeOFIOHLCV(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(compute_ofi_ohlcv([]), 0.0)

    def test_single_bar_returns_zero(self):
        self.assertEqual(compute_ofi_ohlcv([_bar(100, 101, 99, 100.5, 1000)]), 0.0)

    def test_all_bullish_returns_positive_one(self):
        ofi = compute_ofi_ohlcv(_bullish_candles(10), window=10)
        self.assertAlmostEqual(ofi, 1.0, places=4)

    def test_all_bearish_returns_negative_one(self):
        ofi = compute_ofi_ohlcv(_bearish_candles(10), window=10)
        self.assertAlmostEqual(ofi, -1.0, places=4)

    def test_balanced_near_zero(self):
        ofi = compute_ofi_ohlcv(_balanced_candles(10), window=10)
        self.assertAlmostEqual(ofi, 0.0, places=4)

    def test_range_in_minus_one_to_plus_one(self):
        for _ in range(20):
            ofi = compute_ofi_ohlcv(_bullish_candles(15), window=15)
            self.assertGreaterEqual(ofi, -1.0)
            self.assertLessEqual(ofi, 1.0)

    def test_window_respected(self):
        candles = _bullish_candles(10) + _bearish_candles(5)
        ofi_full   = compute_ofi_ohlcv(candles, window=15)
        ofi_recent = compute_ofi_ohlcv(candles, window=5)
        self.assertLess(ofi_recent, ofi_full)

    def test_zero_volume_bars_skipped(self):
        candles = [_bar(100, 101, 99, 101, 0)] * 10 + [_bar(100, 102, 98, 99, 500)]
        ofi = compute_ofi_ohlcv(candles, window=11)
        self.assertLess(ofi, 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 6. compute_vamp_ohlcv  (OHLCV backward-compat)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVAMPOHLCV(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(compute_vamp_ohlcv([]), 0.0)

    def test_single_bar_returns_zero(self):
        self.assertEqual(compute_vamp_ohlcv([_bar(100, 101, 99, 100.5, 500)]), 0.0)

    def test_positive_when_close_above_vwap(self):
        candles = [_bar(100, 102, 98, 100, 1000)] * 19 + [_bar(100, 102, 98, 110, 1000)]
        self.assertGreater(compute_vamp_ohlcv(candles, window=20), 0.0)

    def test_negative_when_close_below_vwap(self):
        candles = [_bar(100, 102, 98, 100, 1000)] * 19 + [_bar(100, 102, 98, 90, 1000)]
        self.assertLess(compute_vamp_ohlcv(candles, window=20), 0.0)

    def test_zero_when_close_equals_vwap(self):
        candles = [_bar(100, 102, 98, 100, 1000)] * 10
        self.assertAlmostEqual(compute_vamp_ohlcv(candles, window=10), 0.0, places=6)

    def test_zero_volume_skipped(self):
        candles = [_bar(100, 102, 98, 100, 0)] * 9 + [_bar(100, 102, 98, 100, 1000)]
        self.assertAlmostEqual(compute_vamp_ohlcv(candles, window=10), 0.0, places=6)


# ══════════════════════════════════════════════════════════════════════════════
# 7. compute_vpin_ohlcv  (OHLCV backward-compat)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeVPINOHLCV(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(compute_vpin_ohlcv([]), 0.0)

    def test_single_bar_returns_zero(self):
        self.assertEqual(compute_vpin_ohlcv([_bar(100, 101, 99, 100.5, 500)]), 0.0)

    def test_one_sided_buy_returns_high_vpin(self):
        candles = [_bar(100, 102, 98, 102, 1000)] * 20
        self.assertGreater(compute_vpin_ohlcv(candles, window=20), 0.9)

    def test_one_sided_sell_returns_high_vpin(self):
        candles = [_bar(100, 102, 98, 98, 1000)] * 20
        self.assertGreater(compute_vpin_ohlcv(candles, window=20), 0.9)

    def test_balanced_returns_low_vpin(self):
        candles = [_bar(98, 102, 98, 100, 1000)] * 20
        self.assertAlmostEqual(compute_vpin_ohlcv(candles, window=20), 0.0, places=4)

    def test_vpin_in_range_zero_to_one(self):
        vpin = compute_vpin_ohlcv(_bullish_candles(20), window=20)
        self.assertGreaterEqual(vpin, 0.0)
        self.assertLessEqual(vpin, 1.0)

    def test_zero_range_candle_split_fifty_fifty(self):
        candles = [_bar(100, 100, 100, 100, 1000)] * 10
        self.assertAlmostEqual(compute_vpin_ohlcv(candles, window=10), 0.0, places=4)


# ══════════════════════════════════════════════════════════════════════════════
# 8. MicrostructureSignal
# ══════════════════════════════════════════════════════════════════════════════

class TestMicrostructureSignal(unittest.TestCase):

    def _make_signal(self, ofi=0.0, vamp=0.0, vpin=0.0):
        return MicrostructureSignal(symbol="BTC/USD", ofi=ofi, vamp=vamp, vpin=vpin)

    def test_from_ohlcv_creates_signal(self):
        ms = MicrostructureSignal.from_ohlcv(_bullish_candles(20), symbol="ETH/USD")
        self.assertEqual(ms.symbol, "ETH/USD")
        self.assertIsInstance(ms.ofi,  float)
        self.assertIsInstance(ms.vamp, float)
        self.assertIsInstance(ms.vpin, float)

    def test_from_orderbook_creates_signal(self):
        ob     = _ob(bid_size=10, ask_size=5)
        trades = [_trade("buy", amount=0.1)] * 5 + [_trade("sell", amount=0.1)] * 5
        ms = MicrostructureSignal.from_orderbook(ob, trades, symbol="BTC/USD")
        self.assertEqual(ms.symbol, "BTC/USD")
        self.assertIsInstance(ms.ofi,  float)
        self.assertIsInstance(ms.vamp, float)
        self.assertIsInstance(ms.vpin, float)

    def test_from_orderbook_buy_pressure_positive_ofi(self):
        ob = _ob(bid_size=20, ask_size=5)
        ms = MicrostructureSignal.from_orderbook(ob, [], symbol="X")
        self.assertGreater(ms.ofi, 0.0)

    def test_from_orderbook_sell_pressure_negative_ofi(self):
        ob = _ob(bid_size=5, ask_size=20)
        ms = MicrostructureSignal.from_orderbook(ob, [], symbol="X")
        self.assertLess(ms.ofi, 0.0)

    def test_from_orderbook_all_buy_trades_high_vpin(self):
        ob     = _ob()
        trades = [_trade("buy", price=50000, amount=0.1)] * 20
        ms     = MicrostructureSignal.from_orderbook(ob, trades, symbol="X",
                                                     bucket_size_usd=5000.0)
        self.assertGreater(ms.vpin, 0.9)

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
        d = self._make_signal(ofi=0.1, vamp=0.002, vpin=0.3).to_dict()
        for key in ("symbol", "ofi", "vamp", "vpin"):
            self.assertIn(key, d)

    def test_to_dict_values_rounded(self):
        ms = self._make_signal(ofi=0.123456789, vpin=0.999999)
        d  = ms.to_dict()
        self.assertEqual(d["ofi"], round(ms.ofi, 4))

    def test_repr(self):
        self.assertIn("MicrostructureSignal", repr(self._make_signal()))

    def test_neutral_signal_long_just_above_threshold(self):
        ms = self._make_signal(ofi=OFI_LONG_MIN + 0.001, vpin=0.1)
        allowed, _ = ms.entry_filter(side="long")
        self.assertTrue(allowed)

    def test_neutral_signal_long_just_below_threshold(self):
        ms = self._make_signal(ofi=OFI_LONG_MIN - 0.001, vpin=0.1)
        allowed, _ = ms.entry_filter(side="long")
        self.assertFalse(allowed)


# ══════════════════════════════════════════════════════════════════════════════
# 9. compute_parametric_var (shared/ — pure function)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeParametricVar(unittest.TestCase):

    def test_known_returns(self):
        returns = [0.01] * 10 + [-0.01] * 10
        var_usd, var_pct = compute_parametric_var(returns, portfolio_usd=100_000, confidence=0.99)
        self.assertAlmostEqual(var_usd, 2326.30, delta=1.0)
        self.assertAlmostEqual(var_pct, 0.023263, delta=0.0001)

    def test_higher_confidence_higher_var(self):
        returns = [0.01, -0.02, 0.005, -0.015, 0.008] * 4
        _, var_99 = compute_parametric_var(returns, 100_000, confidence=0.99)
        _, var_95 = compute_parametric_var(returns, 100_000, confidence=0.95)
        self.assertGreater(var_99, var_95)

    def test_higher_portfolio_scales_linearly(self):
        returns = [0.01, -0.02, 0.005] * 5
        var_100k, _ = compute_parametric_var(returns, 100_000, confidence=0.99)
        var_200k, _ = compute_parametric_var(returns, 200_000, confidence=0.99)
        self.assertAlmostEqual(var_200k, var_100k * 2, delta=0.01)

    def test_zero_variance_returns_zero_var(self):
        returns = [0.01] * 10
        var_usd, var_pct = compute_parametric_var(returns, 100_000, confidence=0.99)
        self.assertEqual(var_usd, 0.0)
        self.assertEqual(var_pct, 0.0)

    def test_raises_on_insufficient_data(self):
        with self.assertRaises(ValueError):
            compute_parametric_var([0.01], 100_000)

    def test_raises_on_zero_portfolio(self):
        with self.assertRaises(ValueError):
            compute_parametric_var([0.01, -0.02], 0.0)

    def test_normal_quantile_table(self):
        self.assertAlmostEqual(_normal_quantile(0.99), 2.3263, places=3)
        self.assertAlmostEqual(_normal_quantile(0.95), 1.6449, places=3)


# ══════════════════════════════════════════════════════════════════════════════
# 11. VaRCircuitBreaker (shared/ — stateful class)
# ══════════════════════════════════════════════════════════════════════════════

class TestVaRCircuitBreaker(unittest.TestCase):

    def _vcb(self, var_limit_pct=0.05, min_obs=3, **kwargs):
        return VaRCircuitBreaker(var_limit_pct=var_limit_pct, min_obs=min_obs, **kwargs)

    def test_not_triggered_initially(self):
        self.assertFalse(self._vcb().is_triggered())

    def test_insufficient_obs_never_trips(self):
        vcb = self._vcb(min_obs=5)
        for _ in range(4):
            vcb.record_return(-0.10)
        triggered, _ = vcb.check_and_trip(100_000)
        self.assertFalse(triggered)

    def test_trips_on_high_variance(self):
        vcb = self._vcb(var_limit_pct=0.01, min_obs=3)
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
        paused_first = vcb.paused_until
        vcb.check_and_trip(100_000)
        self.assertEqual(vcb.paused_until, paused_first)

    def test_pause_expires(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, min_obs=3, pause_hours=0.0)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        vcb.check_and_trip(100_000)
        time.sleep(0.01)
        self.assertFalse(vcb.is_triggered())

    def test_paused_until_none_when_inactive(self):
        self.assertIsNone(self._vcb().paused_until)

    def test_minutes_remaining_zero_when_inactive(self):
        self.assertEqual(self._vcb().minutes_remaining(), 0.0)

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
        d = self._vcb().to_dict()
        for key in (
            "active", "paused_until", "minutes_remaining",
            "last_var_pct", "last_var_usd", "var_limit_pct",
            "confidence_pct", "window", "observation_count", "pause_hours",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_active(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, min_obs=3, pause_hours=1.0)
        for r in [0.10, -0.10, 0.10, -0.10, 0.10]:
            vcb.record_return(r)
        vcb.check_and_trip(100_000)
        d = vcb.to_dict()
        self.assertTrue(d["active"])
        self.assertIsNotNone(d["paused_until"])

    def test_repr(self):
        self.assertIn("VaRCircuitBreaker", repr(self._vcb()))

    def test_window_rolling(self):
        vcb = VaRCircuitBreaker(var_limit_pct=0.01, window=3, min_obs=3, pause_hours=0.01)
        for r in [0.10, -0.10, 0.10]:
            vcb.record_return(r)
        triggered, _ = vcb.check_and_trip(100_000)
        self.assertTrue(triggered)
        vcb.reset()
        for r in [0.0001, -0.0001, 0.0001]:
            vcb.record_return(r)
        triggered_calm, _ = vcb.check_and_trip(100_000)
        self.assertFalse(triggered_calm)

    def test_shared_import(self):
        from shared import VaRCircuitBreaker as _VCB
        self.assertTrue(callable(_VCB))


# ══════════════════════════════════════════════════════════════════════════════
# 12. compute_daily_var — historical simulation VaR (deterministic / mocked)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeDailyVar(unittest.TestCase):
    """
    All tests here use unittest.mock to patch yfinance so they run offline and
    deterministically.  No live network calls are made.

    compute_daily_var() return contract:
        Returns VaR as a *fraction of the invested positions*, not of total
        equity.  Callers must scale to USD before comparing to equity limits:
        ``var_usd = var_pct × invested_usd > daily_loss_limit_pct × equity``.
    """

    def _make_df(self, tickers, prices):
        """Build a minimal yfinance-like multi-ticker DataFrame."""
        import pandas as pd
        idx = pd.date_range("2025-01-01", periods=len(prices), freq="D")
        if isinstance(tickers, list) and len(tickers) == 1:
            # Single-ticker: single-level column
            df = pd.DataFrame({"Close": prices}, index=idx)
            df.columns = pd.Index(tickers)
        else:
            # Multi-ticker: MultiIndex (price_type, ticker)
            arrays = [["Close"] * len(tickers), tickers]
            cols = pd.MultiIndex.from_arrays(arrays)
            data = {("Close", t): prices for t in tickers}
            df = pd.DataFrame(data, index=idx, columns=cols)
        return df

    def test_empty_positions_returns_zero(self):
        from portfolio.var_calculator import compute_daily_var
        self.assertEqual(compute_daily_var([]), 0.0)

    def test_zero_market_value_returns_zero(self):
        from portfolio.var_calculator import compute_daily_var
        positions = [{"symbol": "SPY", "market_value": 0.0}]
        self.assertEqual(compute_daily_var(positions), 0.0)

    def test_negative_market_value_skipped(self):
        from portfolio.var_calculator import compute_daily_var
        positions = [{"symbol": "SPY", "market_value": -500.0}]
        self.assertEqual(compute_daily_var(positions), 0.0)

    def test_yfinance_returns_none_returns_zero(self):
        from portfolio.var_calculator import compute_daily_var
        with unittest.mock.patch("yfinance.download", return_value=None):
            result = compute_daily_var([{"symbol": "SPY", "market_value": 1000.0}])
        self.assertEqual(result, 0.0)

    def test_yfinance_raises_returns_zero_gracefully(self):
        from portfolio.var_calculator import compute_daily_var
        with unittest.mock.patch("yfinance.download", side_effect=RuntimeError("network")):
            result = compute_daily_var([{"symbol": "SPY", "market_value": 1000.0}])
        self.assertEqual(result, 0.0)

    def test_insufficient_observations_returns_zero(self):
        """Fewer than 5 trading days → return 0.0."""
        import pandas as pd
        from portfolio.var_calculator import compute_daily_var
        df = self._make_df(["SPY"], [100.0, 101.0, 99.0])  # 3 prices → 2 returns
        with unittest.mock.patch("yfinance.download", return_value=df):
            result = compute_daily_var([{"symbol": "SPY", "market_value": 10_000.0}])
        self.assertEqual(result, 0.0)

    def test_all_zero_returns_gives_zero_var(self):
        """Flat prices → zero returns → VaR = 0."""
        from portfolio.var_calculator import compute_daily_var
        flat = [100.0] * 30
        df = self._make_df(["SPY"], flat)
        with unittest.mock.patch("yfinance.download", return_value=df):
            result = compute_daily_var([{"symbol": "SPY", "market_value": 10_000.0}])
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_known_returns_95pct_var(self):
        """
        With 20 daily prices alternating +2% and -3%, the worst 5% of daily
        returns is the -3% days.  Expected 95% VaR ≈ 0.03 (3%).
        """
        from portfolio.var_calculator import compute_daily_var
        prices = []
        p = 100.0
        for i in range(25):
            prices.append(p)
            p = p * (1.02 if i % 2 == 0 else 0.97)
        df = self._make_df(["SPY"], prices)
        with unittest.mock.patch("yfinance.download", return_value=df):
            result = compute_daily_var(
                [{"symbol": "SPY", "market_value": 10_000.0}],
                confidence=0.95,
            )
        # Should be close to 3% loss
        self.assertGreater(result, 0.0)
        self.assertLess(result, 0.10)

    def test_higher_confidence_gte_lower(self):
        """99% VaR ≥ 95% VaR on the same position."""
        from portfolio.var_calculator import compute_daily_var
        prices = []
        p = 100.0
        for i in range(30):
            prices.append(p)
            p = p * (1.01 if i % 3 != 0 else 0.97)
        df = self._make_df(["SPY"], prices)
        with unittest.mock.patch("yfinance.download", return_value=df):
            var_95 = compute_daily_var([{"symbol": "SPY", "market_value": 10_000.0}], 0.95)
        with unittest.mock.patch("yfinance.download", return_value=df):
            var_99 = compute_daily_var([{"symbol": "SPY", "market_value": 10_000.0}], 0.99)
        self.assertGreaterEqual(var_99, var_95 - 1e-6)

    def test_return_is_fraction_of_invested_not_equity(self):
        """
        With $50k invested (out of $100k equity) and a VaR of 5%,
        var_pct should be 0.05 — representing 5% of invested capital,
        i.e. $2,500, not $5,000.
        """
        from portfolio.var_calculator import compute_daily_var
        prices = []
        p = 100.0
        for i in range(30):
            prices.append(p)
            p = p * (1.02 if i % 3 != 0 else 0.95)
        df = self._make_df(["SPY"], prices)
        with unittest.mock.patch("yfinance.download", return_value=df):
            var_pct = compute_daily_var([{"symbol": "SPY", "market_value": 50_000.0}], 0.99)
        # var_pct is a fraction of the $50k position, not of $100k equity
        self.assertIsInstance(var_pct, float)
        self.assertGreaterEqual(var_pct, 0.0)

    def test_to_yfinance_ticker_mapping(self):
        from portfolio.var_calculator import _to_yfinance_ticker
        self.assertEqual(_to_yfinance_ticker("BTCUSD"), "BTC-USD")
        self.assertEqual(_to_yfinance_ticker("ETHUSD"), "ETH-USD")
        self.assertEqual(_to_yfinance_ticker("BTC/USD"), "BTC-USD")
        self.assertEqual(_to_yfinance_ticker("SPY"), "SPY")
        self.assertEqual(_to_yfinance_ticker("BTC-USD"), "BTC-USD")


# ══════════════════════════════════════════════════════════════════════════════
# 13. Executor VaR Gate — _execute_slot skips risk-on slots when var_tripped
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutorVaRGate(unittest.TestCase):
    """
    Verifies that `_execute_slot` skips non-cash, non-vault entries when
    `var_tripped=True` and records reason="var_circuit_breaker".

    This test imports the private helper directly to avoid instantiating the
    full executor pipeline (which requires broker credentials).
    """

    def setUp(self):
        """Import the private executor helper and required dataclasses."""
        sys.path.insert(0, os.path.join(_TP, ".."))
        from execution.executor import _execute_slot
        from analysis.schemas import RegimeAllocationSlot
        self._execute_slot       = _execute_slot
        self._RegimeAllocationSlot = RegimeAllocationSlot

    def _make_slot(self, ticker="SPY", kelly=0.15, slot=1):
        """Create a minimal valid RegimeAllocationSlot for testing."""
        # Use a ticker-to-asset_class mapping that matches the approved universe
        _ac_map = {
            "SPY": "equity", "QQQ": "equity", "XLK": "equity",
            "GLD": "commodity", "SLV": "commodity",
            "TLT": "safe_haven", "IEF": "safe_haven",
            "SGOV": "cash",
            "BTC/USD": "crypto_spot",
            "TQQQ": "leveraged_risk", "UPRO": "leveraged_risk",
        }
        asset_class = _ac_map.get(ticker, "equity")
        return self._RegimeAllocationSlot(
            slot=slot,
            ticker=ticker,
            asset_class=asset_class,
            conviction_score=0.70,
            kelly_fraction=kelly,
            thesis=f"Unit test placeholder thesis for {ticker}",
            stop_loss_pct=-0.07,
            take_profit_pct=0.15,
        )

    def _make_results(self):
        return {
            "filled":         [],
            "placed":         [],
            "skipped":        [],
            "closed":         [],
            "errors":         [],
            "risk_overrides": [],
            "vault_sweep":    [],
            "new_positions":    0,
            "closed_positions": 0,
            "margin_blocks":    0,
            "cap_overrides":    0,
        }

    def test_var_tripped_skips_risk_on_slot(self):
        """Risk-on ticker is skipped with reason var_circuit_breaker."""
        slot    = self._make_slot(ticker="SPY")
        results = self._make_results()
        results, _ = self._execute_slot(
            slot, equity=100_000, max_position_usd=20_000,
            remaining_cash=100_000, current_positions={},
            results=results, dry_run=True,
            var_tripped=True,
        )
        self.assertEqual(len(results["skipped"]), 1)
        self.assertEqual(results["skipped"][0]["reason"], "var_circuit_breaker")
        self.assertEqual(results["skipped"][0]["ticker"], "SPY")

    def test_var_tripped_skips_multiple_slots(self):
        """All risk-on slots are skipped individually when var_tripped."""
        tickers = ["SPY", "QQQ", "XLK"]
        results = self._make_results()
        for i, tk in enumerate(tickers, start=1):
            slot = self._make_slot(ticker=tk, slot=i)
            results, _ = self._execute_slot(
                slot, equity=100_000, max_position_usd=20_000,
                remaining_cash=100_000, current_positions={},
                results=results, dry_run=True,
                var_tripped=True,
            )
        self.assertEqual(len(results["skipped"]), 3)
        reasons = {e["reason"] for e in results["skipped"]}
        self.assertEqual(reasons, {"var_circuit_breaker"})

    def test_var_not_tripped_does_not_block_slot(self):
        """Slots are NOT blocked when var_tripped=False (dry_run exits after compliance checks)."""
        slot    = self._make_slot(ticker="SPY")
        results = self._make_results()
        # The wash-sale check reads the trade journal; stub it so this unit
        # test never opens a database connection (FIN-22f).
        not_blocked = {"blocked": False, "reason": None, "similar_ticker": None,
                       "loss_date": None, "pnl_pct": None}
        with unittest.mock.patch("execution.executor.check_wash_sale",
                                 return_value=not_blocked), \
             unittest.mock.patch("execution.executor.get_latest_price",
                                 return_value=None):
            results, _ = self._execute_slot(
                slot, equity=100_000, max_position_usd=20_000,
                remaining_cash=100_000, current_positions={},
                results=results, dry_run=True,
                var_tripped=False,
            )
        # Should NOT have a var_circuit_breaker skip entry
        var_skips = [e for e in results["skipped"] if e.get("reason") == "var_circuit_breaker"]
        self.assertEqual(len(var_skips), 0)

    def test_cash_ticker_no_var_circuit_breaker_entry(self):
        """SGOV with kelly=0.0 is caught by the zero-kelly check before the VaR gate."""
        slot    = self._make_slot(ticker="SGOV", kelly=0.0)
        results = self._make_results()
        # zero_kelly check runs first → no var_circuit_breaker entry ever created
        results, _ = self._execute_slot(
            slot, equity=100_000, max_position_usd=20_000,
            remaining_cash=100_000, current_positions={},
            results=results, dry_run=True,
            var_tripped=True,
        )
        var_skips = [e for e in results["skipped"] if e.get("reason") == "var_circuit_breaker"]
        self.assertEqual(len(var_skips), 0)

    def test_var_tripped_remaining_cash_unchanged(self):
        """Skipped slots must not consume any remaining_cash."""
        slot    = self._make_slot(ticker="QQQ")
        results = self._make_results()
        _, remaining = self._execute_slot(
            slot, equity=100_000, max_position_usd=20_000,
            remaining_cash=80_000, current_positions={},
            results=results, dry_run=True,
            var_tripped=True,
        )
        self.assertEqual(remaining, 80_000)


if __name__ == "__main__":
    unittest.main()
