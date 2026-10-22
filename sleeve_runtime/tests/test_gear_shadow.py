"""GEAR-V1-G4 shadow: replays the registered rules on fetched bars; no orders."""
import math
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from sleeve_runtime import gear_shadow as gs


def _series(days, drift, vol, seed, px=100.0):
    rng, out = random.Random(seed), []
    for d in days:
        o = px
        px *= math.exp(drift + rng.gauss(0, vol))
        out.append({"day": d, "open": o, "high": max(o, px) * 1.002, "low": min(o, px) * 0.998, "close": px})
    return out


def _fetch_factory(last_day):
    days, d = [], date(2025, 6, 2)
    while d <= last_day:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    bars = {"SPY": _series(days, 0.0006, 0.006, 1), "QQQ": _series(days, 0.0007, 0.008, 2),
            "SSO": _series(days, 0.0012, 0.012, 3, 50), "QLD": _series(days, 0.0014, 0.016, 4, 50)}
    seen = {}

    def fetch(symbols, start):
        seen["symbols"], seen["start"] = symbols, start
        return {s: [b for b in bars[s] if b["day"] >= start] for s in symbols}
    return fetch, seen


def test_waits_until_two_finished_sessions_after_the_start():
    fetch, _ = _fetch_factory(date(2026, 10, 23))
    out = gs.run_gear_shadow(fetch, datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc))   # 17:00 NY, 1 session
    assert out["status"] == "waiting"


def test_replays_g4_and_spy_from_the_start_date():
    fetch, seen = _fetch_factory(date(2026, 12, 4))
    out = gs.run_gear_shadow(fetch, datetime(2026, 12, 4, 22, 0, tzinfo=timezone.utc))
    assert out["status"] == "ok" and out["as_of"] == "2026-12-04" and out["shadow_start"] == "2026-10-23"
    assert seen["symbols"] == ["SPY", "QQQ", "SSO", "QLD"] and seen["start"] == date(2025, 8, 29)   # fixed warm-up
    assert out["gear"] in {"aggressive", "normal", "safe"}
    assert out["g4"]["equity"] > 0 and out["spy"]["equity"] > 0
    assert set(out["gears"]["time_in_gear_pct"]) == {"aggressive", "normal", "safe"}


def test_todays_unfinished_bar_is_not_used():
    fetch, _ = _fetch_factory(date(2026, 12, 4))
    out = gs.run_gear_shadow(fetch, datetime(2026, 12, 4, 15, 0, tzinfo=timezone.utc))    # 10:00 NY
    assert out["as_of"] == "2026-12-03"


def test_alpaca_reader_pages_and_falls_back_to_iex():
    calls = []

    class R:
        def __init__(self, body, ok=True): self.body, self.ok = body, ok
        def raise_for_status(self):
            if not self.ok:
                raise RuntimeError("403")
        def json(self): return self.body

    def get(url, params, timeout, headers):
        calls.append((params["feed"], params.get("page_token")))
        if params["feed"] == "sip":
            return R({}, ok=False)
        if not params.get("page_token"):
            return R({"bars": {"SPY": [{"t": "2026-10-22T04:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5}]},
                      "next_page_token": "p2"})
        return R({"bars": {"SPY": [{"t": "2026-10-23T04:00:00Z", "o": 1.5, "h": 2, "l": 1, "c": 1.8}],
                           "QQQ": [{"t": "2026-10-23T04:00:00Z", "o": 3, "h": 4, "l": 2, "c": 3.5}]}})
    out = gs.alpaca_ohlc_fetcher("k", "s", http_get=get)(["SPY", "QQQ"], date(2026, 10, 1))
    assert calls == [("sip", None), ("iex", None), ("iex", "p2")]
    assert [b["day"] for b in out["SPY"]] == [date(2026, 10, 22), date(2026, 10, 23)]
    assert out["QQQ"][0]["close"] == 3.5
