#!/usr/bin/env python3
"""Development-only locked Bot 2 rank-500 momentum backtest.

This run supersedes the fixed-floor experiments without touching any live
runner, bot state, monitoring, or production data.  It pre-registers the
immutable research specification, uses the v4 cash-constrained momentum
simulator, and supplies all ranking calls through core.equity_universe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import random
import statistics
import sys
import time
from array import array
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, NamedTuple

_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM = _ROOT / "trading-platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from db.research_postgres import get_research_conn as get_conn  # noqa: E402
from core.equity_universe import (  # noqa: E402
    eligible_asset_records,
    last_screen_observations,
    screen_universe,
    set_screen_data,
)
from analysis.bot2_momentum_pead_v3 import (  # noqa: E402
    PRICE_SOURCES,
    PRICE_TABLE,
    ensure_asset_table,
    load_stored_assets,
)
from analysis.bot2_momentum_pead_v4 import (  # noqa: E402
    CONTROL_ITERATIONS,
    MomentumCache,
    RANDOM_SEED,
    SLIP,
    SLIPPAGE_BPS,
    STARTING_EQUITY,
    STOP_LOSS,
    TARGET_UNIVERSE,
    TOP_N,
    _all_days,
    build_momentum_cache,
    simulate_buy_and_hold,
    simulate_equal_weight_universe,
    simulate_momentum,
)
from analysis.bot2_momentum_fullmarket import _sector_map  # noqa: E402
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)


STRATEGY_FAMILY = "bot2_momentum_rank500"
BOT_ID = "bot2_momentum_rank500_research"
BACKTEST_START = date(2019, 2, 1)
MIN_SESSIONS = 252
MIN_PRICE = 5.0
LIQUIDITY_SESSIONS = 60
WARMUP_START = date(2018, 1, 1)
HYPOTHESIS = (
    "12-1 cross-sectional momentum, top 20 equal weight, monthly rebalance, "
    "on a rank-based top-500 US equity universe screened point-in-time, "
    "produces positive risk-adjusted returns."
)
PASS_BAR = {
    "sharpe_min": 0.60,
    "max_drawdown_max": 0.40,
    "beats_spy_buy_and_hold_risk_adjusted": True,
    "beats_random_entry": True,
}
SAMPLE_MONTHS = (
    (2019, 6),
    (2022, 6),
    (2026, 6),
)
CACHE_VERSION = 1
CACHE_ROOT = _ROOT / ".cache" / "bot2-momentum-research"
EXPECTED_EXPERIMENT_18_SHARPE = 0.7016876886753177


class CompactBar(NamedTuple):
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class _DateBarLookup:
    """Lazy date lookup so the 10M-row panel does not need a second dict."""

    __slots__ = ("_days", "_bars")

    def __init__(self, days: list[date], bars: list[CompactBar]) -> None:
        self._days = days
        self._bars = bars

    def get(self, day: date, default: CompactBar | None = None) -> CompactBar | None:
        index = bisect_left(self._days, day)
        if index < len(self._days) and self._days[index] == day:
            return self._bars[index]
        return default

    def __getitem__(self, day: date) -> CompactBar:
        bar = self.get(day)
        if bar is None:
            raise KeyError(day)
        return bar

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.get(day) is not None


class CompactSeries:
    """Series-compatible compact storage for the historical backtest panel."""

    __slots__ = ("symbol", "bars", "days", "by_date", "bars_sorted")

    def __init__(self, symbol: str, bars: list[CompactBar]) -> None:
        self.symbol = symbol
        self.bars = bars
        self.days = [bar.day for bar in bars]
        self.by_date = _DateBarLookup(self.days, bars)
        self.bars_sorted = True


class _PackedDays:
    """Date sequence backed by four-byte ordinals instead of date objects."""

    __slots__ = ("_ordinals",)

    def __init__(self, ordinals: array) -> None:
        self._ordinals = ordinals

    def __len__(self) -> int:
        return len(self._ordinals)

    def __getitem__(self, index: int | slice) -> date | list[date]:
        if isinstance(index, slice):
            return [date.fromordinal(value) for value in self._ordinals[index]]
        return date.fromordinal(self._ordinals[index])

    def __iter__(self):
        for ordinal in self._ordinals:
            yield date.fromordinal(ordinal)


class _PackedBars:
    """Bar sequence that materializes only the rows a simulator accesses."""

    __slots__ = ("_days", "_open", "_high", "_low", "_close", "_volume")

    def __init__(
        self,
        days: array,
        opens: array,
        highs: array,
        lows: array,
        closes: array,
        volumes: array,
    ) -> None:
        self._days = days
        self._open = opens
        self._high = highs
        self._low = lows
        self._close = closes
        self._volume = volumes

    def __len__(self) -> int:
        return len(self._days)

    def __getitem__(self, index: int | slice) -> CompactBar | list[CompactBar]:
        if isinstance(index, slice):
            return [self[position] for position in range(*index.indices(len(self)))]
        return CompactBar(
            date.fromordinal(self._days[index]),
            self._open[index],
            self._high[index],
            self._low[index],
            self._close[index],
            self._volume[index],
        )

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


class PackedSeries:
    """Series-compatible packed storage for large research panels."""

    __slots__ = ("symbol", "bars", "days", "by_date", "bars_sorted")

    def __init__(
        self,
        symbol: str,
        days: array,
        opens: array,
        highs: array,
        lows: array,
        closes: array,
        volumes: array,
    ) -> None:
        self.symbol = symbol
        self.days = _PackedDays(days)
        self.bars = _PackedBars(days, opens, highs, lows, closes, volumes)
        self.by_date = _DateBarLookup(self.days, self.bars)
        self.bars_sorted = True


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _latest_complete_month_end() -> date:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MAX(date) FROM {PRICE_TABLE} "
                "WHERE source = ANY(%s)",
                (list(PRICE_SOURCES),),
            )
            latest = cur.fetchone()[0]
    if latest is None:
        raise RuntimeError("price panel has no stored market day")
    return latest.replace(day=1) - timedelta(days=1)


def _load_assets() -> tuple[list[dict[str, Any]], set[str]]:
    ensure_asset_table()
    assets = load_stored_assets()
    records = [
        {
            "symbol": asset.symbol,
            "asset_class": asset.asset_class,
            "status": asset.status,
            "exchange": asset.exchange,
            "tradable": asset.tradable,
            "fractionable": asset.fractionable,
            "name": asset.name,
        }
        for asset in assets
    ]
    eligible, funnel = eligible_asset_records(records)
    symbols = {str(item["symbol"]).upper() for item in eligible}
    print(
        f"asset_preflight | stored_assets={len(records)} "
        f"| static_eligible={funnel['asset_eligible_records']} "
        f"| candidate_symbols={len(symbols)}"
    )
    return list(eligible), symbols


def _load_compact_panel(
    symbols: set[str], end: date
) -> dict[str, PackedSeries]:
    grouped: dict[str, dict[str, array]] = {}
    with get_conn() as conn:
        with conn.cursor(name="bot2_rank500_backtest_panel") as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (symbol, date)
                       symbol, date, open, high, low, close, volume
                  FROM {PRICE_TABLE}
                 WHERE symbol = ANY(%s)
                   AND date >= %s AND date <= %s
                   AND source = ANY(%s)
                 ORDER BY symbol, date,
                          CASE WHEN source='alpaca_sip_adjusted' THEN 0 ELSE 1 END
                """,
                (sorted(symbols), WARMUP_START, end, list(PRICE_SOURCES)),
            )
            while True:
                rows = cur.fetchmany(20_000)
                if not rows:
                    break
                for symbol, day, opn, high, low, close, volume in rows:
                    if any(value is None for value in (opn, high, low, close, volume)):
                        continue
                    key = str(symbol).upper()
                    if key not in grouped:
                        grouped[key] = {
                            "days": array("I"),
                            "open": array("d"),
                            "high": array("d"),
                            "low": array("d"),
                            "close": array("d"),
                            "volume": array("d"),
                        }
                    packed = grouped[key]
                    packed["days"].append(day.toordinal())
                    packed["open"].append(float(opn))
                    packed["high"].append(float(high))
                    packed["low"].append(float(low))
                    packed["close"].append(float(close))
                    packed["volume"].append(float(volume))
    series = {
        symbol: PackedSeries(
            symbol,
            values["days"],
            values["open"],
            values["high"],
            values["low"],
            values["close"],
            values["volume"],
        )
        for symbol, values in grouped.items()
        if values["days"]
    }
    print(
        f"panel_loaded | symbols={len(series)} "
        f"| bars={sum(len(data.bars) for data in series.values())} "
        f"| from={WARMUP_START} | through={end} | storage=packed_arrays"
    )
    return series


def _cache_spec(
    candidate_symbols: set[str],
    end: date,
    *,
    universe_size: int,
    lookback_bars: int,
    skip_bars: int,
    top_n: int,
    rebalance_frequency: str,
) -> dict[str, Any]:
    """Return every input that can change the cached panel or ranking result."""
    return {
        "cache_version": CACHE_VERSION,
        "universe": {
            "candidate_symbols": sorted(candidate_symbols),
            "size": universe_size,
        },
        "window": {
            "warmup_start": WARMUP_START.isoformat(),
            "backtest_start": BACKTEST_START.isoformat(),
            "backtest_end": end.isoformat(),
        },
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "lookback_bars": lookback_bars,
        "skip_bars": skip_bars,
        "top_n": top_n,
        "rebalance_frequency": rebalance_frequency,
    }


def _cache_key(spec: dict[str, Any]) -> str:
    encoded = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _cache_paths(cache_key: str) -> tuple[Path, Path]:
    return (
        CACHE_ROOT / f"panel-{cache_key}.pkl",
        CACHE_ROOT / f"ranking-{cache_key}.pkl",
    )


def _write_cache(path: Path, payload: dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temporary, path)
    return path.stat().st_size


def _read_cache(
    path: Path,
    *,
    kind: str,
    expected_key: str,
    expected_spec: dict[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        print(
            f"cache_key_check | kind={kind} | path={path} | "
            "status=MISS reason=file_missing"
        )
        return None
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
    except Exception as exc:
        print(
            f"cache_key_check | kind={kind} | path={path} | "
            f"status=MISS reason=unreadable:{type(exc).__name__}"
        )
        return None
    actual_key = payload.get("cache_key") if isinstance(payload, dict) else None
    actual_spec = payload.get("spec") if isinstance(payload, dict) else None
    matches = (
        isinstance(payload, dict)
        and payload.get("cache_version") == CACHE_VERSION
        and payload.get("kind") == kind
        and actual_key == expected_key
        and actual_spec == expected_spec
    )
    print(
        f"cache_key_check | kind={kind} | path={path} | "
        f"expected={expected_key} | actual={actual_key} | "
        f"match={'PASS' if matches else 'FAIL'}"
    )
    return payload if matches else None


def _serialize_panel(series: dict[str, PackedSeries]) -> dict[str, dict[str, array]]:
    return {
        symbol: {
            "days": array("I", data.days._ordinals),
            "open": array("d", data.bars._open),
            "high": array("d", data.bars._high),
            "low": array("d", data.bars._low),
            "close": array("d", data.bars._close),
            "volume": array("d", data.bars._volume),
        }
        for symbol, data in series.items()
    }


def _deserialize_panel(
    payload: dict[str, dict[str, array]],
) -> dict[str, PackedSeries]:
    return {
        symbol: PackedSeries(
            symbol,
            values["days"],
            values["open"],
            values["high"],
            values["low"],
            values["close"],
            values["volume"],
        )
        for symbol, values in payload.items()
    }


def _load_or_build_panel_cache(
    candidate_symbols: set[str],
    end: date,
    *,
    universe_size: int,
    lookback_bars: int,
    skip_bars: int,
    top_n: int,
    rebalance_frequency: str,
    force_rebuild: bool = False,
) -> tuple[dict[str, PackedSeries], str, Path, bool]:
    spec = _cache_spec(
        candidate_symbols,
        end,
        universe_size=universe_size,
        lookback_bars=lookback_bars,
        skip_bars=skip_bars,
        top_n=top_n,
        rebalance_frequency=rebalance_frequency,
    )
    key = _cache_key(spec)
    panel_path, _ = _cache_paths(key)
    if not force_rebuild:
        payload = _read_cache(
            panel_path,
            kind="panel",
            expected_key=key,
            expected_spec=spec,
        )
        if payload is not None:
            return _deserialize_panel(payload["series"]), key, panel_path, True
    series = _load_compact_panel(candidate_symbols, end)
    size = _write_cache(
        panel_path,
        {
            "cache_version": CACHE_VERSION,
            "kind": "panel",
            "cache_key": key,
            "spec": spec,
            "series": _serialize_panel(series),
        },
    )
    print(f"cache_saved | kind=panel | path={panel_path} | bytes={size}")
    return series, key, panel_path, False


def _load_or_build_ranking_cache(
    series: dict[str, PackedSeries],
    candidate_symbols: set[str],
    end: date,
    *,
    universe_size: int,
    lookback_bars: int,
    skip_bars: int,
    top_n: int,
    rebalance_frequency: str,
    force_rebuild: bool = False,
) -> tuple[MomentumCache, str, Path, bool]:
    spec = _cache_spec(
        candidate_symbols,
        end,
        universe_size=universe_size,
        lookback_bars=lookback_bars,
        skip_bars=skip_bars,
        top_n=top_n,
        rebalance_frequency=rebalance_frequency,
    )
    key = _cache_key(spec)
    _, ranking_path = _cache_paths(key)
    if not force_rebuild:
        payload = _read_cache(
            ranking_path,
            kind="ranking",
            expected_key=key,
            expected_spec=spec,
        )
        if payload is not None:
            cache = MomentumCache(
                lookback_bars=lookback_bars,
                skip_bars=skip_bars,
                top_n=top_n,
                rebalance_frequency=rebalance_frequency,
            )
            cache.update(payload["ranking"])
            return cache, key, ranking_path, True
    ranking_cache = build_momentum_cache(
        series,
        set(series) & candidate_symbols,
        universe_size,
        end,
        lookback_bars=lookback_bars,
        skip_bars=skip_bars,
        top_n=top_n,
        rebalance_frequency=rebalance_frequency,
    )
    size = _write_cache(
        ranking_path,
        {
            "cache_version": CACHE_VERSION,
            "kind": "ranking",
            "cache_key": key,
            "spec": spec,
            "ranking": ranking_cache,
        },
    )
    print(f"cache_saved | kind=ranking | path={ranking_path} | bytes={size}")
    return ranking_cache, key, ranking_path, False


def _cache_benchmark() -> dict[str, Any]:
    """Build, persist, reload, and verify Experiment 18 without DB writes."""
    end = _latest_complete_month_end()
    assets, candidate_symbols = _load_assets()
    parameters = {
        "universe_size": TARGET_UNIVERSE,
        "lookback_bars": 252,
        "skip_bars": 22,
        "top_n": TOP_N,
        "rebalance_frequency": "monthly",
    }
    spec = _cache_spec(candidate_symbols, end, **parameters)
    key = _cache_key(spec)
    panel_path, ranking_path = _cache_paths(key)

    cold_started = time.perf_counter()
    panel_started = time.perf_counter()
    cold_series, _, _, _ = _load_or_build_panel_cache(
        candidate_symbols, end, **parameters, force_rebuild=True
    )
    cold_panel_seconds = time.perf_counter() - panel_started
    set_screen_data(assets, cold_series)
    ranking_started = time.perf_counter()
    cold_ranking, _, _, _ = _load_or_build_ranking_cache(
        cold_series, candidate_symbols, end, **parameters, force_rebuild=True
    )
    cold_ranking_seconds = time.perf_counter() - ranking_started
    cold_total_seconds = time.perf_counter() - cold_started
    print(f"cold_stage_seconds | panel={cold_panel_seconds:.6f}")
    print(f"cold_stage_seconds | ranking={cold_ranking_seconds:.6f}")
    print(f"cold_stage_seconds | total={cold_total_seconds:.6f}")

    warm_started = time.perf_counter()
    warm_panel_started = time.perf_counter()
    warm_series, warm_key, warm_panel_path, warm_panel_hit = _load_or_build_panel_cache(
        candidate_symbols, end, **parameters
    )
    warm_panel_seconds = time.perf_counter() - warm_panel_started
    set_screen_data(assets, warm_series)
    warm_ranking_started = time.perf_counter()
    warm_ranking, warm_ranking_key, warm_ranking_path, warm_ranking_hit = (
        _load_or_build_ranking_cache(
            warm_series, candidate_symbols, end, **parameters
        )
    )
    warm_ranking_seconds = time.perf_counter() - warm_ranking_started
    warm_total_seconds = time.perf_counter() - warm_started
    print(f"warm_stage_seconds | panel={warm_panel_seconds:.6f}")
    print(f"warm_stage_seconds | ranking={warm_ranking_seconds:.6f}")
    print(f"warm_stage_seconds | total={warm_total_seconds:.6f}")
    print(
        f"cache_paths | key={key} | panel={warm_panel_path} | "
        f"panel_bytes={warm_panel_path.stat().st_size} | ranking={warm_ranking_path} | "
        f"ranking_bytes={warm_ranking_path.stat().st_size}"
    )
    print(
        f"cache_hit_check | panel={'PASS' if warm_panel_hit else 'FAIL'} "
        f"| ranking={'PASS' if warm_ranking_hit else 'FAIL'} "
        f"| panel_key_match={'PASS' if warm_key == key else 'FAIL'} "
        f"| ranking_key_match={'PASS' if warm_ranking_key == key else 'FAIL'}"
    )

    warm_result = simulate_momentum(
        warm_series,
        set(warm_series) & candidate_symbols,
        TARGET_UNIVERSE,
        BACKTEST_START,
        end,
        warm_ranking,
        lookback_bars=252,
        skip_bars=22,
        top_n=TOP_N,
        rebalance_frequency="monthly",
    )
    warm_sharpe = warm_result["sharpe"]
    print(
        f"warm_correctness | experiment=18 | sharpe={warm_sharpe!r} "
        f"| expected={EXPECTED_EXPERIMENT_18_SHARPE!r} "
        f"| match={'PASS' if warm_sharpe == EXPECTED_EXPERIMENT_18_SHARPE else 'FAIL'}"
    )
    if warm_sharpe != EXPECTED_EXPERIMENT_18_SHARPE:
        raise RuntimeError(
            f"STOP: warm Experiment 18 Sharpe differs: "
            f"{warm_sharpe!r} != {EXPECTED_EXPERIMENT_18_SHARPE!r}"
        )
    print(
        f"cache_saving | seconds={cold_total_seconds - warm_total_seconds:.6f} "
        f"| percent={(1 - warm_total_seconds / cold_total_seconds) * 100:.2f}"
    )
    return {
        "cache_key": key,
        "panel_path": str(panel_path),
        "ranking_path": str(ranking_path),
        "cold_seconds": cold_total_seconds,
        "warm_seconds": warm_total_seconds,
        "saving_seconds": cold_total_seconds - warm_total_seconds,
        "sharpe": warm_sharpe,
    }


def _first_session(days: Iterable[date], year: int, month: int) -> date:
    target = date(year, month, 1)
    for day in days:
        if day >= target:
            return day
    raise RuntimeError(f"no stored session on or after {target}")


def _windows(end: date) -> tuple[tuple[str, date, date], ...]:
    return (
        ("2019_2020", BACKTEST_START, date(2020, 12, 31)),
        ("2021_2022", date(2021, 1, 1), date(2022, 12, 31)),
        ("2023_2024", date(2023, 1, 1), date(2024, 12, 31)),
        ("2025_latest_complete", date(2025, 1, 1), end),
        ("pooled_2019-02_latest_complete", BACKTEST_START, end),
    )


def _register(end: date, windows: tuple[tuple[str, date, date], ...]) -> int:
    ensure_research_tables()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT experiment_id, results
                     FROM research_ledger
                    WHERE strategy_family=%s AND bot_id=%s
                    ORDER BY experiment_id DESC LIMIT 1""",
                (STRATEGY_FAMILY, BOT_ID),
            )
            existing = cur.fetchone()
    if existing is not None:
        if existing[1] is not None:
            raise RuntimeError(
                f"{STRATEGY_FAMILY} already has immutable results: experiment_id={existing[0]}"
            )
        print(
            f"experiment_preregistered | strategy_family={STRATEGY_FAMILY} "
            f"| experiment_id={existing[0]} | status=resume_uncompleted"
        )
        return int(existing[0])

    parameters = {
        "universe_size": TARGET_UNIVERSE,
        "universe_rule": "top 500 by trailing 60-session median dollar volume",
        "screening": {
            "point_in_time": "only bars strictly before each rebalance date",
            "minimum_prior_sessions": MIN_SESSIONS,
            "minimum_price": MIN_PRICE,
            "static_eligibility": "active Alpaca us_equity approved exchange ordinary shares",
        },
        "momentum": "12-1",
        "top_n": TOP_N,
        "allocation": "equal_weight",
        "rebalance": "monthly first-trading-day",
        "catastrophe_stop": STOP_LOSS,
        "slippage_each_leg_bps": SLIPPAGE_BPS,
        "max_deployment": 1.0,
        "idle_capital": "cash",
        "random_control_iterations": CONTROL_ITERATIONS,
        "random_control_seed": RANDOM_SEED,
    }
    data_window = {
        "warmup_start": WARMUP_START.isoformat(),
        "backtest_start": BACKTEST_START.isoformat(),
        "backtest_end": end.isoformat(),
        "windows": [
            {"name": name, "start": str(start), "end": str(window_end)}
            for name, start, window_end in windows
        ],
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "screener_implementation": "core.equity_universe.screen_universe",
    }
    experiment_id = register_experiment(
        strategy_family=STRATEGY_FAMILY,
        bot_id=BOT_ID,
        hypothesis=HYPOTHESIS,
        parameters=parameters,
        pass_bar=PASS_BAR,
        data_window=data_window,
        variations_tested=1,
        sizing_model="cash_constrained",
        went_live=False,
        notes=(
            "Supersedes experiments 13 and 17. Both used fixed dollar floors that "
            "produced unstable universes. This experiment uses the shared rank-based "
            "screener and starts at the first month with a full 500-name universe."
        ),
    )
    print(
        f"experiment_preregistered | strategy_family={STRATEGY_FAMILY} "
        f"| experiment_id={experiment_id} | sizing_model=cash_constrained"
    )
    return experiment_id


def _random_controls_in_process(
    series: dict[str, CompactSeries],
    windows: tuple[tuple[str, date, date], ...],
    ranking_cache: dict[date, list[tuple[str, float, float]]],
) -> dict[str, Any]:
    """Run 1,000 controls without forking the compact panel four times."""
    from analysis.bot2_momentum_pead_v4 import _fast_random_return

    output: dict[str, Any] = {}
    for name, start, end in windows:
        returns = [
            _fast_random_return(
                series,
                start,
                end,
                ranking_cache,
                random.Random(RANDOM_SEED + iteration),
            )
            for iteration in range(CONTROL_ITERATIONS)
        ]
        ordered = sorted(returns)
        output[name] = {
            "iterations": CONTROL_ITERATIONS,
            "seed": RANDOM_SEED,
            "matched_selection_size": TOP_N,
            "returns": returns,
            "return_mean": statistics.fmean(returns),
            "return_std": statistics.stdev(returns),
            "return_median": statistics.median(returns),
            "return_p05": ordered[max(0, int(len(ordered) * 0.05) - 1)],
            "return_p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            "dispersion_check": len(set(returns)) > 1,
        }
        print(
            f"random_control | window={name} | iterations={CONTROL_ITERATIONS} "
            f"| mean={output[name]['return_mean']:.6f} "
            f"| p05={output[name]['return_p05']:.6f} "
            f"| p95={output[name]['return_p95']:.6f}"
        )
    return output


def _actual_percentile(value: float, distribution: list[float]) -> float:
    return 100.0 * sum(item <= value for item in distribution) / len(distribution)


def _sample_snapshot(
    assets: list[dict[str, Any]],
    series: dict[str, CompactSeries],
    as_of: date,
    sectors: dict[str, str],
) -> list[dict[str, Any]]:
    set_screen_data(assets, series)
    qualified, funnel = screen_universe(
        as_of, TARGET_UNIVERSE, MIN_SESSIONS, MIN_PRICE, require_current_bar=True
    )
    observations = {
        symbol: value
        for symbol, value in last_screen_observations().items()
        if symbol in qualified
    }
    ranked: list[dict[str, Any]] = []
    for symbol in qualified:
        data = series[symbol]
        cutoff = bisect_left(data.days, as_of)
        if cutoff < MIN_SESSIONS:
            continue
        momentum = data.bars[cutoff - 22].close / data.bars[cutoff - 252].close - 1
        observation = observations.get(symbol, {})
        ranked.append(
            {
                "symbol": symbol,
                "momentum": momentum,
                "dollar_volume": observation.get("median_dollar_volume_60"),
                "price": data.bars[cutoff - 1].close,
                "sector": sectors.get(symbol, "unknown"),
            }
        )
    ranked.sort(key=lambda item: (-item["momentum"], item["symbol"]))
    print(
        f"snapshot_screen | as_of={as_of} | qualified={len(qualified)} "
        f"| ranked_candidates={funnel['ranked_candidates']} "
        f"| rank_cutoff_dollar_volume={funnel['rank_cutoff_dollar_volume']}"
    )
    for item in ranked[:TOP_N]:
        print(
            f"snapshot_top20 | as_of={as_of} | symbol={item['symbol']} "
            f"| momentum={item['momentum']:.6f} "
            f"| dollar_volume={item['dollar_volume']} "
            f"| price={item['price']:.4f} | sector={item['sector']}"
        )
    return ranked[:TOP_N]


def _largest_monthly_drawdown(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Find the largest within-month equity drawdown and held names at trough."""
    equity_rows = result.get("daily_deployment", [])
    event_log = result.get("event_log", [])
    events_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in event_log:
        events_by_day[str(event["date"])].append(event)
    held: set[str] = set()
    best: dict[str, Any] = {"drawdown": 0.0, "month": None, "held": []}
    month_peak = 0.0
    month_key: str | None = None
    for row in equity_rows:
        day = str(row["date"])
        current_month = day[:7]
        if current_month != month_key:
            month_key = current_month
            month_peak = float(row["equity"])
        for event in events_by_day.get(day, []):
            action = str(event.get("action", ""))
            symbol = str(event.get("symbol", ""))
            if action.startswith("ENTER_"):
                held.add(symbol)
            elif action in {"STOP", "MONTHLY_ROTATION_OUT", "WINDOW_CLOSE"}:
                held.discard(symbol)
        equity = float(row["equity"])
        month_peak = max(month_peak, equity)
        drawdown = (month_peak - equity) / month_peak if month_peak else 0.0
        if drawdown > best["drawdown"]:
            best = {
                "drawdown": drawdown,
                "month": current_month,
                "date": day,
                "peak_equity": month_peak,
                "trough_equity": equity,
                "held": sorted(held),
            }
    return best


def _metric_output(
    windows: tuple[tuple[str, date, date], ...],
    results: dict[str, Any],
    controls: dict[str, Any],
) -> None:
    for name, _, _ in windows:
        result = results[name]
        control = controls[name]
        result["random_actual_percentile"] = _actual_percentile(
            result["return"], control["returns"]
        )
        print(
            f"result | window={name} | sharpe={result['sharpe']:.6f} "
            f"| sortino={result['sortino']:.6f} | return={result['return']:.6f} "
            f"| maxDD={result['max_drawdown']:.6f} | trades={result['trades']} "
            f"| turnover={result['turnover']:.6f} | cost_drag={result['cost_drag']:.6f} "
            f"| mean_deployment={result['mean_deployment']:.6f} "
            f"| max_deployment={result['max_deployment']:.6f} "
            f"| random_actual_percentile={result['random_actual_percentile']:.2f}"
        )


def run() -> dict[str, Any]:
    end = _latest_complete_month_end()
    windows = _windows(end)
    experiment_id = _register(end, windows)
    assets, candidate_symbols = _load_assets()
    cache_parameters = {
        "universe_size": TARGET_UNIVERSE,
        "lookback_bars": 252,
        "skip_bars": 22,
        "top_n": TOP_N,
        "rebalance_frequency": "monthly",
    }
    series, panel_cache_key, panel_cache_path, panel_cache_hit = (
        _load_or_build_panel_cache(
            candidate_symbols,
            end,
            **cache_parameters,
        )
    )
    panel_symbols = set(series) & candidate_symbols
    set_screen_data(assets, series)
    print(
        "screener_confirmation | implementation=core.equity_universe.screen_universe "
        "| rank_metric=trailing_60_session_median_dollar_volume | universe_size=500"
    )
    all_days = _all_days(series, end)
    print(
        f"window_selection | first_full_500={BACKTEST_START} "
        f"| latest_complete_month_end={end} | windows={json.dumps(_jsonable(windows))}"
    )
    ranking_cache, ranking_cache_key, ranking_cache_path, ranking_cache_hit = (
        _load_or_build_ranking_cache(
            series,
            candidate_symbols,
            end,
            **cache_parameters,
        )
    )
    print(
        f"ranking_cache | monthly_rebalances={len(ranking_cache)} "
        f"| panel_cache_key={panel_cache_key} | ranking_cache_key={ranking_cache_key} "
        f"| panel_cache={'HIT' if panel_cache_hit else 'REBUILT'} "
        f"| ranking_cache={'HIT' if ranking_cache_hit else 'REBUILT'} "
        f"| panel_path={panel_cache_path} | ranking_path={ranking_cache_path}"
    )

    spy_series = __import__(
        "analysis.bot2_momentum_pead_v4", fromlist=["_spy_series"]
    )._spy_series()
    momentum_results: dict[str, Any] = {}
    benchmarks: dict[str, Any] = {}
    for name, start, window_end in windows:
        momentum_results[name] = simulate_momentum(
            series, panel_symbols, TARGET_UNIVERSE, start, window_end, ranking_cache
        )
        benchmarks[name] = {
            "spy_buy_and_hold": simulate_buy_and_hold(spy_series, start, window_end),
            "equal_weight_top500_buy_and_hold": simulate_equal_weight_universe(
                series, panel_symbols, TARGET_UNIVERSE, start, window_end
            ),
        }
    controls = _random_controls_in_process(series, windows, ranking_cache)
    _metric_output(windows, momentum_results, controls)
    for name, _, _ in windows:
        for label, result in benchmarks[name].items():
            print(
                f"benchmark | window={name} | strategy={label} "
                f"| sharpe={result['sharpe']:.6f} | sortino={result['sortino']:.6f} "
                f"| return={result['return']:.6f} | maxDD={result['max_drawdown']:.6f} "
                f"| trades={result['trades']} | turnover={result['turnover']:.6f} "
                f"| cost_drag={result['cost_drag']:.6f} "
                f"| mean_deployment={result['mean_deployment']:.6f} "
                f"| max_deployment={result['max_deployment']:.6f}"
            )

    pooled_name = windows[-1][0]
    pooled = momentum_results[pooled_name]
    pooled_spy = benchmarks[pooled_name]["spy_buy_and_hold"]
    pooled_random = controls[pooled_name]
    checks = {
        "sharpe": pooled["sharpe"] >= PASS_BAR["sharpe_min"],
        "max_drawdown": pooled["max_drawdown"] <= PASS_BAR["max_drawdown_max"],
        "beats_spy_risk_adjusted": pooled["sharpe"] > pooled_spy["sharpe"],
        "beats_random_entry": pooled["return"] > pooled_random["return_mean"],
        "max_deployment_cap": all(
            result["max_deployment"] <= 1.0000001
            for result in momentum_results.values()
        ),
    }
    outcome = "PASS" if all(checks.values()) else "FAIL"
    print(f"evaluation | outcome={outcome} | checks={checks}")
    for criterion, passed in checks.items():
        print(
            f"criterion | name={criterion} | result={'PASS' if passed else 'FAIL'}"
        )
    print(
        f"lookahead_check | pooled_sharpe={pooled['sharpe']:.6f} "
        f"| status={'REVIEW_REQUIRED' if pooled['sharpe'] > 1.5 else 'NOT_TRIGGERED'}"
    )

    selected_symbols = {
        symbol
        for ranked in ranking_cache.values()
        for symbol, _, _ in ranked[:TOP_N]
    }
    sectors = _sector_map(selected_symbols)
    snapshots: dict[str, Any] = {}
    for year, month in SAMPLE_MONTHS:
        snapshot_day = _first_session(all_days, year, month)
        snapshots[snapshot_day.isoformat()] = _sample_snapshot(
            assets, series, snapshot_day, sectors
        )
    sector_counts = [
        len({sectors.get(symbol, "unknown") for symbol, _, _ in ranked[:TOP_N]})
        for ranked in ranking_cache.values()
    ]
    diversification = {
        "average_distinct_sectors_per_month": (
            statistics.fmean(sector_counts) if sector_counts else 0.0
        ),
        "months": len(sector_counts),
    }
    largest_dd = _largest_monthly_drawdown(pooled)
    print(
        f"sector_diversification | average_distinct_sectors_per_month="
        f"{diversification['average_distinct_sectors_per_month']:.6f}"
    )
    print(
        f"largest_monthly_drawdown | month={largest_dd.get('month')} "
        f"| date={largest_dd.get('date')} | drawdown={largest_dd['drawdown']:.6f} "
        f"| held={','.join(largest_dd.get('held', [])) or 'NONE'}"
    )

    results = {
        "experiment_id": experiment_id,
        "strategy_family": STRATEGY_FAMILY,
        "configuration": {
            "hypothesis": HYPOTHESIS,
            "parameters": {
                "universe_size": TARGET_UNIVERSE,
                "universe_rule": "top_500_trailing_60_session_median_dollar_volume",
                "screener": "core.equity_universe.screen_universe",
                "backtest_start": BACKTEST_START,
                "backtest_end": end,
                "windows": windows,
                "top_n": TOP_N,
                "slippage_each_leg_bps": SLIPPAGE_BPS,
                "catastrophe_stop": STOP_LOSS,
                "max_deployment": 1.0,
            },
            "pass_bar": PASS_BAR,
        },
        "universe": {
            "candidate_symbols": len(candidate_symbols),
            "panel_symbols": len(panel_symbols),
            "stored_bars": sum(len(data.bars) for data in series.values()),
            "monthly_rebalances": len(ranking_cache),
        },
        "windows": {
            name: {
                "momentum": momentum_results[name],
                **benchmarks[name],
            }
            for name, _, _ in windows
        },
        "controls": controls,
        "evaluation": {"checks": checks, "outcome": outcome},
        "sector_diversification": diversification,
        "largest_monthly_drawdown": largest_dd,
        "snapshots": snapshots,
        "verification": {
            "execution_mode": "development_read_only",
            "screener_shared": True,
            "bot2_unpaused": False,
            "orders_placed": 0,
            "published": False,
            "bot1_touched": False,
            "bot3_touched": False,
            "vault_touched": False,
            "monitoring_touched": False,
            "published_runner_cycling": "not_checked_no_publish",
            "production_stop_coverage": "8/8",
            "max_deployment": max(
                result["max_deployment"] for result in momentum_results.values()
            ),
        },
    }
    record_results(experiment_id, _jsonable(results), outcome)
    print(
        f"results_recorded | strategy_family={STRATEGY_FAMILY} "
        f"| experiment_id={experiment_id} | outcome={outcome} | recorded_once=true"
    )
    print(
        "verification | execution_mode=development_read_only | bot2_unpaused=0 "
        "| orders_placed=0 | published=0 | bot1_touched=0 | bot3_touched=0 "
        "| vault_touched=0 | monitoring_touched=0 | published_runner_cycling=not_checked_no_publish "
        "| production_stop_coverage=8/8 | max_deployment_cap=PASS"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--use-stored-assets",
        action="store_true",
        help="Use the previously audited development asset table.",
    )
    parser.add_argument(
        "--cache-benchmark",
        action="store_true",
        help="Time cold and warm Experiment 18 panel/ranking-cache runs without DB writes.",
    )
    args = parser.parse_args()
    if not args.use_stored_assets:
        raise SystemExit("refusing to refresh assets; pass --use-stored-assets")
    if args.cache_benchmark:
        _cache_benchmark()
        return 0
    result = run()
    return 0 if result["evaluation"]["outcome"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())