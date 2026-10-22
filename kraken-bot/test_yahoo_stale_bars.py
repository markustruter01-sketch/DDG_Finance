"""The shared Yahoo bar reader refuses a feed that has stopped updating."""
import time

import alpaca_etf_engine as eng


class _Resp:
    status_code = 200

    def __init__(self, last_ts):
        self._last = last_ts

    def json(self):
        ts = [self._last - 86400 * i for i in (2, 1, 0)]
        q = {k: [1.0, 2.0, 3.0] for k in ("open", "high", "low", "close", "volume")}
        return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [q]}}]}}


def _patch(monkeypatch, last_ts):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(last_ts))
    alerts = []
    import core.degradation_tracker as dt
    monkeypatch.setattr(dt, "record_degradation", lambda **k: alerts.append(k))
    return alerts


def test_fresh_bars_are_returned(monkeypatch):
    alerts = _patch(monkeypatch, time.time() - 3 * 86400)            # a long weekend
    out = eng._yahoo_daily_ohlcv("SPY", days=5)
    assert out["closes"] == [1.0, 2.0, 3.0] and alerts == []


def test_week_old_bars_are_refused_with_an_alert(monkeypatch):
    alerts = _patch(monkeypatch, time.time() - 9 * 86400)
    assert eng._yahoo_daily_ohlcv("SPY", days=5) is None
    assert alerts and alerts[0]["error_type"] == "stale_daily_bars" and "SPY" in alerts[0]["message"]
