from datetime import date, timedelta

from analysis.bot2_commodity_research import (
    COMMODITY_ETFS,
    Bar,
    Series,
    _bounded_weights,
    _event_schedule,
    _random_entry_distribution,
)


def _series(symbol: str, count: int = 140) -> Series:
    bars = []
    current = date(2021, 1, 4)
    while len(bars) < count:
        if current.weekday() < 5:
            price = 100.0 + len(bars) * 0.25
            bars.append(Bar(current, price, price + 1, price - 1, price, 10_000))
        current += timedelta(days=1)
    return Series(symbol, bars)


def test_bounded_weights_respect_floor_cap_and_deployment():
    weights = _bounded_weights(
        {"PDBC": 1.0, "DBC": 2.0, "COMT": 3.0, "DBA": 4.0},
        floor=0.05,
        cap=0.40,
        total=0.80,
    )

    assert sum(weights.values()) == 0.80
    assert all(0.05 <= weight <= 0.40 for weight in weights.values())


def test_event_schedule_branches_on_report_time():
    stock = {"JPM": _series("JPM", 10)}
    events = [
        {"symbol": "JPM", "reported_date": date(2021, 1, 5), "surprise": 1.0, "report_time": "pre-market"},
        {"symbol": "JPM", "reported_date": date(2021, 1, 5), "surprise": 1.0, "report_time": "post-market"},
        {"symbol": "JPM", "reported_date": date(2021, 1, 5), "surprise": 1.0, "report_time": "unknown"},
    ]

    scheduled = _event_schedule(events, stock, "close")

    assert len(scheduled) == 2
    assert scheduled[0]["entry_day"] == date(2021, 1, 5)
    assert scheduled[1]["entry_day"] == date(2021, 1, 6)


def test_random_entry_control_is_deterministic_and_runs_1000_iterations():
    stock = {symbol: _series(symbol) for symbol in ("JPM",)}
    earnings = [
        {
            "symbol": "JPM",
            "reported_date": date(2021, 1, 5),
            "surprise": 1.0,
            "report_time": "pre-market",
        },
        {
            "symbol": "JPM",
            "reported_date": date(2021, 1, 12),
            "surprise": 1.0,
            "report_time": "post-market",
        },
    ]

    first = _random_entry_distribution(
        earnings, stock, date(2021, 1, 4), date(2021, 1, 29), "close"
    )
    second = _random_entry_distribution(
        earnings, stock, date(2021, 1, 4), date(2021, 1, 29), "close"
    )

    assert first["iterations"] == 1000
    assert first == second