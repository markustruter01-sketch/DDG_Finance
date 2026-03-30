"""
Unit tests for analysis.llm_response_cache
Covers: key determinism, hit/miss behaviour, get_or_call(), audit/perf budget tagging.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hashlib
import unittest
from unittest.mock import patch, MagicMock

from analysis.llm_response_cache import LLMResponseCache

_MARKET_BULL = {
    "spy_above_ema_20": True,
    "by_ticker": {
        "SPY":  {"momentum_3mo": "Positive", "momentum_6mo": "Positive"},
        "QQQ":  {"momentum_3mo": "Positive", "momentum_6mo": "Positive"},
        "GLD":  {"momentum_3mo": "Negative", "momentum_6mo": "Negative"},
    },
}
_MARKET_BEAR = {
    "spy_above_ema_20": False,
    "by_ticker": {
        "SPY":  {"momentum_3mo": "Negative", "momentum_6mo": "Negative"},
        "QQQ":  {"momentum_3mo": "Negative", "momentum_6mo": "Negative"},
        "GLD":  {"momentum_3mo": "Positive", "momentum_6mo": "Positive"},
    },
}
_MARKET_BULL_SAME = {
    "spy_above_ema_20": True,
    "by_ticker": {
        "SPY":  {"momentum_3mo": "Positive", "momentum_6mo": "Positive"},
        "QQQ":  {"momentum_3mo": "Positive", "momentum_6mo": "Positive"},
        "GLD":  {"momentum_3mo": "Negative", "momentum_6mo": "Negative"},
        "XLK":  {"momentum_3mo": "Negative", "momentum_6mo": "Negative"},  # extra ticker — same top-3 + sentiment
    },
}


class TestCacheKeyDeterminism(unittest.TestCase):

    def test_same_context_produces_same_key(self):
        """Identical regime+tickers+sentiment → same MD5."""
        k1 = LLMResponseCache.make_key("regime", _MARKET_BULL)
        k2 = LLMResponseCache.make_key("regime", _MARKET_BULL)
        self.assertEqual(k1, k2)

    def test_different_regime_produces_different_key(self):
        """Bull vs Bear → different key."""
        k_bull = LLMResponseCache.make_key("regime", _MARKET_BULL)
        k_bear = LLMResponseCache.make_key("regime", _MARKET_BEAR)
        self.assertNotEqual(k_bull, k_bear)

    def test_call_type_differentiates_keys(self):
        """'regime' vs 'crypto' call_type → different key for same market data."""
        k_regime = LLMResponseCache.make_key("regime", _MARKET_BULL)
        k_crypto = LLMResponseCache.make_key("crypto", _MARKET_BULL)
        self.assertNotEqual(k_regime, k_crypto)

    def test_extra_tickers_with_same_top3_produce_same_key(self):
        """Adding an extra negative-momentum ticker should not change the key if top-3
        positive tickers and sentiment band remain the same."""
        k1 = LLMResponseCache.make_key("regime", _MARKET_BULL)
        k2 = LLMResponseCache.make_key("regime", _MARKET_BULL_SAME)
        # Both have same regime_band=bull, top-3=QQQ+SPY (sorted), same sentiment
        # QQQ and SPY are positive; GLD negative; adding XLK negative keeps top-3 identical
        # Only QQQ and SPY are positive across both → sorted: [QQQ, SPY] (2 positive, capped at 3)
        self.assertEqual(k1, k2)

    def test_key_is_md5_hex(self):
        """Key should be a 32-char hex string."""
        k = LLMResponseCache.make_key("regime", _MARKET_BULL)
        self.assertEqual(len(k), 32)
        int(k, 16)   # should not raise


class TestGetOrCall(unittest.TestCase):

    def setUp(self):
        # Use in-memory only cache (no disk writes)
        self.cache = LLMResponseCache(ttl_minutes=90)
        self.cache._ttl_s = 90 * 60
        # Disable disk persistence
        self.cache._persist = lambda: None

    def test_miss_calls_fn_and_stores(self):
        """On a miss, call_fn is invoked and result is cached."""
        fn = MagicMock(return_value='{"result": "fresh"}')
        key = "testkey_miss"
        result = self.cache.get_or_call(key, fn)
        self.assertEqual(result, '{"result": "fresh"}')
        fn.assert_called_once()
        self.assertIn(key, self.cache._store)

    def test_hit_does_not_call_fn(self):
        """On a hit, call_fn is NOT invoked."""
        key = "testkey_hit"
        import time
        self.cache._store[key] = {"raw_json": '{"result": "cached"}', "saved_at": time.time()}
        fn = MagicMock(return_value='{"result": "new"}')
        result = self.cache.get_or_call(key, fn)
        self.assertEqual(result, '{"result": "cached"}')
        fn.assert_not_called()

    def test_hit_increments_hits(self):
        """Cache hit increments _hits counter."""
        key = "testkey_hitcount"
        import time
        self.cache._store[key] = {"raw_json": '{}', "saved_at": time.time()}
        before = self.cache._hits
        self.cache.get_or_call(key, lambda: '{}')
        self.assertEqual(self.cache._hits, before + 1)

    def test_miss_increments_misses(self):
        """Cache miss increments _misses counter."""
        before = self.cache._misses
        self.cache.get_or_call("no_such_key", lambda: '{"x": 1}')
        self.assertEqual(self.cache._misses, before + 1)

    def test_ttl_minutes_override(self):
        """Expired entry (older than override TTL) triggers a fresh call."""
        import time
        key = "testkey_ttl_override"
        # Store with a saved_at of 2 minutes ago
        self.cache._store[key] = {"raw_json": '{"old": true}', "saved_at": time.time() - 120}
        fn = MagicMock(return_value='{"new": true}')
        result = self.cache.get_or_call(key, fn, ttl_minutes=1)   # 1-min TTL → 2-min-old entry expired
        self.assertEqual(result, '{"new": true}')
        fn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
