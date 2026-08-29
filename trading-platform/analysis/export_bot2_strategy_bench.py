#!/usr/bin/env python3
"""Export the development-only Bot 2 browser backtest bench dataset."""

from __future__ import annotations

import json
import math
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM = _ROOT / "trading-platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from core.equity_universe import (  # noqa: E402
    last_screen_observations,
    screen_universe,
    set_screen_data,
)
from analysis.bot2_momentum_pead_v4 import (  # noqa: E402
    _all_days,
    _spy_series,
)
from analysis.bot2_momentum_pead_v3 import (  # noqa: E402
    PRICE_SOURCES,
    PRICE_TABLE,
    _fetch_feed,
)
from analysis.bot2_momentum_rank500_backtest import (  # noqa: E402
    BACKTEST_START,
    MIN_PRICE,
    MIN_SESSIONS,
    TARGET_UNIVERSE,
    WARMUP_START,
    _load_assets,
    _load_compact_panel,
    _latest_complete_month_end,
)


OUTPUT_PATH = _PLATFORM / ".local" / "bot2_strategy_bench.json"
SKIP_SESSIONS = 21
MOMENTUM_WINDOWS = (12, 9, 6, 3)
REGIME_LOOKBACK = 200


def _round_float(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"non-finite value cannot be exported: {value!r}")
    rounded = round(float(value), 6)
    return 0.0 if abs(rounded) < 0.0000005 else rounded


def _month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    ordinal = year * 12 + (month - 1) + offset
    return ordinal // 12, ordinal % 12 + 1


def _month_closes(data: Any) -> dict[tuple[int, int], float]:
    closes: dict[tuple[int, int], float] = {}
    for bar in data.bars:
        closes[(bar.day.year, bar.day.month)] = float(bar.close)
    return closes


def _monthly_return(
    closes: dict[tuple[int, int], float],
    end_month: tuple[int, int],
    months_back: int,
) -> float | None:
    start_month = _shift_month(end_month[0], end_month[1], -months_back)
    end_close = closes.get(end_month)
    start_close = closes.get(start_month)
    if end_close is None or start_close is None or start_close <= 0:
        return None
    return end_close / start_close - 1


def _monthly_feature(
    closes: dict[tuple[int, int], float],
    month: tuple[int, int],
    lookback: int,
) -> float | None:
    # The current month is not complete at the rebalance. Use the prior
    # month-end close and the corresponding lookback month-end close.
    prior_month = _shift_month(month[0], month[1], -1)
    return _monthly_return(closes, prior_month, lookback)


def _trailing_monthly_vol(
    closes: dict[tuple[int, int], float],
    month: tuple[int, int],
) -> float | None:
    prior_month = _shift_month(month[0], month[1], -1)
    returns: list[float] = []
    for offset in range(6, 0, -1):
        end_month = _shift_month(prior_month[0], prior_month[1], -(offset - 1))
        value = _monthly_return(closes, end_month, 1)
        if value is None:
            return None
        returns.append(value)
    return statistics.pstdev(returns)


def _daily_momentum_features(data: Any, rebalance: date) -> dict[str, float] | None:
    cutoff = bisect_left(data.days, rebalance)
    if cutoff <= 0:
        return None
    features: dict[str, float] = {}
    for lookback in MOMENTUM_WINDOWS:
        lookback_sessions = lookback * 21
        skip_index = cutoff - SKIP_SESSIONS - 1
        lookback_index = cutoff - lookback_sessions
        no_skip = cutoff - 1
        if lookback_index < 0 or skip_index < 0:
            return None
        start_close = data.bars[lookback_index].close
        if start_close <= 0:
            return None
        skip_close = data.bars[skip_index].close
        current_close = data.bars[no_skip].close
        features[f"{lookback}_1"] = _round_float(skip_close / start_close - 1)
        features[f"{lookback}_0"] = _round_float(current_close / start_close - 1)
    return features


def _load_spy(end: date) -> Any:
    # SPY is intentionally outside the ordinary-equity SIP panel. Reuse the
    # existing read-only benchmark fallback; no order or live-runner path is
    # reachable from this exporter.
    spy = _spy_series()
    if not spy.bars:
        raise RuntimeError("SPY reference series is empty")
    if spy.bars[-1].day < end:
        raise RuntimeError(
            f"SPY reference ends at {spy.bars[-1].day}, before panel end {end}"
        )
    return spy


def _spy_regime(spy: Any, rebalance: date) -> bool:
    cutoff = bisect_left(spy.days, rebalance)
    prior = spy.bars[:cutoff]
    if len(prior) < REGIME_LOOKBACK:
        raise RuntimeError(
            f"SPY has only {len(prior)} prior sessions before {rebalance}"
        )
    prior_close = prior[-1].close
    sma = statistics.fmean(
        bar.close for bar in prior[-REGIME_LOOKBACK:]
    )
    return bool(prior_close > sma)


def _rebalance_dates(panel: dict[str, Any], end: date) -> list[date]:
    first_by_month: dict[tuple[int, int], date] = {}
    for day in _all_days(panel, end):
        if day < BACKTEST_START:
            continue
        key = (day.year, day.month)
        first_by_month.setdefault(key, day)
    expected_last = (end.year, end.month)
    if expected_last not in first_by_month:
        raise RuntimeError(f"no stored rebalance session for {expected_last}")
    return [
        first_by_month[key]
        for key in sorted(first_by_month)
        if key <= expected_last
    ]


def build_export() -> dict[str, Any]:
    end = _latest_complete_month_end()
    assets, candidate_symbols = _load_assets()
    panel = _load_compact_panel(candidate_symbols, end)
    if not panel:
        raise RuntimeError("stored SIP panel is empty")
    set_screen_data(assets, panel)
    rebalance_dates = _rebalance_dates(panel, end)
    if not rebalance_dates:
        raise RuntimeError("no monthly rebalance dates found")
    months = [_month_key(day) for day in rebalance_dates]
    print(
        f"bench_window | first={months[0]} | last={months[-1]} "
        f"| monthly_rebalances={len(months)} | requested_count=103"
    )
    if len(months) != 103:
        print(
            f"bench_window_note | requested_dates_count_is={len(months)} "
            "| 103 includes the stored 2018-01 warmup span, outside the requested 2019-02 window"
        )

    spy = _load_spy(end)
    universe: dict[str, list[str]] = {}
    momentum: dict[str, dict[str, dict[str, float]]] = {}
    forward: dict[str, dict[str, float]] = {}
    vol: dict[str, dict[str, float]] = {}
    spy_output: dict[str, dict[str, Any]] = {}
    monthly_cache: dict[str, dict[tuple[int, int], float]] = {}

    for rebalance in rebalance_dates:
        key = _month_key(rebalance)
        selected, funnel = screen_universe(
            rebalance,
            TARGET_UNIVERSE,
            MIN_SESSIONS,
            MIN_PRICE,
            require_current_bar=True,
        )
        observations = last_screen_observations()
        ranked = sorted(
            selected,
            key=lambda symbol: (
                -float(observations[symbol]["median_dollar_volume_60"]),
                symbol,
            ),
        )
        if len(ranked) > TARGET_UNIVERSE:
            raise RuntimeError(f"shared screener returned too many symbols for {key}")
        universe[key] = ranked
        momentum[key] = {}
        forward[key] = {}
        vol[key] = {}
        month_tuple = (rebalance.year, rebalance.month)

        for symbol in ranked:
            data = panel.get(symbol)
            if data is None:
                raise RuntimeError(f"shared screener returned unloaded symbol {symbol}")
            features = _daily_momentum_features(data, rebalance)
            if features is not None:
                momentum[key][symbol] = features
            closes = monthly_cache.setdefault(symbol, _month_closes(data))
            prior_month = _shift_month(month_tuple[0], month_tuple[1], -1)
            next_month = _shift_month(month_tuple[0], month_tuple[1], 1)
            next_return = _monthly_return(closes, next_month, 1)
            trailing_vol = _trailing_monthly_vol(closes, month_tuple)
            if next_return is not None:
                forward[key][symbol] = _round_float(next_return)
            if trailing_vol is not None:
                vol[key][symbol] = _round_float(trailing_vol)

        spy_closes = monthly_cache.setdefault("__SPY__", _month_closes(spy))
        spy_month_return = _monthly_return(spy_closes, month_tuple, 1)
        if spy_month_return is None:
            raise RuntimeError(f"SPY monthly return unavailable for {key}")
        spy_output[key] = {
            "ret": _round_float(spy_month_return),
            "risk_on": _spy_regime(spy, rebalance),
        }
        print(
            f"bench_month | month={key} | universe={len(ranked)} "
            f"| momentum={len(momentum[key])} | forward={len(forward[key])} "
            f"| vol={len(vol[key])} | spy_risk_on={spy_output[key]['risk_on']} "
            f"| rank_cutoff_dollar_volume={funnel['rank_cutoff_dollar_volume']}"
        )

    payload = {
        "meta": {
            "source": (
                "development bot2_sp500_prices stored adjusted SIP/IEX panel; "
                "universe=core.equity_universe.screen_universe; "
                "SPY=read-only historical SIP reference"
            ),
            "generated": datetime.now(timezone.utc).isoformat(),
        },
        "months": months,
        "universe": universe,
        "momentum": momentum,
        "forward": forward,
        "vol": vol,
        "spy": spy_output,
    }
    top_level = list(payload)
    expected_top_level = ["meta", "months", "universe", "momentum", "forward", "vol", "spy"]
    if top_level != expected_top_level:
        raise AssertionError(f"unexpected top-level schema: {top_level}")
    return payload


def main() -> int:
    payload = build_export()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, separators=(",", ": "))
        handle.write("\n")
    size = OUTPUT_PATH.stat().st_size
    print(f"bench_export_written | path={OUTPUT_PATH} | bytes={size} | size_kb={size / 1024:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())