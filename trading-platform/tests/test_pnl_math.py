"""Unit tests for the canonical compute_unrealized_pnl helper (audit H2)."""
import math
import pytest

from core.pnl_math import compute_unrealized_pnl


class TestLong:
    def test_winner(self):
        # Bought 10 units at $100, now $110 -> +$100
        assert compute_unrealized_pnl("long", 100, 110, 10) == pytest.approx(100.0)

    def test_loser(self):
        # Bought 10 units at $100, now $90 -> -$100
        assert compute_unrealized_pnl("long", 100, 90, 10) == pytest.approx(-100.0)

    def test_breakeven(self):
        assert compute_unrealized_pnl("long", 100, 100, 10) == pytest.approx(0.0)

    def test_with_fees(self):
        # +$100 gross, $5 fees -> +$95 net
        assert compute_unrealized_pnl("long", 100, 110, 10, fees=5.0) == pytest.approx(95.0)


class TestShort:
    def test_winner(self):
        # Sold short 10 units at $100, covered at $90 -> +$100
        assert compute_unrealized_pnl("short", 100, 90, 10) == pytest.approx(100.0)

    def test_loser(self):
        # Sold short 10 units at $100, covered at $110 -> -$100
        assert compute_unrealized_pnl("short", 100, 110, 10) == pytest.approx(-100.0)

    def test_breakeven(self):
        assert compute_unrealized_pnl("short", 100, 100, 10) == pytest.approx(0.0)

    def test_with_fees(self):
        # +$100 gross, $5 fees -> +$95 net
        assert compute_unrealized_pnl("short", 100, 90, 10, fees=5.0) == pytest.approx(95.0)

    def test_short_profit_when_price_falls(self):
        # Regression for the kraken-bot short P&L bug: profitable short must
        # return a POSITIVE pnl (the old formula returned negative on price drop).
        pnl = compute_unrealized_pnl("short", entry=50_000, current=45_000, units=0.1)
        assert pnl > 0
        assert pnl == pytest.approx(500.0)


class TestEdgeCases:
    def test_string_side_case_insensitive(self):
        assert compute_unrealized_pnl("LONG", 100, 110, 10) == pytest.approx(100.0)
        assert compute_unrealized_pnl("Short", 100, 90, 10) == pytest.approx(100.0)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            compute_unrealized_pnl("flat", 100, 110, 10)

    def test_zero_units(self):
        assert compute_unrealized_pnl("long", 100, 110, 0) == pytest.approx(0.0)

    def test_string_inputs_coerced(self):
        # Defensive: the helper coerces numeric strings rather than blowing up
        assert compute_unrealized_pnl("long", "100", "110", "10") == pytest.approx(100.0)
