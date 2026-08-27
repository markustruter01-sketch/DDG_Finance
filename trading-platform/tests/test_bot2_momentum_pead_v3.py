from datetime import date, timedelta

from analysis.bot2_momentum_pead_v3 import (
    Bar,
    PEAD_SYMBOLS,
    Series,
    choose_liquidity_floor,
    _is_signal_earnings_event,
    screen_universe,
    simulate_momentum,
)


def _series(symbol: str, count: int = 320, volume: float = 1_000_000.0) -> Series:
    bars = []
    first = date(2018, 1, 1)
    for index in range(count):
        day = first + timedelta(days=index)
        close = 100.0 + index * 0.25 + (index % 5) * 0.10
        bars.append(Bar(day, close, close + 1, close - 1, close, volume))
    return Series(symbol, bars)


def test_screen_uses_only_bars_strictly_before_as_of():
    data = _series("AAA")
    as_of = data.bars[280].day
    qualified, observations = screen_universe(
        {"AAA": data}, {"AAA"}, as_of, liquidity_floor=1.0
    )

    assert qualified == {"AAA"}
    assert observations["AAA"]["last_data_day"] < as_of
    assert observations["AAA"]["uses_future_data"] is False
    assert observations["AAA"]["sessions_available"] == 280


def test_liquidity_floor_is_calibrated_from_the_targetth_largest_observation():
    series = {
        f"S{index}": _series(f"S{index}", volume=(index + 1) * 1_000_000)
        for index in range(4)
    }

    floor = choose_liquidity_floor(
        series, as_of=date(2018, 10, 20), target=2
    )

    assert 300_000_000 < floor < 600_000_000


def test_mechanical_screen_rejects_insufficient_history_and_low_price():
    short = _series("SHORT", count=100)
    low = _series("LOW")
    low.bars = [
        Bar(bar.day, bar.open, bar.high, bar.low, 4.0, bar.volume)
        for bar in low.bars
    ]
    low.__post_init__()

    qualified, observations = screen_universe(
        {"SHORT": short, "LOW": low},
        {"SHORT", "LOW"},
        date(2018, 10, 20),
        liquidity_floor=1.0,
    )

    assert qualified == set()
    assert "SHORT" not in observations
    assert observations["LOW"]["median_close_60"] == 4.0


def test_cash_constrained_momentum_never_exceeds_full_deployment():
    data = _series("AAA", count=900)
    result = simulate_momentum(
        {"AAA": data},
        {"AAA"},
        liquidity_floor=1.0,
        start=date(2018, 1, 1),
        end=data.bars[-1].day,
    )

    assert result["trades"] > 0
    assert result["max_deployment"] <= 1.0000001
    assert sum(
        days["invested"] + days["cash"]
        for days in result["mode_days"].values()
    ) > 0


def test_manual_cost_is_excluded_but_non_manual_cost_remains_eligible():
    assert "COST" in PEAD_SYMBOLS
    assert not _is_signal_earnings_event("COST", 1.0, "post-market", "manual")
    assert _is_signal_earnings_event("COST", 1.0, "post-market", "alphavantage")