from datetime import date, timedelta

import pytest

from core.equity_universe import set_screen_data
import analysis.bot2_momentum_pead_v4 as momentum_v4
import analysis.bot2_momentum_rank500_backtest as rank500_backtest
from analysis.bot2_momentum_pead_v4 import (
    Bar,
    MomentumCache,
    Series,
    append_spy_sleeve_exploration_runs,
    _cooldown_expiry_index,
    _cooldown_filtered_weights,
    _is_cooling_down,
    _margin_interest_due,
    _sgov_daily_return,
    _volatility_multiplier,
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
    simulation_options: dict[str, object] | None = None,
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
        **(simulation_options or {}),
    )


def _sleeve_fixture():
    days = [
        date(2020, 1, 2),
        date(2020, 1, 3),
        date(2020, 2, 3),
        date(2020, 2, 4),
    ]
    equity_prices = [100.0, 110.0, 120.0, 130.0]
    spy_prices = [100.0, 120.0, 150.0, 150.0]
    equities = {
        "AAA": Series(
            "AAA",
            [
                Bar(day, price, price, price, price, 1_000_000)
                for day, price in zip(days, equity_prices)
            ],
        )
    }
    spy = Series(
        "SPY",
        [
            Bar(day, price, price, price, price, 1_000_000)
            for day, price in zip(days, spy_prices)
        ],
    )
    cache = MomentumCache(
        lookback_bars=252,
        skip_bars=22,
        top_n=1,
        rebalance_frequency="monthly",
    )
    cache[days[0]] = [("AAA", 0.2, 0.1)]
    cache[days[2]] = [("AAA", 0.2, 0.1)]
    return equities, spy, cache, days


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


def test_changed_cache_parameter_changes_key_and_forces_rebuild(monkeypatch, tmp_path):
    monkeypatch.setattr(rank500_backtest, "CACHE_ROOT", tmp_path)
    calls = []

    def fake_build(series, symbols, universe_size, end, **kwargs):
        calls.append(kwargs.copy())
        cache = MomentumCache(
            lookback_bars=kwargs["lookback_bars"],
            skip_bars=kwargs["skip_bars"],
            top_n=kwargs["top_n"],
            rebalance_frequency=kwargs["rebalance_frequency"],
        )
        cache[date(2019, 1, 2)] = [("AAA", 0.1, 0.2)]
        return cache

    monkeypatch.setattr(rank500_backtest, "build_momentum_cache", fake_build)
    common = {
        "universe_size": 500,
        "lookback_bars": 252,
        "skip_bars": 22,
        "rebalance_frequency": "monthly",
    }
    first, first_key, _, first_hit = rank500_backtest._load_or_build_ranking_cache(
        {},
        {"AAA"},
        date(2020, 1, 31),
        top_n=20,
        **common,
    )
    second, second_key, _, second_hit = rank500_backtest._load_or_build_ranking_cache(
        {},
        {"AAA"},
        date(2020, 1, 31),
        top_n=20,
        **common,
    )
    changed, changed_key, _, changed_hit = (
        rank500_backtest._load_or_build_ranking_cache(
            {},
            {"AAA"},
            date(2020, 1, 31),
            top_n=50,
            **common,
        )
    )

    assert first_key == second_key
    assert first_key != changed_key
    assert first_hit is False
    assert second_hit is True
    assert changed_hit is False
    assert len(calls) == 2
    assert first == second
    assert changed.top_n == 50


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


def test_new_momentum_options_are_off_without_changing_defaults():
    data = _parameter_universe()
    implicit = _momentum_result(data)
    explicit = _momentum_result(
        data,
        simulation_options={
            "multiplier_cap": 1.0,
            "margin_interest_rate": 0.0,
            "maintenance_margin_ratio": None,
            "cooldown_days": 0,
            "spy_sleeve_weight": 0.0,
            "spy_sleeve_leverage": 1.0,
        },
    )

    assert implicit == explicit
    assert explicit["margin_interest_paid"] == 0.0
    assert explicit["margin_calls"] == 0
    assert explicit["borrowed_days"] == 0
    assert explicit["spy_sleeve_weight"] == 0.0
    assert explicit["spy_price_source"] is None


def test_margin_interest_accrues_only_on_borrowed_cash_and_calendar_days():
    assert _margin_interest_due(1_000.0, 0.0625, 3) == 0.0
    assert _margin_interest_due(0.0, 0.0625, 3) == 0.0
    assert _margin_interest_due(-1_000.0, 0.0625, 0) == 0.0
    assert _margin_interest_due(-1_000.0, 0.0625, 3) == pytest.approx(
        1_000.0 * 0.0625 * 3 / 365
    )


def test_volatility_multiplier_respects_an_opt_in_cap():
    curve = [100_000.0]
    for index in range(126):
        daily_return = 0.0001 if index % 2 else -0.0001
        curve.append(curve[-1] * (1 + daily_return))

    multiplier, fallback = _volatility_multiplier(
        curve, 0.12, 126, multiplier_cap=1.5
    )

    assert multiplier == 1.5
    assert fallback is False


def test_cooldown_blocks_through_session_63_and_keeps_the_slot_idle():
    cooldown_until = {"AAA": _cooldown_expiry_index(0, 63)}
    ranked = [("AAA", 0.20, 0.10), ("BBB", 0.10, 0.12)]

    assert _is_cooling_down("AAA", 63, cooldown_until)
    assert _cooldown_filtered_weights(ranked, 2, 63, cooldown_until) == {
        "BBB": 0.5
    }
    assert not _is_cooling_down("AAA", 64, cooldown_until)
    assert _cooldown_filtered_weights(ranked, 2, 64, cooldown_until) == {
        "AAA": 0.5,
        "BBB": 0.5,
    }


def test_margin_call_is_recorded_and_reduces_exposure_to_one_x(monkeypatch):
    first = date(2019, 1, 2)
    second = date(2019, 1, 3)
    data = {
        "AAA": Series(
            "AAA",
            [
                Bar(first, 100.0, 100.0, 100.0, 100.0, 1_000_000),
                # The gap is below maintenance but stays above the 20% stop.
                Bar(second, 81.0, 81.0, 81.0, 81.0, 1_000_000),
            ],
        )
    }
    cache = MomentumCache(
        lookback_bars=252,
        skip_bars=22,
        top_n=1,
        rebalance_frequency="monthly",
    )
    cache[first] = [("AAA", 0.20, 0.10)]
    monkeypatch.setattr(
        "analysis.bot2_momentum_pead_v4._volatility_multiplier",
        lambda curve, target, window, multiplier_cap=1.0: (
            multiplier_cap,
            False,
        ),
    )

    result = simulate_momentum(
        data,
        {"AAA"},
        universe_size=500,
        start=first,
        end=second,
        ranking_cache=cache,
        lookback_bars=252,
        skip_bars=22,
        top_n=1,
        target_volatility=0.12,
        idle_capital="cash",
        multiplier_cap=3.0,
        margin_interest_rate=0.0625,
        maintenance_margin_ratio=0.30,
    )

    assert result["margin_calls"] == 1
    assert result["margin_interest_paid"] == pytest.approx(
        200_300.0 * 0.0625 / 365
    )
    assert result["average_multiplier"] == 3.0
    assert result["borrowed_days"] == 1
    assert result["daily_deployment"][0]["margin_interest_paid"] == 0.0
    assert result["daily_deployment"][0]["borrowed_amount"] == pytest.approx(
        200_300.0
    )
    assert result["daily_deployment"][1]["margin_interest_paid"] > 0
    assert [event["action"] for event in result["event_log"]].count(
        "MARGIN_CALL"
    ) == 1
    assert result["daily_deployment"][-1]["deployed_pct"] == pytest.approx(1.0)


def test_spy_sleeve_rebalances_and_leaves_the_residual_equity_for_momentum(monkeypatch):
    data, spy, cache, days = _sleeve_fixture()
    monkeypatch.setattr(momentum_v4, "SLIP", 0.0)
    monkeypatch.setattr(momentum_v4, "_load_spy_reference_series", lambda end: spy)

    result = simulate_momentum(
        data,
        {"AAA"},
        universe_size=500,
        start=days[0],
        end=days[-1],
        ranking_cache=cache,
        top_n=1,
        idle_capital="cash",
        spy_sleeve_weight=0.20,
        spy_sleeve_leverage=1.0,
    )

    deployments = {item["date"]: item for item in result["daily_deployment"]}
    assert deployments[days[0].isoformat()]["momentum_budget"] == pytest.approx(
        80_000.0
    )
    momentum_entries = [
        event
        for event in result["event_log"]
        if event["action"] == "ENTER_MOMENTUM"
    ]
    assert momentum_entries[0]["notional"] == pytest.approx(80_000.0)
    assert deployments[days[1].isoformat()]["spy_market_value"] / deployments[
        days[1].isoformat()
    ]["equity"] != pytest.approx(0.20)
    assert deployments[days[2].isoformat()]["spy_market_value"] / deployments[
        days[2].isoformat()
    ]["equity"] == pytest.approx(0.20)
    assert len(
        [event for event in result["event_log"] if event["action"] == "REBALANCE_SPY"]
    ) == 2


def test_spy_sleeve_interest_is_paid_only_when_cash_is_borrowed(monkeypatch):
    data, spy, cache, days = _sleeve_fixture()
    monkeypatch.setattr(momentum_v4, "SLIP", 0.0)
    monkeypatch.setattr(momentum_v4, "_load_spy_reference_series", lambda end: spy)

    borrowed = simulate_momentum(
        data,
        {"AAA"},
        universe_size=500,
        start=days[0],
        end=days[-1],
        ranking_cache=cache,
        top_n=1,
        idle_capital="cash",
        margin_interest_rate=0.0625,
        maintenance_margin_ratio=0.30,
        spy_sleeve_weight=0.20,
        spy_sleeve_leverage=1.5,
    )
    unborrowed = simulate_momentum(
        data,
        {"AAA"},
        universe_size=500,
        start=days[0],
        end=days[-1],
        ranking_cache=cache,
        top_n=1,
        idle_capital="cash",
        margin_interest_rate=0.0625,
        maintenance_margin_ratio=0.30,
        spy_sleeve_weight=0.20,
        spy_sleeve_leverage=0.5,
    )

    assert borrowed["daily_deployment"][0]["borrowed_amount"] == pytest.approx(
        10_000.0
    )
    assert borrowed["daily_deployment"][0]["margin_interest_paid"] == 0.0
    assert borrowed["daily_deployment"][1]["margin_interest_paid"] == pytest.approx(
        10_000.0 * 0.0625 / 365.0
    )
    assert borrowed["margin_interest_paid"] > 0
    assert borrowed["borrowed_days"] > 0
    assert unborrowed["borrowed_days"] == 0
    assert unborrowed["margin_interest_paid"] == 0.0


def test_spy_sleeve_maintenance_check_reduces_total_exposure(monkeypatch):
    data, spy, cache, days = _sleeve_fixture()
    data["AAA"] = Series(
        "AAA",
        [
            Bar(day, price, price, price, price, 1_000_000)
            for day, price in zip(days, (100.0, 5.0, 5.0, 5.0))
        ],
    )
    spy = Series(
        "SPY",
        [
            Bar(day, price, price, price, price, 1_000_000)
            for day, price in zip(days, (100.0, 5.0, 5.0, 5.0))
        ],
    )
    monkeypatch.setattr(momentum_v4, "SLIP", 0.0)
    monkeypatch.setattr(momentum_v4, "_load_spy_reference_series", lambda end: spy)

    result = simulate_momentum(
        data,
        {"AAA"},
        universe_size=500,
        start=days[0],
        end=days[1],
        ranking_cache=cache,
        top_n=1,
        idle_capital="cash",
        maintenance_margin_ratio=0.30,
        spy_sleeve_weight=0.20,
        spy_sleeve_leverage=1.5,
    )

    margin_call = next(
        event for event in result["event_log"] if event["action"] == "MARGIN_CALL"
    )
    assert margin_call["maintenance_ratio_before"] < 0.30
    assert margin_call["target_leverage"] == 1.0
    assert result["margin_calls"] == 1
    assert result["daily_deployment"][-1]["invested_value"] == pytest.approx(0.0)


def test_spy_returns_do_not_change_the_momentum_volatility_scaling(monkeypatch):
    data = _parameter_universe()
    spy = _series("SPY", count=800, slope=0.55)
    monkeypatch.setattr(momentum_v4, "SLIP", 0.0)
    monkeypatch.setattr(momentum_v4, "_load_spy_reference_series", lambda end: spy)
    cache = build_momentum_cache(
        data,
        set(data),
        universe_size=500,
        end=date(2020, 1, 31),
        top_n=20,
    )
    common = {
        "universe_size": 500,
        "start": date(2019, 1, 1),
        "end": date(2020, 1, 31),
        "ranking_cache": cache,
        "top_n": 20,
        "target_volatility": 0.12,
        "realized_volatility_window": 126,
        "multiplier_cap": 1.0,
        "idle_capital": "cash",
    }

    momentum_only = simulate_momentum(data, set(data), **common)
    with_spy = simulate_momentum(
        data,
        set(data),
        **common,
        spy_sleeve_weight=0.20,
        spy_sleeve_leverage=1.5,
    )

    assert with_spy["rebalance_multipliers"] == momentum_only["rebalance_multipliers"]


def test_spy_sleeve_rows_append_with_strict_sql_placeholder_validation(monkeypatch):
    class StrictCursor:
        def __init__(self):
            self.executions = []
            self.row = None
            self.insert_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query, parameters=()):
            if query.count("%s") != len(parameters):
                raise AssertionError(
                    f"{query.count('%s')} placeholders for {len(parameters)} parameters"
                )
            self.executions.append((query, parameters))
            if query.lstrip().startswith("SELECT COUNT"):
                self.row = (0,)
            else:
                self.insert_count += 1
                self.row = (900 + self.insert_count,)

        def fetchone(self):
            return self.row

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = StrictCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def cursor(self):
            return self.fake_cursor

    connection = FakeConnection()
    monkeypatch.setattr(momentum_v4, "get_conn", lambda: connection)
    rows = [
        {
            "parameters": {
                "reference_run_id": 139,
                "spy_sleeve_weight": 0.20,
                "spy_sleeve_leverage": leverage,
            },
            "data_window": {
                "backtest_start": "2019-02-01",
                "backtest_end": "2026-07-31",
            },
            "result": {
                "return": 0.25,
                "sharpe": 0.8,
                "max_drawdown": 0.2,
                "margin_calls": 0,
                "margin_interest_paid": 1.5,
            },
        }
        for leverage in (1.0, 1.5)
    ]

    run_ids = append_spy_sleeve_exploration_runs(
        rows,
        reference_run_id=139,
    )

    assert run_ids == [901, 902]
    assert connection.fake_cursor.insert_count == 2
    assert [query.count("%s") for query, _ in connection.fake_cursor.executions] == [
        3,
        9,
        9,
    ]
    with pytest.raises(AssertionError, match="placeholders for"):
        connection.fake_cursor.execute("SELECT %s, %s", (1,))


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