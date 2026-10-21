"""Tests for the TREND-V1-B shared core and shadow job (no broker, no DB)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from research_harness.explore.trend_v1 import UNIVERSE
from sleeve_runtime import trend_v1b as tv


def _series(days: int, end: date, up: bool):
    series, d, px = [], end - timedelta(days=days * 7 // 5 + 10), 100.0
    while len(series) < days:
        if d.weekday() < 5:
            px *= 1.001 if up else 0.999
            px *= 1.004 if len(series) % 2 else 0.996   # some volatility
            series.append({"day": d, "close": round(px, 4)})
        d += timedelta(days=1)
    while series[-1]["day"] > end:
        series.pop()
    return series


def _bars(days: int, end: date, up: set[str], extra: tuple[str, ...] = ()):
    return {s: _series(days, end, s in up) for s in (*UNIVERSE, *extra)}


def test_plan_buys_only_trending_etfs_with_stops_and_sells_legacy_holdings():
    end = date(2026, 10, 16)
    bars = _bars(300, end, up={"SPY", "GLD", "TLT"}, extra=("EPOL", "EWZ"))
    tp = tv.compute_plan(bars=bars, positions={"EPOL": 263, "EWZ": 106.88, "SPY": 15},
                         equity=100_000, cash=60_000)
    res = tp.summary()
    assert set(res["weights"]) == {"SPY", "GLD", "TLT"}
    assert all(w <= 0.30 for w in res["weights"].values())
    assert sorted(res["sells"]) == [["EPOL", 263], ["EWZ", 106]]       # whole shares planned
    assert res["fractional"] == {"EWZ": 0.88}                          # reported, sold by full exit
    assert {s for s, _ in res["buys"]} == {"SPY", "GLD", "TLT"}
    assert {s for s, *_ in res["stops"]} == {"SPY", "GLD", "TLT"}
    assert res["price_day"] == res["signal_day"] == bars["SPY"][-1]["day"].isoformat()


def test_unpriced_symbol_is_left_alone_and_reported():
    bars = _bars(300, date(2026, 10, 16), up={"SPY"})
    tp = tv.compute_plan(bars=bars, positions={"EWT": 50}, equity=100_000, cash=80_000)
    assert "EWT" in tp.plan.skipped and tp.plan.final_qty["EWT"] == 50


def test_weights_use_the_signal_day_and_sizes_use_the_latest_close():
    bars = _bars(300, date(2026, 11, 4), up=set(UNIVERSE))
    signal = bars["SPY"][-3]["day"]
    tp = tv.compute_plan(bars=bars, positions={}, equity=100_000, cash=100_000, signal_day=signal)
    assert tp.signal_day == signal and tp.price_day == bars["SPY"][-1]["day"]
    spy = next(a for a in tp.plan.stops if a.symbol == "SPY")
    assert spy.stop == round(bars["SPY"][-1]["close"] * 0.8, 2)


def test_sleeve_capital_removes_vault_and_counts_parked_cash():
    positions = [
        {"symbol": "BIL", "qty": 31.9, "market_value": 2900.0},
        {"symbol": "VOO", "qty": 4.1, "market_value": 2600.0},
        {"symbol": "SGOV", "qty": 100, "market_value": 10_000.0},
        {"symbol": "SPY", "qty": 15, "market_value": 11_000.0},
        {"symbol": "XYZ", "qty": 0.0000001, "market_value": 0.0},
    ]
    cap = tv.sleeve_capital({"equity": 100_000, "cash": 5_000}, positions,
                            vault={"BIL", "VOO"}, cash_park={"SGOV"})
    assert cap.equity == 94_500 and cap.cash == 15_000
    assert cap.held == {"SPY": 15} and cap.excluded == ["BIL", "SGOV", "VOO"]


def test_completed_bars_drop_the_forming_session():
    bars = {"SPY": [{"day": date(2026, 11, 2), "close": 1.0}, {"day": date(2026, 11, 3), "close": 2.0}]}
    during = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)      # 10:00 New York
    after = datetime(2026, 11, 3, 21, 30, tzinfo=timezone.utc)      # 16:30 New York
    assert [b["day"] for b in tv.completed_bars(bars, during)["SPY"]] == [date(2026, 11, 2)]
    assert [b["day"] for b in tv.completed_bars(bars, after)["SPY"]] == [date(2026, 11, 2), date(2026, 11, 3)]


def test_run_shadow_never_raises_and_returns_plan():
    def broken(symbols, start):
        raise RuntimeError("feed down")
    assert tv.run_shadow(fetch_bars=broken, account={"equity": 1, "cash": 1}, positions=[],
                         vault=set(), cash_park=set(),
                         now=datetime(2026, 10, 18, tzinfo=timezone.utc)) is None

    bars = _bars(300, date(2026, 10, 16), up={"SPY"}, extra=("EWZ",))
    asked = []

    def fetch(symbols, start):
        asked.extend(symbols)
        return bars

    res = tv.run_shadow(fetch_bars=fetch, account={"equity": 50_000, "cash": 40_000},
                        positions=[{"symbol": "EWZ", "qty": 106.88, "market_value": 4000.0}],
                        vault=set(), cash_park=set(), now=datetime(2026, 10, 18, tzinfo=timezone.utc))
    assert "EWZ" in asked                                   # legacy holding gets a price
    assert res and ["EWZ", 106] in res["sells"] and res["buys"][0][0] == "SPY"


def test_alpaca_fetcher_reads_raw_rows_and_falls_back_to_iex():
    class Bars(list):
        _raw = [{"S": "SPY", "t": "2026-10-16T04:00:00Z", "c": 600.5},
                {"S": "SPY", "t": "2026-10-15T04:00:00Z", "c": 599.0}]

    calls = []

    class Api:
        def get_bars(self, symbols, tf, start, adjustment, feed):
            calls.append(feed)
            if feed == "sip":
                raise PermissionError("subscription does not permit SIP")
            return Bars()

    out = tv.alpaca_bar_fetcher(Api())(["SPY", "GLD"], date(2025, 8, 1))
    assert calls == ["sip", "iex"]
    assert out["SPY"] == [{"day": date(2026, 10, 15), "close": 599.0}, {"day": date(2026, 10, 16), "close": 600.5}]
    assert out["GLD"] == []
