from datetime import date, datetime, timezone

import pytest

from research_harness import fetch
from research_harness.harness.store import BarStore

OFFSET = -14400   # New York, daylight time


def _ts(d):   # 09:30 New York on day d, as Yahoo stamps daily bars
    return int(datetime(d.year, d.month, d.day, 13, 30, tzinfo=timezone.utc).timestamp())


def _payload(days, closes, adj, missing=()):
    q = {k: [] for k in ("open", "high", "low", "close", "volume")}
    for i, c in enumerate(closes):
        bad = i in missing
        q["open"].append(None if bad else c - 1)
        q["high"].append(None if bad else c + 1)
        q["low"].append(None if bad else c - 2)
        q["close"].append(None if bad else c)
        q["volume"].append(1000)
    return {"chart": {"result": [{"meta": {"gmtoffset": OFFSET}, "timestamp": [_ts(d) for d in days],
                                  "indicators": {"quote": [q], "adjclose": [{"adjclose": adj}]}}]}}


def test_scales_every_price_by_adjclose_over_close_and_drops_gaps():
    days = [date(2020, 3, 2), date(2020, 3, 3), date(2020, 3, 4)]
    bars = fetch.parse_yahoo_chart(_payload(days, [100, 110, 120], [50, 55, 60], missing={1}),
                                   date(2020, 1, 1), date(2020, 12, 31))
    assert [b["day"] for b in bars] == [date(2020, 3, 2), date(2020, 3, 4)]
    b = bars[0]
    assert b["close"] == 50 and b["open"] == pytest.approx(49.5) and b["high"] == pytest.approx(50.5)
    assert b["low"] == pytest.approx(49.0)


def test_window_is_inclusive_and_dataset_is_written(tmp_path):
    days = [date(2020, 3, d) for d in (2, 3, 4, 5)]
    seen = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return _payload(days, [10, 11, 12, 13], [10, 11, 12, 13])

    def get(url, params, headers, timeout):
        seen["url"], seen["params"] = url, params
        return R()

    store = BarStore(tmp_path / "d")
    m = fetch.fetch_yahoo_chart(store, "y", ["SSO"], "2020-03-03", "2020-03-04", http_get=get, pause=0)
    assert seen["url"].endswith("/SSO") and seen["params"]["events"] == "div,splits"
    assert m["symbols"]["SSO"]["rows"] == 2
    assert [b["day"] for b in store.load("y", "SSO", start=date(2020, 1, 1), end=date(2020, 12, 31))] == [date(2020, 3, 3), date(2020, 3, 4)]


def test_no_rows_is_an_error(tmp_path):
    class R:
        def raise_for_status(self): pass
        def json(self): return _payload([], [], [])
    with pytest.raises(RuntimeError, match="no data for QLD"):
        fetch.fetch_yahoo_chart(BarStore(tmp_path / "d"), "y", ["QLD"], "2020-01-01", "2020-12-31",
                                http_get=lambda *a, **k: R(), pause=0)
