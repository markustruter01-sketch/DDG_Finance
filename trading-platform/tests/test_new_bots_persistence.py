"""
Regression tests for task #181: persist refreshed pairs leg prices back to
the live-state file so restarts don't show $0 P&L.

Covers:
  _enrich_stale_pairs_kraken  — returns True and updates prices in-place
  _write_live_state           — atomic write; temp file cleaned up on failure
  round-trip persistence      — after enrichment, reloading from disk retains
                                updated current_price_a/b
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLATFORM = os.path.join(_HERE, "..")
_REPO_ROOT = os.path.join(_HERE, "..", "..")
for _p in (_REPO_ROOT, _PLATFORM):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from routes.new_bots import (
    _enrich_stale_pairs_kraken,
    _write_live_state,
    _read_live_state,
)


def _mock_kraken_response(result: dict):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"error": [], "result": result}
    return mock_resp


def _stale_pairs_state(asset_a="ETH", asset_b="BTC", ep_a=1800.0, ep_b=50000.0):
    return {
        "pair_1": {
            "asset_a": asset_a,
            "asset_b": asset_b,
            "leg_a_entry": ep_a,
            "current_price_a": ep_a,
            "leg_b_entry": ep_b,
            "current_price_b": ep_b,
            "leg_a_side": "long",
            "leg_b_side": "short",
            "leg_a_units": 1.0,
            "leg_b_units": 0.036,
            "position_value": 3600.0,
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# _enrich_stale_pairs_kraken
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichStalePairsKraken(unittest.IsolatedAsyncioTestCase):

    async def test_returns_true_and_updates_prices_when_stale(self):
        pairs = _stale_pairs_state()
        ticker = {
            "XETHZUSD": {"c": ["2300.0", "1"]},
            "XXBTZUSD": {"c": ["60000.0", "1"]},
        }

        with patch("routes.new_bots.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=_mock_kraken_response(ticker))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _enrich_stale_pairs_kraken(pairs)

        self.assertTrue(result, "_enrich_stale_pairs_kraken should return True when prices updated")
        self.assertEqual(pairs["pair_1"]["current_price_a"], 2300.0)
        self.assertEqual(pairs["pair_1"]["current_price_b"], 60000.0)

    async def test_returns_false_when_no_stale_prices(self):
        pairs = _stale_pairs_state(ep_a=1800.0)
        pairs["pair_1"]["current_price_a"] = 2000.0
        pairs["pair_1"]["current_price_b"] = 55000.0

        with patch("routes.new_bots.httpx.AsyncClient") as MockClient:
            result = await _enrich_stale_pairs_kraken(pairs)
            MockClient.assert_not_called()

        self.assertFalse(result, "Should return False when no stale positions")

    async def test_returns_false_on_network_error(self):
        pairs = _stale_pairs_state()

        with patch("routes.new_bots.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("timeout"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _enrich_stale_pairs_kraken(pairs)

        self.assertFalse(result, "Should return False on network failure")
        self.assertEqual(pairs["pair_1"]["current_price_a"], 1800.0)
        self.assertEqual(pairs["pair_1"]["current_price_b"], 50000.0)

    async def test_returns_false_on_kraken_api_error(self):
        pairs = _stale_pairs_state()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"error": ["EQuery:Unknown asset pair"], "result": {}}

        with patch("routes.new_bots.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _enrich_stale_pairs_kraken(pairs)

        self.assertFalse(result)

    async def test_pnl_recomputed_after_enrichment(self):
        pairs = _stale_pairs_state(ep_a=1800.0, ep_b=50000.0)
        ticker = {
            "XETHZUSD": {"c": ["2000.0", "1"]},
            "XXBTZUSD": {"c": ["52000.0", "1"]},
        }

        with patch("routes.new_bots.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=_mock_kraken_response(ticker))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await _enrich_stale_pairs_kraken(pairs)

        pos = pairs["pair_1"]
        expected_pnl_a = 1.0 * (2000.0 - 1800.0)
        expected_pnl_b = 0.036 * (50000.0 - 52000.0)
        self.assertAlmostEqual(pos["total_pnl"], round(expected_pnl_a + expected_pnl_b, 2), places=2)


# ══════════════════════════════════════════════════════════════════════════════
# _write_live_state
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteLiveState(unittest.TestCase):

    def test_writes_json_to_disk(self):
        state = {"equity_usd": 123456.0, "positions": {"p1": {"asset_a": "ETH"}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "live_state.json")
            _write_live_state(path, state)
            with open(path) as f:
                on_disk = json.load(f)
        self.assertEqual(on_disk, state)

    def test_no_tmp_file_left_on_success(self):
        state = {"x": 1}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "live_state.json")
            _write_live_state(path, state)
            tmp_files = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], "Orphan .tmp file left after successful write")

    def test_no_tmp_file_left_on_failure(self):
        state = {"x": 1}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "live_state.json")
            with patch("routes.new_bots.os.replace", side_effect=OSError("disk full")):
                _write_live_state(path, state)
            tmp_files = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], "Orphan .tmp file left after failed write")

    def test_write_failure_does_not_raise(self):
        state = {"x": 1}
        with patch("routes.new_bots.os.replace", side_effect=OSError("disk full")):
            with patch("routes.new_bots.tempfile.NamedTemporaryFile"):
                try:
                    _write_live_state("/nonexistent/path/state.json", state)
                except Exception as exc:
                    self.fail(f"_write_live_state raised unexpectedly: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# Round-trip persistence: enrichment → write → reload retains updated prices
# ══════════════════════════════════════════════════════════════════════════════

class TestPersistenceRoundTrip(unittest.IsolatedAsyncioTestCase):

    async def test_reloaded_state_has_enriched_prices(self):
        """After a successful Kraken enrichment, prices written to disk survive a reload."""
        pairs = _stale_pairs_state(ep_a=1800.0, ep_b=50000.0)
        live_state = {"positions": pairs}

        ticker = {
            "XETHZUSD": {"c": ["2400.0", "1"]},
            "XXBTZUSD": {"c": ["62000.0", "1"]},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "poseidon_live_state.json")

            with patch("routes.new_bots.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=_mock_kraken_response(ticker))
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                updated = await _enrich_stale_pairs_kraken(pairs)

            self.assertTrue(updated)
            _write_live_state(path, live_state)

            reloaded = _read_live_state(path)

        pos = reloaded["positions"]["pair_1"]
        self.assertEqual(pos["current_price_a"], 2400.0,
                         "current_price_a should be persisted after enrichment")
        self.assertEqual(pos["current_price_b"], 62000.0,
                         "current_price_b should be persisted after enrichment")


if __name__ == "__main__":
    unittest.main()
