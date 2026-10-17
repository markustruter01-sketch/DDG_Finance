"""Tests for the TREND-V1-B shadow job (no broker, no DB)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from research_harness.explore.trend_v1 import UNIVERSE
from sleeve_runtime import trend_shadow as ts


def _bars(days: int, end: date, up: set[str]):
    out = {}
    for s in UNIVERSE:
        series, d, px = [], end - timedelta(days=days * 7 // 5 + 10), 100.0
        while len(series) < days:
            if d.weekday() < 5:
                px *= 1.001 if s in up else 0.999
                px *= 1.004 if len(series) % 2 else 0.996   # some volatility
                series.append({"day": d, "close": round(px, 4)})
            d += timedelta(days=1)
        out[s] = series
    return out


def test_plan_buys_only_trending_etfs_with_stops_and_keeps_vault():
    end = date(2026, 10, 16)
    bars = _bars(300, end, up={"SPY", "GLD", "TLT"})
    last = bars["SPY"][-1]["day"]
    res = ts.compute_plan(bars=bars, positions={"EWT": 50, "BIL": 10, "VOO": 2},
                          equity=100_000, cash=80_000, exclude={"BIL", "VOO"})
    assert set(res["weights"]) == {"SPY", "GLD", "TLT"}
    assert all(w <= 0.30 for w in res["weights"].values())
    assert {s for s, _ in res["buys"]} == {"SPY", "GLD", "TLT"}
    assert res["excluded"] == ["BIL", "VOO"]                     # vault never traded
    # EWT has no bar in the universe data: no price -> left alone, reported
    assert "EWT" in res["skipped"]
    assert {s for s, *_ in res["stops"]} >= {"SPY", "GLD", "TLT"}
    assert res["bar_day"] == last.isoformat()


def test_first_close_of_month_is_a_rebalance_day():
    assert ts.is_rebalance_day(date(2026, 11, 2), date(2026, 10, 30))
    assert not ts.is_rebalance_day(date(2026, 10, 16), date(2026, 10, 15))


def test_run_shadow_never_raises_and_logs_skip():
    def broken(symbols, start):
        raise RuntimeError("feed down")
    assert ts.run_shadow(fetch_bars=broken, account={"equity": 1, "cash": 1}, positions=[],
                         exclude=set(), now=datetime(2026, 10, 18, tzinfo=timezone.utc)) is None


def test_run_shadow_returns_plan():
    bars = _bars(300, date(2026, 10, 16), up={"SPY"})
    res = ts.run_shadow(fetch_bars=lambda s, start: bars, account={"equity": 50_000, "cash": 50_000},
                        positions=[], exclude=set(), now=datetime(2026, 10, 18, tzinfo=timezone.utc))
    assert res and res["buys"] and res["buys"][0][0] == "SPY"


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

    out = ts.alpaca_bar_fetcher(Api())(["SPY", "GLD"], date(2025, 8, 1))
    assert calls == ["sip", "iex"]
    assert out["SPY"] == [{"day": date(2026, 10, 15), "close": 599.0}, {"day": date(2026, 10, 16), "close": 600.5}]
    assert out["GLD"] == []
