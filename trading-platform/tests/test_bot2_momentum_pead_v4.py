from datetime import date, timedelta

import pytest

from core.equity_universe import set_screen_data
from analysis.bot2_momentum_pead_v4 import (
    Bar,
    Series,
    _sgov_daily_return,
    build_event_schedule,
    build_momentum_cache,
    screen_universe_current,
    simulate_equal_weight_universe,
    simulate_momentum,
    simulate_true_rotation,
    _rebalance_days,
)
from analysis.bot2_momentum_rank500_backtest import (
    BACKTEST_START,
    TARGET_UNIVERSE,
    _latest_complete_month_end,
    _load_assets,
    _load_compact_panel,
)


def _series(symbol: str, count: int = 420, slope: float = 0.20) -> Series:
    first = date(2018, 1, 1)
    bars = []
    for index in range(count):
        day = first + timedelta(days=index)
        close = 100.0 + index * slope + (index % 7) * 0.05
        bars.append(Bar(day, close, close + 1, close - 1, close, 1_000_000))
    return Series(symbol, bars)


def _parameter_series(symbol: str, count: int = 800, late: bool = False) -> Series:
    first = date(2018, 1, 1)
    bars = []
    for index in range(count):
        day = first + timedelta(days=index)
        if late:
            close = 100.0 + max(0, index - 500) * 0.8
        else:
            close = 100.0 + min(index, 520) * 0.8
        bars.append(Bar(day, close, close + 1, close - 1, close, 1_000_000))
    return Series(symbol, bars)


def _parameter_universe() -> dict[str, Series]:
    return {
        **{
            f"OLD{index:02d}": _parameter_series(f"OLD{index:02d}")
            for index in range(20)
        },
        "LATE": _parameter_series("LATE", late=True),
    }


def _momentum_result(
    data: dict[str, Series],
    *,
    lookback_bars: int = 252,
    top_n: int = 20,
    rebalance_frequency: str = "monthly",
) -> dict[str, object]:
    cache = build_momentum_cache(
        data,
        set(data),
        universe_size=500,
        end=date(2020, 1, 31),
        lookback_bars=lookback_bars,
        skip_bars=22,
        top_n=top_n,
        rebalance_frequency=rebalance_frequency,
    )
    return simulate_momentum(
        data,
        set(data),
        universe_size=500,
        start=date(2019, 1, 1),
        end=date(2020, 1, 31),
        ranking_cache=cache,
        lookback_bars=lookback_bars,
        skip_bars=22,
        top_n=top_n,
        rebalance_frequency=rebalance_frequency,
    )


def test_default_arguments_match_explicit_defaults():
    data = {"AAA": _series("AAA"), "BBB": _series("BBB")}
    implicit = build_momentum_cache(
        data, set(data), universe_size=500, end=date(2019, 3, 31)
    )
    explicit = build_momentum_cache(
        data,
        set(data),
        universe_size=500,
        end=date(2019, 3, 31),
        lookback_bars=252,
        skip_bars=22,
        top_n=20,
        rebalance_frequency="monthly",
    )

    assert dict(implicit) == dict(explicit)
    assert implicit.lookback_bars == 252
    assert implicit.skip_bars == 22
    assert implicit.top_n == 20
    assert implicit.rebalance_frequency == "monthly"
    assert _momentum_result(data) == _momentum_result(
        data,
        lookback_bars=252,
        top_n=20,
        rebalance_frequency="monthly",
    )


def test_default_volatility_arguments_keep_the_unscaled_result():
    data = _parameter_universe()
    implicit = _momentum_result(data)
    explicit = simulate_momentum(
        data,
        set(data),
        universe_size=500,
        start=date(2019, 1, 1),
        end=date(2020, 1, 31),
        ranking_cache=build_momentum_cache(
            data,
            set(data),
            universe_size=500,
            end=date(2020, 1, 31),
        ),
        target_volatility=None,
        realized_volatility_window=126,
    )

    assert implicit["sharpe"] == explicit["sharpe"]
    assert implicit["return"] == explicit["return"]
    assert implicit["max_drawdown"] == explicit["max_drawdown"]
    assert explicit["average_multiplier"] == 1.0
    assert explicit["minimum_multiplier"] == 1.0
    assert explicit["scaling_fallbacks"] == 0


def test_experiment_18_default_sharpe_reproduces_exactly():
    assets, candidates = _load_assets()
    end = _latest_complete_month_end()
    series = _load_compact_panel(candidates, end)
    panel_symbols = set(series) & candidates
    set_screen_data(assets, series)
    ranking_cache = build_momentum_cache(
        series,
        panel_symbols,
        TARGET_UNIVERSE,
        end,
        lookback_bars=252,
        skip_bars=22,
        top_n=20,
        rebalance_frequency="monthly",
    )

    result = simulate_momentum(
        series,
        panel_symbols,
        TARGET_UNIVERSE,
        BACKTEST_START,
        end,
        ranking_cache,
        lookback_bars=252,
        skip_bars=22,
        top_n=20,
        rebalance_frequency="monthly",
        target_volatility=None,
        realized_volatility_window=126,
        idle_capital="cash",
    )

    assert result["sharpe"] == 0.7016876886753177


def test_sgov_idle_capital_changes_result(monkeypatch):
    data = _parameter_universe()
    sgov = _series("SGOV", count=800, slope=0.02)
    monkeypatch.setattr(
        "analysis.bot2_momentum_pead_v4._load_sgov_series",
        lambda end: sgov,
    )
    cache = build_momentum_cache(
        data,
        set(data),
        universe_size=500,
        end=date(2020, 1, 31),
    )

    cash_result = simulate_momentum(
        data,
        set(data),
        universe_size=500,
        start=date(2019, 1, 1),
        end=date(2020, 1, 31),
        ranking_cache=cache,
        idle_capital="cash",
    )
    sgov_result = simulate_momentum(
        data,
        set(data),
        universe_size=500,
        start=date(2019, 1, 1),
        end=date(2020, 1, 31),
        ranking_cache=cache,
        idle_capital="sgov",
    )

    assert sgov_result["idle_interest_earned"] > 0
    assert sgov_result["return"] != cash_result["return"]


def test_sgov_before_first_stored_bar_earns_zero():
    sgov = Series(
        "SGOV",
        [
            Bar(date(2020, 6, 1), 100, 100, 100, 100, 1),
            Bar(date(2020, 6, 2), 100, 100, 100, 101, 1),
        ],
    )

    assert _sgov_daily_return(sgov, date(2020, 5, 29)) == 0.0
    assert _sgov_daily_return(sgov, date(2020, 6, 1)) == 0.0
    assert _sgov_daily_return(sgov, date(2020, 6, 2)) == pytest.approx(0.01)


def test_target_volatility_changes_result_and_is_capped():
    data = _parameter_universe()
    baseline = _momentum_result(data)
    scaled = simulate_momentum(
        data,
        set(data),
        universe_size=500,
        start=date(2019, 1, 1),
        end=date(2020, 1, 31),
        ranking_cache=build_momentum_cache(
            data,
            set(data),
            universe_size=500,
            end=date(2020, 1, 31),
        ),
        target_volatility=0.001,
        realized_volatility_window=126,
    )

    assert (
        baseline["return"],
        baseline["sharpe"],
        baseline["max_drawdown"],
    ) != (
        scaled["return"],
        scaled["sharpe"],
        scaled["max_drawdown"],
    )
    assert scaled["scaled_rebalances"] > 0
    assert max(scaled["rebalance_multipliers"]) <= 1.0


def test_insufficient_realized_volatility_history_uses_one():
    data = _parameter_universe()
    scaled = simulate_momentum(
        data,
        set(data),
        universe_size=500,
        start=date(2019, 1, 1),
        end=date(2020, 1, 31),
        ranking_cache=build_momentum_cache(
            data,
            set(data),
            universe_size=500,
            end=date(2020, 1, 31),
        ),
        target_volatility=0.12,
        realized_volatility_window=126,
    )

    assert scaled["rebalance_multipliers"][0] == 1.0
    assert scaled["scaling_fallbacks"] >= 1


def test_changed_lookback_changes_result():
    data = _parameter_universe()
    baseline = _momentum_result(data, lookback_bars=252)
    changed = _momentum_result(data, lookback_bars=126)

    assert (
        baseline["return"],
        baseline["sharpe"],
        baseline["max_drawdown"],
    ) != (
        changed["return"],
        changed["sharpe"],
        changed["max_drawdown"],
    )


def test_mismatched_top_n_between_cache_and_simulator_raises():
    data = {"AAA": _series("AAA"), "BBB": _series("BBB")}
    cache = build_momentum_cache(
        data,
        set(data),
        universe_size=500,
        end=date(2019, 3, 31),
        top_n=20,
    )

    with pytest.raises(ValueError, match="top_n mismatch"):
        simulate_momentum(
            data,
            set(data),
            universe_size=500,
            start=date(2019, 2, 1),
            end=date(2019, 3, 31),
            ranking_cache=cache,
            top_n=50,
        )


def test_quarterly_produces_fewer_rebalances_than_monthly():
    days = [
        date(2019, 1, 2) + timedelta(days=index)
        for index in range(800)
    ]

    monthly = _rebalance_days(days, "monthly")
    quarterly = _rebalance_days(days, "quarterly")

    assert len(monthly) == 27
    assert len(quarterly) == 9
    assert len(quarterly) < len(monthly)


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