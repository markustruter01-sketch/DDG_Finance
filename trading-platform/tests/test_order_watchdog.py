from datetime import datetime, timedelta, timezone

from core import order_watchdog as wd

UTC = timezone.utc


def _every(start, minutes, n):
    return [start + timedelta(minutes=minutes * i) for i in range(n)]


def test_vault_loop_pattern_is_caught_as_sustained():
    # 21 Oct 2026: a BIL + VOO pair every 15 min from 13:30 UTC (09:30 NY).
    loop = [t + timedelta(seconds=s) for t in _every(datetime(2026, 10, 21, 13, 30, tzinfo=UTC), 15, 26)
            for s in (0, 1)]
    now = datetime(2026, 10, 21, 17, 5, tzinfo=UTC)          # 13:05 NY
    seen = [t for t in loop if t <= now]
    rules = {f["rule"] for f in wd.evaluate("oracle", seen, now)}
    assert rules == {"sustained"}                            # 10:00, 11:00, 12:00 NY hours each 8


def test_one_rebalance_burst_is_not_sustained_and_within_daily_limit():
    # 12 Oct 2026: spy_qqq_trend placed 104 orders on its rebalance day.
    burst = _every(datetime(2026, 10, 12, 20, 30, tzinfo=UTC), 0.25, 104)   # 16:30 NY, ~26 min
    now = datetime(2026, 10, 12, 22, 5, tzinfo=UTC)
    assert wd.evaluate("spy_qqq_trend", burst, now) == []


def test_daily_limit():
    orders = _every(datetime(2026, 10, 20, 13, 30, tzinfo=UTC), 1, 31)
    now = datetime(2026, 10, 20, 14, 5, tzinfo=UTC)
    out = wd.evaluate("jerome_macro", orders, now)
    assert out == [{"bot_id": "jerome_macro", "rule": "daily", "orders_today": 31, "limit": 30}]


def test_yesterdays_orders_do_not_count():
    old = _every(datetime(2026, 10, 20, 13, 30, tzinfo=UTC), 1, 100)
    now = datetime(2026, 10, 21, 14, 5, tzinfo=UTC)
    assert wd.evaluate("jerome_macro", old, now) == []


def test_alerts_and_only_resolves_when_every_account_is_clean(monkeypatch):
    import core.degradation_tracker as dt
    recorded, resolved = [], []
    monkeypatch.setattr(dt, "record_degradation", lambda **k: recorded.append(k))
    monkeypatch.setattr(dt, "mark_resolved", lambda *a, **k: resolved.append(a[1]))
    now = datetime(2026, 10, 21, 17, 5, tzinfo=UTC)
    loop = _every(datetime(2026, 10, 21, 13, 30, tzinfo=UTC), 7.5, 28)
    monkeypatch.setattr(wd, "_today_submissions",
                        lambda bot, _now: loop if bot == "oracle" else [])
    report = wd.run_watchdog(now)
    assert report["oracle"]["status"] == "alert" and report["jerome_macro"]["status"] == "ok"
    assert [r["error_type"] for r in recorded] == ["order_rate_sustained"]
    assert resolved == ["order_rate_daily"]                  # sustained stays open: oracle still hits it


def test_unreadable_account_blocks_resolving(monkeypatch):
    import core.degradation_tracker as dt
    resolved = []
    monkeypatch.setattr(dt, "record_degradation", lambda **k: None)
    monkeypatch.setattr(dt, "mark_resolved", lambda *a, **k: resolved.append(a[1]))

    def read(bot, _now):
        if bot == "oracle":
            raise RuntimeError("broker down")
        return []
    monkeypatch.setattr(wd, "_today_submissions", read)
    report = wd.run_watchdog(datetime(2026, 10, 21, 17, 5, tzinfo=UTC))
    assert report["oracle"]["status"] == "unknown" and resolved == []
