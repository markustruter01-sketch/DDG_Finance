"""Public DDG Finance page extras in the fleet push (holdings, S&P 500 benchmark)."""
from datetime import date, datetime, timezone

from core import ddg_push
from core.ddg_push import PUBLIC_RECORD_BASE_DATE, sp500_benchmark


def _rows(*pairs):
    return [{"day": d, "close": c} for d, c in pairs]


def test_no_benchmark_before_the_record():
    called = []
    assert sp500_benchmark(datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc), lambda *a: called.append(a)) is None
    assert called == []  # no broker read at all before the record


def test_total_return_from_the_base_close_to_the_last_finished_session():
    rows = _rows((PUBLIC_RECORD_BASE_DATE, 600.0), (date(2027, 1, 4), 606.0), (date(2027, 1, 5), 612.0))
    # 5 Jan 22:00 UTC = 17:00 New York: 5 Jan is finished.
    b = sp500_benchmark(datetime(2027, 1, 5, 22, 0, tzinfo=timezone.utc), lambda start, end: rows)
    assert b == {"symbol": "SPY", "base_date": "2026-12-31", "as_of": "2027-01-05", "total_return_pct": 2.0}


def test_todays_unfinished_bar_is_ignored():
    rows = _rows((PUBLIC_RECORD_BASE_DATE, 600.0), (date(2027, 1, 4), 606.0), (date(2027, 1, 5), 300.0))
    # 5 Jan 15:00 UTC = 10:00 New York: 5 Jan's bar is still moving.
    b = sp500_benchmark(datetime(2027, 1, 5, 15, 0, tzinfo=timezone.utc), lambda start, end: rows)
    assert b["as_of"] == "2027-01-04" and b["total_return_pct"] == 1.0


def test_missing_base_close_or_no_session_yet_gives_none():
    now = datetime(2027, 1, 6, 22, 0, tzinfo=timezone.utc)
    assert sp500_benchmark(now, lambda s, e: _rows((date(2027, 1, 4), 606.0), (date(2027, 1, 5), 612.0))) is None
    assert sp500_benchmark(now, lambda s, e: _rows((PUBLIC_RECORD_BASE_DATE, 600.0))) is None


def test_holdings_flattened_per_bot(monkeypatch):
    import core.bot_state as bot_state
    import core.holdings as holdings

    monkeypatch.setattr(bot_state, "get_all_portfolios", lambda: [])
    monkeypatch.setattr(holdings, "holdings_by_bot", lambda portfolios, ids: {
        "oracle": {"items": [{"label": "S&P 500", "pct": 60.0}, {"label": "Cash", "pct": 40.0}]},
        "forex_ai": None,
        "spy_qqq_trend": {"items": [{"label": "Cash", "pct": float("nan")}]},
    })
    assert ddg_push.public_holdings(["oracle", "forex_ai", "spy_qqq_trend"]) == [
        {"bot_id": "oracle", "label": "S&P 500", "pct": 60.0},
        {"bot_id": "oracle", "label": "Cash", "pct": 40.0},
    ]


def test_detail_limits_keep_new_fields():
    detail = {"holdings": [{"bot_id": "oracle", "label": "x" * 80, "pct": 1.0}] * 200, "benchmark": None}
    fitted = ddg_push._fit_detail_limits(detail)
    assert len(fitted["holdings"]) == 150 and len(fitted["holdings"][0]["label"]) == 40
