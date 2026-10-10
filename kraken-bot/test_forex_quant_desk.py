from __future__ import annotations

import pytest

import forex_quant_desk as qd


def _candles(closes, *, wick=0.001):
    return [
        {
            "time": f"day-{i}",
            "complete": True,
            "mid": {"o": str(c), "h": str(c + wick), "l": str(c - wick), "c": str(c)},
        }
        for i, c in enumerate(closes)
    ]


def _trend(start, step, n=qd.CANDLES_REQUESTED):
    return [start + step * i for i in range(n)]


def test_uptrend_gives_long_baseline_with_stop_below_close():
    row = qd.signal_row("EUR_USD", _candles(_trend(1.0, 0.001)), spread=0.0001)
    call = qd.baseline_call(row)
    assert row["trend"] == "up" and row["momentum_return"] > 0
    assert call["direction"] == "long"
    assert call["stop_price"] == pytest.approx(row["close"] - 2.0 * row["atr"])
    assert call["stop_price"] < row["close"]


def test_downtrend_gives_short_baseline_with_stop_above_close():
    row = qd.signal_row("USD_JPY", _candles(_trend(150.0, -0.1)))
    call = qd.baseline_call(row)
    assert call["direction"] == "short"
    assert call["stop_price"] > row["close"]


def test_trend_and_momentum_disagree_gives_flat():
    # Low base, a jump, then a 63-day drift down that stays above the 100-day average.
    closes = [1.0] * 66 + [2.0] + _trend(2.0 - 0.1 / 63, -0.1 / 63, 63)
    row = qd.signal_row("GBP_USD", _candles(closes))
    assert row["trend"] == "up" and row["momentum_return"] < 0
    assert qd.baseline_call(row)["direction"] == "flat"
    assert qd.baseline_call(row)["stop_price"] is None


def test_atr_uses_true_range_including_gaps():
    closes = [1.0] * 120 + [1.1] * 10
    row = qd.signal_row("AUD_USD", _candles(closes, wick=0.0))
    # One 0.1 gap inside the last 14 days, zero range elsewhere.
    assert row["atr"] == pytest.approx(0.1 / 14)


def test_too_few_candles_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="need 101"):
        qd.signal_row("NZD_USD", _candles(_trend(1.0, 0.001, 50)))


def test_carry_reads_oanda_financing_or_reports_unavailable():
    closes = _trend(1.0, 0.001)
    ok = qd.signal_row("EUR_USD", _candles(closes), financing={"longRate": "-0.031", "shortRate": "0.012"})
    missing = qd.signal_row("EUR_USD", _candles(closes))
    assert ok["carry"] == {"long_rate": -0.031, "short_rate": 0.012, "status": "ok"}
    assert missing["carry"]["status"] == "unavailable"
    assert missing["calendar"] == "unavailable" and missing["positioning"] == "unavailable"


class _Client:
    def __init__(self, fail_pair=None):
        self.fail_pair = fail_pair
        self.calls = []

    def tradeable_instruments(self):
        self.calls.append("instruments")
        return [{"name": p, "financing": {"longRate": "0.01", "shortRate": "-0.02"}} for p in qd.FOREX_PAIRS]

    def daily_candles(self, pair, *, count):
        self.calls.append(("candles", pair, count))
        if pair == self.fail_pair:
            raise RuntimeError("OANDA practice API returned HTTP 503")
        return _candles(_trend(1.0, 0.001))

    def current_bid_ask(self, pair):
        self.calls.append(("quote", pair))
        return {"spread": 0.0002}


def test_sheet_covers_all_pairs_and_one_failure_does_not_stop_others():
    client = _Client(fail_pair="USD_CAD")
    sheet = qd.build_signal_sheet(client)
    assert [r["pair"] for r in sheet["rows"]] == list(qd.FOREX_PAIRS)
    failed = next(r for r in sheet["rows"] if r["pair"] == "USD_CAD")
    assert "503" in failed["error"] and failed["baseline"]["direction"] == "flat"
    assert sum(1 for r in sheet["rows"] if "error" not in r) == 6
    assert all(r["carry"]["status"] == "ok" for r in sheet["rows"] if "error" not in r)
    # Read-only: only the three read methods are ever called.
    assert {c if isinstance(c, str) else c[0] for c in client.calls} == {"instruments", "candles", "quote"}
