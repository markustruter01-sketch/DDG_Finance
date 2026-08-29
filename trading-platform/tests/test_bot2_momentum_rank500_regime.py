from datetime import date, timedelta

from analysis.bot2_momentum_pead_v3 import Bar, Series
from analysis.bot2_momentum_rank500_regime import (
    REGIME_OFF,
    REGIME_ON,
    _build_regime_cache,
    _regime_for_day,
)


def _series(closes: list[float]) -> Series:
    start = date(2020, 1, 1)
    return Series(
        "SPY",
        [
            Bar(start + timedelta(days=index), close, close, close, close, 1_000_000)
            for index, close in enumerate(closes)
        ],
    )


def test_regime_uses_only_the_strictly_prior_200_sessions() -> None:
    # August 1, 2020 is the 214th calendar bar from January 1, so there are
    # at least 200 observations while the current-day spike remains excluded.
    closes = [100.0] * 213 + [120.0]
    spy = _series(closes)
    rebalance = date(2020, 8, 1)

    cache = _build_regime_cache(spy, rebalance)

    # The rebalance-day bar is not in the lookback; the 200 prior bars are
    # flat, so a same-day spike cannot make this RISK_ON.
    assert cache[rebalance]["prior_sessions"] == 200
    assert cache[rebalance]["prior_close"] == 100.0
    assert cache[rebalance]["sma_200"] == 100.0
    assert cache[rebalance]["state"] == REGIME_OFF


def test_regime_is_strictly_above_sma_for_risk_on() -> None:
    closes = [100.0] * 200 + [110.0] * 25
    spy = _series(closes)

    cache = _build_regime_cache(spy, date(2020, 8, 1))

    assert cache[date(2020, 8, 1)]["prior_close"] == 110.0
    assert cache[date(2020, 8, 1)]["sma_200"] > 100.0
    assert cache[date(2020, 8, 1)]["state"] == REGIME_ON


def test_regime_for_day_carries_the_last_monthly_state() -> None:
    cache = {
        date(2021, 1, 4): {"state": REGIME_ON},
        date(2021, 2, 1): {"state": REGIME_OFF},
    }

    assert _regime_for_day(cache, date(2021, 1, 29)) == REGIME_ON
    assert _regime_for_day(cache, date(2021, 2, 12)) == REGIME_OFF