from __future__ import annotations

from datetime import date, timedelta

import pytest

import forex_baseline_backtest as bt


def _bars(closes, *, spread=0.0002, start=date(2010, 1, 4), wick=0.002):
    bars, d = [], start
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        bars.append({"day": d,
                     "bo": o - spread / 2, "bh": max(o, c) + wick - spread / 2, "bl": min(o, c) - wick - spread / 2, "bc": c - spread / 2,
                     "ao": o + spread / 2, "ah": max(o, c) + wick + spread / 2, "al": min(o, c) - wick + spread / 2, "ac": c + spread / 2})
        d += timedelta(days=1)
    return bars


def test_steady_uptrend_goes_long_and_makes_money():
    closes = [1.0 + 0.001 * i for i in range(400)]
    res = bt.run_backtest({"EUR_USD": _bars(closes)})
    s = bt.stats(res["curve"], res["trades"])
    assert res["open_at_end"] == 1  # still long
    assert s["total_return_pct"] > 0
    assert s["max_gross_leverage"] <= bt.GROSS_CAP + 1e-9


def test_crash_through_stop_fills_at_gap_open_and_costs_about_risk():
    closes = [1.0 + 0.001 * i for i in range(200)]
    bars = _bars(closes)
    last = bars[-1]["bc"]
    # Next day gaps 20% down: stop must fill at that day's open, not at the stop price.
    gap = {"day": bars[-1]["day"] + timedelta(days=1), "bo": last * 0.8, "bh": last * 0.8, "bl": last * 0.79,
           "bc": last * 0.79, "ao": last * 0.8, "ah": last * 0.8, "al": last * 0.79, "ac": last * 0.79}
    res = bt.run_backtest({"EUR_USD": bars + [gap]})
    stop_trades = [t for t in res["trades"] if t["reason"] == "stop"]
    assert stop_trades and stop_trades[-1]["r"] < -1.5  # gap loss far beyond 1R is reported, not hidden


def test_max_four_positions_and_usd_base_conversion():
    data = {p: _bars([1.0 + 0.001 * i for i in range(300)]) for p in ["EUR_USD", "GBP_USD", "AUD_USD", "NZD_USD"]}
    data["USD_JPY"] = _bars([100 + 0.1 * i for i in range(300)], spread=0.02, wick=0.2)
    res = bt.run_backtest(data)
    assert res["open_at_end"] == bt.MAX_OPEN
    assert bt.usd_per_unit_move("USD_JPY", 150.0) == pytest.approx(1 / 150)


def test_stats_windows_and_empty_window():
    res = bt.run_backtest({"EUR_USD": _bars([1.0 + 0.001 * i for i in range(300)])})
    assert bt.stats(res["curve"], res["trades"], date(1999, 1, 1), date(1999, 12, 31)) == {"note": "no data in window"}
