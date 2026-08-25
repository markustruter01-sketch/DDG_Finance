"""
Tests for the Kraken open-position P&L enrichment helpers added to
trading-platform/routes/kraken.py (task #175).

These helpers fix the startup timing issue where write_live_state() fires
before the WebSocket feed connects, leaving current_price == entry_price
and thus unrealized_pnl_usd == 0.0 for all open positions.

Tests:
  _recompute_pnl       — always-on in-place recalc from entry/current price
  _match_kraken_pair   — maps ccxt-style symbols to Kraken internal pair keys
  _enrich_stale_positions — async live-price fetch and P&L recomputation
"""

import asyncio
import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLATFORM = os.path.join(_HERE, "..")
_REPO_ROOT = os.path.join(_HERE, "..", "..")
for _p in (_REPO_ROOT, _PLATFORM):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from routes.kraken import _recompute_pnl, _match_kraken_pair, _enrich_stale_positions


# ══════════════════════════════════════════════════════════════════════════════
# _recompute_pnl
# ══════════════════════════════════════════════════════════════════════════════

class TestRecomputePnl(unittest.TestCase):

    def _pos(self, side, entry, current, size, pnl=0.0):
        return {
            "side": side,
            "entry_price": entry,
            "current_price": current,
            "size_usd": size,
            "unrealized_pnl_usd": pnl,
            "unrealized_pnl_pct": 0.0,
        }

    def test_long_profit(self):
        pos = self._pos("long", 100.0, 110.0, 1000.0)
        _recompute_pnl([pos])
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], 100.0, places=2)
        self.assertAlmostEqual(pos["unrealized_pnl_pct"], 10.0, places=2)

    def test_long_loss(self):
        pos = self._pos("long", 100.0, 90.0, 1000.0)
        _recompute_pnl([pos])
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], -100.0, places=2)

    def test_short_profit(self):
        pos = self._pos("short", 100.0, 90.0, 1000.0)
        _recompute_pnl([pos])
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], 100.0, places=2)

    def test_short_loss(self):
        pos = self._pos("short", 100.0, 110.0, 1000.0)
        _recompute_pnl([pos])
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], -100.0, places=2)

    def test_stale_startup_state_produces_zero(self):
        pos = self._pos("long", 1800.0, 1800.0, 5000.0)
        _recompute_pnl([pos])
        self.assertEqual(pos["unrealized_pnl_usd"], 0.0)

    def test_zero_entry_price_skipped(self):
        pos = self._pos("long", 0.0, 100.0, 1000.0, pnl=42.0)
        _recompute_pnl([pos])
        self.assertEqual(pos["unrealized_pnl_usd"], 42.0)

    def test_zero_size_usd_skipped(self):
        pos = self._pos("long", 100.0, 110.0, 0.0, pnl=99.0)
        _recompute_pnl([pos])
        self.assertEqual(pos["unrealized_pnl_usd"], 99.0)

    def test_multiple_positions(self):
        positions = [
            self._pos("long",  100.0, 110.0, 1000.0),
            self._pos("short", 200.0, 190.0, 2000.0),
        ]
        _recompute_pnl(positions)
        self.assertAlmostEqual(positions[0]["unrealized_pnl_usd"], 100.0, places=2)
        self.assertAlmostEqual(positions[1]["unrealized_pnl_usd"], 100.0, places=2)


# ══════════════════════════════════════════════════════════════════════════════
# _match_kraken_pair
# ══════════════════════════════════════════════════════════════════════════════

class TestMatchKrakenPair(unittest.TestCase):

    def _map(self):
        return {
            "XETHZUSD": 2300.0,
            "XXBTZUSD": 78000.0,
            "SOLUSD":   150.0,
            "LINKUSD":  14.5,
            "XDGUSDT":  0.15,
        }

    def test_eth_usd(self):
        self.assertEqual(_match_kraken_pair("ETH/USD", self._map()), 2300.0)

    def test_btc_usd_alias(self):
        self.assertEqual(_match_kraken_pair("BTC/USD", self._map()), 78000.0)

    def test_sol_usd(self):
        self.assertEqual(_match_kraken_pair("SOL/USD", self._map()), 150.0)

    def test_link_usd(self):
        self.assertEqual(_match_kraken_pair("LINK/USD", self._map()), 14.5)

    def test_missing_symbol_returns_none(self):
        self.assertIsNone(_match_kraken_pair("ADA/USD", self._map()))

    def test_empty_price_map(self):
        self.assertIsNone(_match_kraken_pair("ETH/USD", {}))

    def test_symbol_without_slash(self):
        price_map = {"ETHUSD": 2300.0}
        result = _match_kraken_pair("ETHUSD", price_map)
        self.assertEqual(result, 2300.0)


# ══════════════════════════════════════════════════════════════════════════════
# _enrich_stale_positions (async)
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichStalePositions(unittest.IsolatedAsyncioTestCase):

    def _make_stale_position(self, symbol, side, entry, size):
        return {
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "current_price": entry,
            "size_usd": size,
            "unrealized_pnl_usd": 0.0,
            "unrealized_pnl_pct": 0.0,
        }

    def _mock_ticker_response(self, result: dict):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"error": [], "result": result}
        return mock_resp

    async def test_stale_eth_short_gets_live_price(self):
        pos = self._make_stale_position("ETH/USD", "short", 1800.0, 5000.0)
        ticker_result = {"XETHZUSD": {"c": ["2300.0", "1"]}}

        with patch("routes.kraken.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=self._mock_ticker_response(ticker_result))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await _enrich_stale_positions([pos])

        self.assertEqual(pos["current_price"], 2300.0)
        expected_pnl = (1800.0 - 2300.0) / 1800.0 * 5000.0
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], round(expected_pnl, 2), places=2)

    async def test_stale_btc_long_gets_live_price(self):
        pos = self._make_stale_position("BTC/USD", "long", 50000.0, 10000.0)
        ticker_result = {"XXBTZUSD": {"c": ["78000.0", "1"]}}

        with patch("routes.kraken.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=self._mock_ticker_response(ticker_result))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await _enrich_stale_positions([pos])

        self.assertEqual(pos["current_price"], 78000.0)
        expected_pnl = (78000.0 - 50000.0) / 50000.0 * 10000.0
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], round(expected_pnl, 2), places=2)

    async def test_non_stale_position_not_fetched(self):
        pos = {
            "symbol": "ETH/USD", "side": "long",
            "entry_price": 1800.0, "current_price": 1900.0,
            "size_usd": 5000.0, "unrealized_pnl_usd": 277.78,
        }
        with patch("routes.kraken.httpx.AsyncClient") as MockClient:
            await _enrich_stale_positions([pos])
            MockClient.assert_not_called()

        self.assertEqual(pos["current_price"], 1900.0)
        self.assertAlmostEqual(pos["unrealized_pnl_usd"], 277.78, places=2)

    async def test_network_error_degrades_gracefully(self):
        pos = self._make_stale_position("ETH/USD", "long", 1800.0, 5000.0)
        original_pnl = pos["unrealized_pnl_usd"]

        with patch("routes.kraken.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("network error"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await _enrich_stale_positions([pos])

        self.assertEqual(pos["unrealized_pnl_usd"], original_pnl)

    async def test_kraken_api_error_response_skipped(self):
        pos = self._make_stale_position("ETH/USD", "long", 1800.0, 5000.0)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"error": ["EQuery:Unknown asset pair"], "result": {}}

        with patch("routes.kraken.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await _enrich_stale_positions([pos])

        self.assertEqual(pos["unrealized_pnl_usd"], 0.0)
        self.assertEqual(pos["current_price"], 1800.0)

    async def test_empty_positions_list(self):
        with patch("routes.kraken.httpx.AsyncClient") as MockClient:
            await _enrich_stale_positions([])
            MockClient.assert_not_called()


if __name__ == "__main__":
    unittest.main()
