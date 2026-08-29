from datetime import date, timedelta

from analysis.bot2_momentum_pead_v4 import (
    Bar,
    Series,
    build_event_schedule,
    build_momentum_cache,
    screen_universe_current,
    simulate_equal_weight_universe,
    simulate_true_rotation,
)


def _series(symbol: str, count: int = 420, slope: float = 0.20) -> Series:
    first = date(2018, 1, 1)
    bars = []
    for index in range(count):
        day = first + timedelta(days=index)
        close = 100.0 + index * slope + (index % 7) * 0.05
        bars.append(Bar(day, close, close + 1, close - 1, close, 1_000_000))
    return Series(symbol, bars)


def test_current_screen_requires_a_bar_on_the_asof_date():
    data = _series("AAA")
    as_of = data.bars[300].day
    data.bars = [bar for bar in data.bars if bar.day != as_of]
    data.__post_init__()

    qualified, observations = screen_universe_current(
        {"AAA": data}, {"AAA"}, as_of, universe_size=500
    )

    assert qualified == set()
    assert observations == {}


def test_event_schedule_assigns_same_cluster_to_adjacent_entry_sessions():
    data = {"AAA": _series("AAA"), "BBB": _series("BBB")}
    calendar = sorted({day for item in data.values() for day in item.days})
    report_day = data["AAA"].bars[300].day
    events = [
        {
            "symbol": "AAA",
            "reported_date": report_day,
            "surprise": 1.0,
            "report_time": "pre-market",
            "source": "alphavantage",
        },
        {
            "symbol": "BBB",
            "reported_date": report_day + timedelta(days=1),
            "surprise": 1.0,
            "report_time": "pre-market",
            "source": "alphavantage",
        },
    ]

    scheduled = build_event_schedule(
        events, data, set(data), universe_size=500, hold_sessions=5, calendar=calendar
    )

    assert len(scheduled) == 2
    assert scheduled[0].cluster_id == scheduled[1].cluster_id
    assert scheduled[0].cluster_first is True
    assert scheduled[1].cluster_first is False


def test_true_rotation_transfers_one_book_and_reenters_after_pead_closes():
    data = {"MOM": _series("MOM", slope=0.40), "AAA": _series("AAA", slope=0.15)}
    symbols = set(data)
    cache = build_momentum_cache(data, symbols, universe_size=500, end=date(2019, 3, 31))
    report_day = data["AAA"].bars[300].day
    events = [
        {
            "symbol": "AAA",
            "reported_date": report_day,
            "surprise": 1.0,
            "report_time": "pre-market",
            "source": "alphavantage",
        }
    ]

    result = simulate_true_rotation(
        data,
        symbols,
        universe_size=500,
        start=data["MOM"].bars[260].day,
        end=data["MOM"].bars[380].day,
        hold_sessions=5,
        ranking_cache=cache,
        events=events,
    )
    actions = [item["action"] for item in result["event_log"]]

    assert "LIQUIDATE_MOMENTUM" in actions
    assert "ENTER_EARNINGS" in actions
    assert "REENTER_MOMENTUM_AFTER_PEAD" in actions
    assert result["days_out_of_momentum"] > 0
    assert result["return_per_out_of_momentum_day"] == (
        result["out_of_momentum_return"] / result["days_out_of_momentum"]
    )
    assert result["max_deployment"] <= 1.0000001


def test_equal_weight_benchmark_pays_costs_without_negative_cash():
    data = {"AAA": _series("AAA"), "BBB": _series("BBB")}
    result = simulate_equal_weight_universe(
        data,
        set(data),
        universe_size=500,
        start=data["AAA"].bars[260].day,
        end=data["AAA"].bars[380].day,
    )

    assert result["cost_paid"] > 0
    assert result["max_deployment"] <= 1.0000001
    assert all(item["cash"] >= -0.0001 for item in result["daily_deployment"])