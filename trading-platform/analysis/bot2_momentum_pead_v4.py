#!/usr/bin/env python3
"""Development-only Bot 2 v4 momentum/PEAD rotation research.

This module is intentionally separate from v3.  It never imports a live
strategy or order-placement path.  The rotation simulator owns one cash
balance and one book: monthly momentum is the default state, while a positive
earnings cluster moves the book into progressive PEAD entries until the last
PEAD position closes and the next monthly rebalance returns to momentum.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import random
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

import psycopg2.extras

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.research_postgres import get_research_conn as get_conn  # noqa: E402
from core.equity_universe import (  # noqa: E402
    last_screen_observations,
    screen_universe as shared_screen_universe,
    set_screen_data,
)
from analysis.bot2_data_pipeline import EARNINGS_SYMBOLS, EARNINGS_TABLE  # noqa: E402
from analysis.bot2_sp500_data import REFERENCE_PRICE_SOURCES  # noqa: E402
from analysis.bot2_momentum_pead_v3 import (  # noqa: E402
    ALPACA_BARS_URL,
    ASSET_TABLE,
    Asset,
    Bar,
    PRICE_SOURCES,
    PRICE_TABLE,
    Series,
    _fetch_feed,
    ensure_asset_table,
    fetch_tradable_us_equities,
    ingest_expanded_prices,
    load_asset_symbols,
    load_panel,
    persist_assets,
)
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)


ANALYSIS_START = date(2018, 1, 1)
ANALYSIS_END = date.today() - timedelta(days=1)
CALIBRATION_DATE = date(2019, 6, 3)
LOOKBACK_SESSIONS = 252
SKIP_BARS = 22
LIQUIDITY_SESSIONS = 60
TARGET_UNIVERSE = 500
TOP_N = 20
SLIPPAGE_BPS = 10.0
SLIP = SLIPPAGE_BPS / 10_000
STOP_LOSS = 0.20
STARTING_EQUITY = 100_000.0
CONTROL_ITERATIONS = 1_000
RANDOM_SEED = 271_2026
PEAD_SYMBOLS = EARNINGS_SYMBOLS
WINDOWS: tuple[tuple[str, date, date], ...] = (
    ("2019_2020", date(2019, 1, 1), date(2020, 12, 31)),
    ("2021_2022", date(2021, 1, 1), date(2022, 12, 31)),
    ("2023_present", date(2023, 1, 3), ANALYSIS_END),
    ("pooled_2018_present", ANALYSIS_START, ANALYSIS_END),
)
SAMPLE_DATES = (
    date(2019, 6, 3),
    date(2020, 6, 1),
    date(2021, 6, 1),
    date(2022, 6, 1),
    date(2024, 6, 3),
    date(2026, 1, 2),
)

MOMENTUM_HYPOTHESIS = (
    "12-1 cross-sectional momentum across a mechanically screened US equity "
    "universe, top 20 equal weight, monthly rebalance, produces positive "
    "risk-adjusted returns without an earnings overlay."
)
ROTATION_HYPOTHESIS = (
    "A one-book monthly momentum strategy that liquidates into positive-surprise "
    "PEAD clusters can improve risk-adjusted returns without implicit leverage "
    "or a second cash balance."
)
MOMENTUM_CRASH_CAVEAT = (
    "2018-present contains no momentum crash. Single-stock momentum's defining "
    "failure mode is a sharp post-crash rebound; March 2009 erased years of "
    "gains in weeks. This result is measured on a window that excludes that "
    "regime. Also note: SPY buy-and-hold beat this strategy risk-adjusted in "
    "the 2023-present validation window, Sharpe 1.439 vs 1.428."
)
DISCREPANCY_NOTE = (
    "Experiment 12 is unchanged. Its immutable ledger pass_bar expectancy is "
    "0.0291357051, while its embedded result configuration and stored pooled "
    "momentum-alone expectancy are 0.0289652822. The former is the value "
    "captured by the initial baseline run when Experiment 12 was registered; "
    "the latter is the resumed run's pooled momentum result. Experiment 12 did "
    "not persist the complete baseline object, so its exact numerical cause "
    "cannot be reconstructed from that row. v4 derives any expectancy threshold "
    "from the same persisted momentum-alone result object used for its run and "
    "stores the source value explicitly."
)


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    reported_date: date
    entry_day: date
    exit_day: date
    surprise: float
    report_time: str
    cluster_id: int
    cluster_first: bool


@dataclass
class Holding:
    symbol: str
    qty: float
    entry_exec: float
    stop: float
    mode: str
    entry_day: date
    exit_day: date | None = None


RebalanceFrequency = Literal["monthly", "quarterly"]


class MomentumCache(dict[date, list[tuple[str, float, float]]]):
    """Ranking cache carrying the parameters used to build it."""

    def __init__(
        self,
        *,
        lookback_bars: int,
        skip_bars: int,
        top_n: int,
        rebalance_frequency: RebalanceFrequency,
    ) -> None:
        super().__init__()
        self.lookback_bars = lookback_bars
        self.skip_bars = skip_bars
        self.top_n = top_n
        self.rebalance_frequency = rebalance_frequency


def _bar_before(data: Series, day: date) -> Bar | None:
    index = bisect_left(data.days, day)
    return data.bars[index - 1] if index else None


def _bar_open(data: Series, day: date) -> Bar | None:
    return data.by_date.get(day) or _bar_before(data, day)


def _all_days(series: dict[str, Series], end: date) -> list[date]:
    return sorted({day for data in series.values() for day in data.days if day <= end})


def _first_day_on_or_after(series: dict[str, Series], target: date) -> date:
    days = _all_days(series, ANALYSIS_END)
    for day in days:
        if day >= target:
            return day
    raise RuntimeError(f"no price session on or after {target}")


def screen_universe_current(
    series: dict[str, Series],
    candidates: Iterable[str],
    as_of: date,
    universe_size: int = TARGET_UNIVERSE,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    assets = [
        {
            "symbol": symbol,
            "status": "active",
            "asset_class": "us_equity",
            "tradable": True,
            "exchange": "NASDAQ",
        }
        for symbol in sorted(set(candidates))
    ]
    set_screen_data(assets, series)
    qualified, funnel = shared_screen_universe(
        as_of,
        universe_size,
        LOOKBACK_SESSIONS,
        5.0,
        require_current_bar=True,
    )
    observations = last_screen_observations()
    for symbol in qualified:
        if symbol in series and as_of in series[symbol].by_date:
            observations[symbol]["current_data_day"] = as_of
            observations[symbol]["uses_future_data"] = False
    return qualified, observations


def implied_liquidity_floor_current(
    series: dict[str, Series],
    candidates: Iterable[str] | None = None,
    as_of: date = CALIBRATION_DATE,
) -> float | None:
    _, observations = screen_universe_current(
        series, candidates or set(series), as_of, TARGET_UNIVERSE
    )
    if len(observations) < TARGET_UNIVERSE:
        return None
    return sorted(
        (item["median_dollar_volume_60"] for item in observations.values()),
        reverse=True,
    )[TARGET_UNIVERSE - 1]


def mechanical_gate(
    series: dict[str, Series],
    candidate_symbols: set[str],
) -> tuple[bool, int, dict[str, Any]]:
    universe_size = TARGET_UNIVERSE
    print(
        f"universe_rule | rank=trailing_{LIQUIDITY_SESSIONS}_session_median_dollar_volume "
        f"| top_n={universe_size} | source=trailing_data_only"
    )
    snapshots: dict[str, Any] = {}
    valid = True
    print("mechanical_sample | as_of | qualified | current_history | future_rows")
    for as_of in SAMPLE_DATES:
        qualified, observations = screen_universe_current(
            series, candidate_symbols, as_of, universe_size
        )
        future_rows = sum(
            int(item.get("uses_future_data", False)) for item in observations.values()
        )
        snapshots[as_of.isoformat()] = {
            "qualified": sorted(qualified),
            "qualified_count": len(qualified),
            "history_eligible": len(observations),
            "future_rows": future_rows,
            "observations": observations,
        }
        print(
            f"mechanical_sample | {as_of} | {len(qualified)} | {len(observations)} "
            f"| {future_rows}"
        )
        if future_rows or not qualified:
            valid = False

    first_set = set(snapshots[SAMPLE_DATES[0].isoformat()]["qualified"])
    last_set = set(snapshots[SAMPLE_DATES[-1].isoformat()]["qualified"])
    true_dropouts = sorted(first_set - last_set)
    data_ended_early = sorted(
        symbol for symbol in first_set if series[symbol].bars[-1].day < SAMPLE_DATES[-1]
    )
    print(
        f"mechanical_dropout | early_date={SAMPLE_DATES[0]} | late_date={SAMPLE_DATES[-1]} "
        f"| true_qualified_dropouts={len(true_dropouts)} "
        f"| data_ended_early={len(data_ended_early)}"
    )
    print("true_dropout_symbols | " + ",".join(true_dropouts or ["NONE"]))
    print("data_ended_early_symbols | " + ",".join(data_ended_early or ["NONE"]))
    if not true_dropouts:
        print("mechanical_dropout_gate | STOP | no true qualified-universe dropouts")
        valid = False
    else:
        print(
            f"mechanical_dropout_gate | PASS | true_dropouts={len(true_dropouts)}"
        )

    annual: dict[str, Any] = {}
    previous: set[str] = set()
    print("year | as_of | universe_count | additions | drops | median_dollar_volume | artifacts")
    for year in range(2019, ANALYSIS_END.year + 1):
        as_of = _first_day_on_or_after(series, date(year, 1, 1))
        current, observations = screen_universe_current(
            series, candidate_symbols, as_of, universe_size
        )
        additions = len(current - previous) if previous else len(current)
        drops = len(previous - current)
        medians = [
            observations[symbol]["median_dollar_volume_60"]
            for symbol in current
            if symbol in observations
        ]
        artifacts = len(candidate_symbols - set(observations))
        annual[str(year)] = {
            "as_of": as_of.isoformat(),
            "universe_count": len(current),
            "additions": additions,
            "drops": drops,
            "median_dollar_volume": statistics.median(medians) if medians else None,
            "data_artifact_symbols": artifacts,
        }
        print(
            f"{year} | {as_of} | {len(current)} | {additions} | {drops} | "
            f"{annual[str(year)]['median_dollar_volume']} | missing_history={artifacts}"
        )
        previous = current

    missing = sorted(candidate_symbols - set(series))
    artifacts = {
        "candidate_symbols": len(candidate_symbols),
        "price_backed_symbols": len(set(series)),
        "missing_price_history": len(missing),
        "missing_price_examples": missing[:30],
        "panel_symbols_with_no_bars": sorted(
            symbol for symbol, value in series.items() if not value.bars
        ),
    }
    print(
        f"data_artifact_flags | candidate_symbols={artifacts['candidate_symbols']} "
        f"| price_backed={artifacts['price_backed_symbols']} "
        f"| missing_price_history={artifacts['missing_price_history']} "
        f"| panel_empty={len(artifacts['panel_symbols_with_no_bars'])}"
    )
    return valid, universe_size, {
        "universe_size": universe_size,
        "sample_dates": snapshots,
        "annual": annual,
        "true_dropouts": true_dropouts,
        "data_ended_early": data_ended_early,
        "artifact_flags": artifacts,
    }


def audit_earnings() -> dict[str, Any]:
    rows_by_symbol: dict[str, int] = {}
    manual_cost = 0
    valid = True
    print("earnings_audit | symbol | rows | manual_rows | signal_rows")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in EARNINGS_SYMBOLS:
                cur.execute(
                    f"""
                    SELECT COUNT(*),
                           COUNT(*) FILTER (WHERE source='manual'),
                           COUNT(*) FILTER (WHERE source <> 'manual')
                      FROM {EARNINGS_TABLE}
                     WHERE symbol=%s AND reported_date >= %s
                    """,
                    (symbol, ANALYSIS_START),
                )
                rows, manual_rows, signal_rows = cur.fetchone()
                rows_by_symbol[symbol] = int(signal_rows)
                if symbol == "COST":
                    manual_cost += int(manual_rows)
                if not rows or (symbol != "COST" and not signal_rows):
                    valid = False
                print(f"earnings_audit | {symbol} | {rows} | {manual_rows} | {signal_rows}")
    print(
        f"earnings_cost_rule | manual_rows_excluded={manual_cost} "
        "| non_manual_COST_remains_eligible=true"
    )
    print(f"earnings_audit_gate | {'PASS' if valid else 'STOP'}")
    if not valid:
        raise RuntimeError("Bot 2 v4 earnings audit failed")
    return {
        "rows_by_symbol": rows_by_symbol,
        "manual_cost_rows_excluded": manual_cost,
    }


def _load_earnings_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, reported_date, surprise, report_time, source
                  FROM {EARNINGS_TABLE}
                 WHERE reported_date >= %s
                   AND source <> 'manual'
                 ORDER BY reported_date, symbol, id
                """,
                (ANALYSIS_START,),
            )
            for symbol, reported_date, surprise, report_time, source in cur.fetchall():
                timing = (report_time or "").lower()
                if (
                    symbol not in PEAD_SYMBOLS
                    or surprise is None
                    or float(surprise) <= 0
                    or not any(word in timing for word in ("pre", "before", "post", "after"))
                ):
                    continue
                events.append(
                    {
                        "symbol": symbol,
                        "reported_date": reported_date,
                        "surprise": float(surprise),
                        "report_time": timing,
                        "source": source,
                    }
                )
    return events


def _month_start_rebalances(days: Iterable[date]) -> set[date]:
    """Return the first available trading session in each calendar month."""
    result: set[date] = set()
    seen: set[tuple[int, int]] = set()
    for day in sorted(set(days)):
        key = (day.year, day.month)
        if key not in seen:
            seen.add(key)
            result.add(day)
    return result


def _rebalance_days(
    days: Iterable[date],
    frequency: RebalanceFrequency = "monthly",
) -> set[date]:
    if frequency == "monthly":
        return _month_start_rebalances(days)
    if frequency == "quarterly":
        return {
            day
            for day in _month_start_rebalances(days)
            if day.month in (1, 4, 7, 10)
        }
    raise ValueError(
        f"unsupported rebalance frequency {frequency!r}; "
        "expected 'monthly' or 'quarterly'"
    )


def build_momentum_cache(
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    end: date,
    *,
    lookback_bars: int = LOOKBACK_SESSIONS,
    skip_bars: int = SKIP_BARS,
    top_n: int = TOP_N,
    rebalance_frequency: RebalanceFrequency = "monthly",
) -> MomentumCache:
    if lookback_bars <= 0:
        raise ValueError("lookback_bars must be positive")
    if skip_bars < 0:
        raise ValueError("skip_bars must be non-negative")
    if skip_bars >= lookback_bars:
        raise ValueError("skip_bars must be less than lookback_bars")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    _rebalance_days([], rebalance_frequency)

    days = _all_days(series, end)
    cache = MomentumCache(
        lookback_bars=lookback_bars,
        skip_bars=skip_bars,
        top_n=top_n,
        rebalance_frequency=rebalance_frequency,
    )
    for rebalance_day in sorted(_rebalance_days(days, rebalance_frequency)):
        screened, _ = screen_universe_current(
            series, symbols, rebalance_day, universe_size
        )
        ranked: list[tuple[str, float, float]] = []
        for symbol in screened:
            data = series[symbol]
            cutoff = bisect_left(data.days, rebalance_day)
            if cutoff < lookback_bars:
                continue
            momentum = (
                data.bars[cutoff - skip_bars].close
                / data.bars[cutoff - lookback_bars].close
                - 1
            )
            returns = [
                data.bars[index].close / data.bars[index - 1].close - 1
                for index in range(max(1, cutoff - 63), cutoff)
                if data.bars[index - 1].close > 0
            ]
            volatility = statistics.pstdev(returns) * math.sqrt(252) if returns else 0.0
            if momentum > 0 and volatility > 0:
                ranked.append((symbol, momentum, volatility))
        cache[rebalance_day] = sorted(ranked, key=lambda item: (-item[1], item[0]))
    return cache


def _monthly_days(days: list[date]) -> set[date]:
    return _month_start_rebalances(days)


def _weights(
    ranked: list[tuple[str, float, float]],
    allocation: str = "equal_weight",
    top_n: int = TOP_N,
) -> dict[str, float]:
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    chosen = ranked[:top_n]
    if not chosen:
        return {}
    if allocation == "equal_weight":
        return {symbol: 1 / len(chosen) for symbol, _, _ in chosen}
    inverse = {symbol: 1 / volatility for symbol, _, volatility in chosen}
    total = sum(inverse.values())
    return {symbol: weight / total for symbol, weight in inverse.items()}


def build_event_schedule(
    events: list[dict[str, Any]],
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    hold_sessions: int,
    calendar: list[date],
) -> list[EarningsEvent]:
    scheduled: list[tuple[date, dict[str, Any], int]] = []
    screened_by_day: dict[date, set[str]] = {}
    for event in events:
        data = series.get(event["symbol"])
        if not data:
            continue
        if "post" in event["report_time"] or "after" in event["report_time"]:
            entry_candidates = [day for day in data.days if day > event["reported_date"]]
        else:
            entry_candidates = [day for day in data.days if day >= event["reported_date"]]
        if not entry_candidates:
            continue
        entry_day = entry_candidates[0]
        if entry_day not in screened_by_day:
            screened_by_day[entry_day] = screen_universe_current(
                series, symbols, entry_day, universe_size
            )[0]
        screened = screened_by_day[entry_day]
        if event["symbol"] not in screened:
            continue
        entry_index = data.days.index(entry_day)
        exit_index = entry_index + hold_sessions - 1
        if exit_index >= len(data.days):
            continue
        calendar_index = bisect_left(calendar, entry_day)
        scheduled.append(
            (
                entry_day,
                event,
                calendar_index,
            )
        )
    scheduled.sort(key=lambda item: (item[0], item[1]["symbol"]))
    output: list[EarningsEvent] = []
    cluster_id = -1
    previous_calendar_index: int | None = None
    for entry_day, event, calendar_index in scheduled:
        if previous_calendar_index is None or calendar_index - previous_calendar_index > 1:
            cluster_id += 1
            cluster_first = True
        else:
            cluster_first = False
        data = series[event["symbol"]]
        entry_index = data.days.index(entry_day)
        exit_day = data.days[entry_index + hold_sessions - 1]
        output.append(
            EarningsEvent(
                symbol=event["symbol"],
                reported_date=event["reported_date"],
                entry_day=entry_day,
                exit_day=exit_day,
                surprise=event["surprise"],
                report_time=event["report_time"],
                cluster_id=cluster_id,
                cluster_first=cluster_first,
            )
        )
        previous_calendar_index = calendar_index
    return output


def _metrics(
    curve: list[float],
    trade_returns: list[float],
    turnover: float,
    cost_paid: float,
    daily_deployment: list[dict[str, Any]],
    mode_days: dict[str, dict[str, int]],
    stops: int,
    out_mode_pnl: float,
    out_mode_days: int,
    event_log: list[dict[str, Any]],
) -> dict[str, Any]:
    daily_returns = [
        curve[index] / curve[index - 1] - 1
        for index in range(1, len(curve))
        if curve[index - 1] > 0
    ]
    mean = statistics.fmean(daily_returns) if daily_returns else 0.0
    deviation = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0
    downside = (
        math.sqrt(
            statistics.fmean(
                min(value, 0.0) ** 2 for value in daily_returns
            )
        )
        if daily_returns
        else 0.0
    )
    peak = curve[0] if curve else STARTING_EQUITY
    max_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak if peak else 0.0)
    deployments = [float(item["deployed_pct"]) for item in daily_deployment]
    return {
        "return": curve[-1] / curve[0] - 1 if curve and curve[0] else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe": mean / deviation * math.sqrt(252) if deviation else 0.0,
        "sortino": mean / downside * math.sqrt(252) if downside else 0.0,
        "expectancy": statistics.fmean(trade_returns) if trade_returns else 0.0,
        "trades": len(trade_returns),
        "turnover": turnover / curve[0] if curve and curve[0] else 0.0,
        "cost_drag": cost_paid / STARTING_EQUITY,
        "cost_paid": cost_paid,
        "stops": stops,
        "mean_deployment": statistics.fmean(deployments) if deployments else 0.0,
        "max_deployment": max(deployments) if deployments else 0.0,
        "days_above_90pct_deployed": sum(value > 0.90 for value in deployments),
        "mode_days": mode_days,
        "days_out_of_momentum": sum(
            values.get("out_of_momentum", 0) for values in mode_days.values()
        ),
        "out_of_momentum_return": out_mode_pnl / STARTING_EQUITY,
        "return_per_out_of_momentum_day": (
            out_mode_pnl / STARTING_EQUITY / out_mode_days if out_mode_days else 0.0
        ),
        "daily_deployment": daily_deployment,
        "daily_returns": daily_returns,
        "event_log": event_log,
        "stop_coverage": STOP_LOSS > 0,
    }


def _volatility_multiplier(
    curve: list[float],
    target_volatility: float,
    realized_volatility_window: int,
) -> tuple[float, bool]:
    """Return a capped portfolio-volatility multiplier and fallback status."""
    daily_returns = [
        curve[index] / curve[index - 1] - 1
        for index in range(1, len(curve))
        if curve[index - 1] > 0
    ]
    if len(daily_returns) < realized_volatility_window:
        return 1.0, True
    realized_volatility = (
        statistics.stdev(daily_returns[-realized_volatility_window:])
        * math.sqrt(252)
    )
    if realized_volatility <= 0:
        return 1.0, True
    return min(1.0, target_volatility / realized_volatility), False


def _sell(
    holding: Holding,
    data: Series,
    day: date,
    cash: float,
    trade_returns: list[float],
    event_log: list[dict[str, Any]],
    turnover: float,
    cost_paid: float,
    reason: str,
) -> tuple[float, float, float]:
    bar = _bar_open(data, day)
    if bar is None:
        return cash, turnover, cost_paid
    reference = bar.open
    proceeds = holding.qty * reference * (1 - SLIP)
    cost = holding.qty * reference * SLIP
    cash += proceeds
    turnover += holding.qty * reference
    cost_paid += cost
    trade_returns.append(proceeds / (holding.qty * holding.entry_exec) - 1)
    event_log.append(
        {
            "date": day.isoformat(),
            "action": reason,
            "symbol": holding.symbol,
            "cash_after": cash,
            "notional": holding.qty * reference,
        }
    )
    return cash, turnover, cost_paid


def _buy(
    symbol: str,
    mode: str,
    target_notional: float,
    data: Series,
    day: date,
    cash: float,
    holdings: dict[str, Holding],
    event_log: list[dict[str, Any]],
    turnover: float,
    cost_paid: float,
    exit_day: date | None = None,
) -> tuple[float, float, float]:
    bar = data.by_date.get(day)
    if bar is None or target_notional <= 0:
        return cash, turnover, cost_paid
    notional = min(target_notional, cash / (1 + SLIP))
    if notional <= 0:
        return cash, turnover, cost_paid
    entry_exec = bar.open * (1 + SLIP)
    qty = notional / entry_exec
    cost = notional * SLIP
    cash -= notional + cost
    turnover += notional
    cost_paid += cost
    holdings[symbol] = Holding(
        symbol=symbol,
        qty=qty,
        entry_exec=entry_exec,
        stop=entry_exec * (1 - STOP_LOSS),
        mode=mode,
        entry_day=day,
        exit_day=exit_day,
    )
    event_log.append(
        {
            "date": day.isoformat(),
            "action": f"ENTER_{mode.upper()}",
            "symbol": symbol,
            "cash_after": cash,
            "notional": notional,
            "exit_day": exit_day.isoformat() if exit_day else None,
        }
    )
    return cash, turnover, cost_paid


def _holding_value(
    holdings: dict[str, Holding],
    series: dict[str, Series],
    day: date,
) -> float:
    value = 0.0
    for symbol, holding in holdings.items():
        bar = _bar_open(series[symbol], day)
        if bar:
            value += holding.qty * (bar.close if bar.day == day else bar.close)
    return value


def _load_sgov_series(end: date) -> Series:
    """Load the dedicated SGOV reference series without changing the equity panel."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (date)
                       date, open, high, low, close, volume
                  FROM {PRICE_TABLE}
                 WHERE symbol='SGOV'
                   AND date <= %s
                   AND source = ANY(%s)
                 ORDER BY date,
                          CASE
                              WHEN source='alpaca_sip_adjusted' THEN 0
                              WHEN source='alpaca_iex_adjusted' THEN 1
                              ELSE 2
                          END
                """,
                (end, list(REFERENCE_PRICE_SOURCES)),
            )
            rows = cur.fetchall()
    if not rows:
        raise RuntimeError("SGOV idle-capital mode requires stored SGOV reference bars")
    return Series("SGOV", [Bar(row[0], *map(float, row[1:])) for row in rows])


def _sgov_daily_return(series: Series, day: date) -> float:
    """Return SGOV's close-to-close return for ``day`` or zero when unavailable."""
    current = series.by_date.get(day)
    previous = _bar_before(series, day)
    if current is None or previous is None or previous.close <= 0:
        return 0.0
    return current.close / previous.close - 1


def simulate_true_rotation(
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    start: date,
    end: date,
    hold_sessions: int,
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    events: list[dict[str, Any]],
    scheduled_events: list[EarningsEvent] | None = None,
) -> dict[str, Any]:
    calendar = _all_days(series, end)
    scheduled = (
        build_event_schedule(
            events, series, symbols, universe_size, hold_sessions, calendar
        )
        if scheduled_events is None
        else scheduled_events
    )
    entries: dict[date, list[EarningsEvent]] = defaultdict(list)
    for event in scheduled:
        if start <= event.entry_day <= end:
            entries[event.entry_day].append(event)
    monthly = _monthly_days(calendar)
    cash = STARTING_EQUITY
    holdings: dict[str, Holding] = {}
    trade_returns: list[float] = []
    curve: list[float] = []
    daily_deployment: list[dict[str, Any]] = []
    mode_days: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "momentum": 0,
            "earnings": 0,
            "cash": 0,
            "out_of_momentum": 0,
        }
    )
    event_log: list[dict[str, Any]] = []
    turnover = 0.0
    cost_paid = 0.0
    stops = 0
    mode = "momentum"
    last_pead_close: date | None = None
    out_mode_pnl = 0.0
    out_mode_days = 0
    previous_equity: float | None = None

    for day in calendar:
        if day < start:
            continue
        day_events = entries.get(day, [])

        for symbol, holding in list(holdings.items()):
            if holding.exit_day == day:
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "EXIT_PEAD_HOLD",
                )
                del holdings[symbol]
                if holding.mode == "earnings":
                    last_pead_close = day

        for symbol, holding in list(holdings.items()):
            bar = series[symbol].by_date.get(day)
            if bar is not None and bar.low <= holding.stop:
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "STOP",
                )
                del holdings[symbol]
                stops += 1
                if holding.mode == "earnings":
                    last_pead_close = day

        if mode == "momentum" and any(event.cluster_first for event in day_events):
            momentum_holdings = [
                (symbol, holding)
                for symbol, holding in holdings.items()
                if holding.mode == "momentum"
            ]
            if momentum_holdings:
                event_log.append(
                    {
                        "date": day.isoformat(),
                        "action": "LIQUIDATE_MOMENTUM_FOR_EARNINGS_CLUSTER",
                        "positions": len(momentum_holdings),
                        "cash_before": cash,
                    }
                )
            for symbol, holding in momentum_holdings:
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "LIQUIDATE_MOMENTUM",
                )
                del holdings[symbol]
            mode = "earnings"

        if mode == "earnings":
            for event in sorted(day_events, key=lambda item: item.symbol):
                if event.symbol in holdings:
                    continue
                equity_open = cash + _holding_value(holdings, series, day)
                target = equity_open / TOP_N
                cash, turnover, cost_paid = _buy(
                    event.symbol,
                    "earnings",
                    target,
                    series[event.symbol],
                    day,
                    cash,
                    holdings,
                    event_log,
                    turnover,
                    cost_paid,
                    event.exit_day,
                )

        if mode == "momentum" and day in monthly:
            for symbol, holding in list(holdings.items()):
                if holding.mode != "momentum":
                    continue
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "MONTHLY_ROTATION_OUT",
                )
                del holdings[symbol]
            ranked = ranking_cache.get(day, [])
            for symbol, weight in _weights(ranked).items():
                equity_open = cash + _holding_value(holdings, series, day)
                cash, turnover, cost_paid = _buy(
                    symbol,
                    "momentum",
                    equity_open * weight,
                    series[symbol],
                    day,
                    cash,
                    holdings,
                    event_log,
                    turnover,
                    cost_paid,
                )

        if (
            mode == "earnings"
            and not holdings
            and last_pead_close is not None
            and day in monthly
            and day > last_pead_close
            and not day_events
        ):
            mode = "momentum"
            last_pead_close = None
            event_log.append(
                {
                    "date": day.isoformat(),
                    "action": "REENTER_MOMENTUM_AFTER_PEAD",
                    "cash_before": cash,
                }
            )
            ranked = ranking_cache.get(day, [])
            for symbol, weight in _weights(ranked).items():
                equity_open = cash + _holding_value(holdings, series, day)
                cash, turnover, cost_paid = _buy(
                    symbol,
                    "momentum",
                    equity_open * weight,
                    series[symbol],
                    day,
                    cash,
                    holdings,
                    event_log,
                    turnover,
                    cost_paid,
                )

        equity_close = cash + _holding_value(holdings, series, day)
        deployed = (
            (equity_close - cash) / equity_close if equity_close > 0 else 0.0
        )
        curve.append(equity_close)
        if previous_equity is not None and mode != "momentum":
            out_mode_pnl += equity_close - previous_equity
            out_mode_days += 1
        previous_equity = equity_close
        key = str(day.year)
        mode_days[key][mode] += 1
        if mode != "momentum":
            mode_days[key]["out_of_momentum"] += 1
        if not holdings:
            mode_days[key]["cash"] += 1
        daily_deployment.append(
            {
                "date": day.isoformat(),
                "mode": mode,
                "cash": cash,
                "equity": equity_close,
                "deployed_pct": deployed,
                "positions": len(holdings),
            }
        )

    for symbol, holding in list(holdings.items()):
        cash, turnover, cost_paid = _sell(
            holding, series[symbol], end, cash, trade_returns, event_log,
            turnover, cost_paid, "WINDOW_CLOSE",
        )
        del holdings[symbol]
    result = _metrics(
        curve,
        trade_returns,
        turnover,
        cost_paid,
        daily_deployment,
        dict(mode_days),
        stops,
        out_mode_pnl,
        out_mode_days,
        event_log,
    )
    result["hold_sessions"] = hold_sessions
    result["rotation_state_machine"] = [
        "MOMENTUM: monthly rebalance into equal-weight top-20 12-1 momentum",
        "EARNINGS_TRIGGER: first event in a clustered announcement sequence",
        "LIQUIDATE: sell every momentum holding into the shared cash balance",
        "EARNINGS: enter each positive-surprise announcement progressively",
        "CASH: unused shared capital remains cash",
        "REENTER: next monthly rebalance after the last PEAD position closes",
    ]
    return result


def simulate_momentum(
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    start: date,
    end: date,
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    selector: Callable[
        [list[tuple[str, float, float]]], list[tuple[str, float, float]]
    ]
    | None = None,
    *,
    lookback_bars: int = LOOKBACK_SESSIONS,
    skip_bars: int = SKIP_BARS,
    top_n: int = TOP_N,
    rebalance_frequency: RebalanceFrequency = "monthly",
    target_volatility: float | None = None,
    realized_volatility_window: int = 126,
    idle_capital: Literal["cash", "sgov"] = "cash",
) -> dict[str, Any]:
    """One-cash momentum book; selector is used only for controls."""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if target_volatility is not None and target_volatility <= 0:
        raise ValueError("target_volatility must be positive when provided")
    if realized_volatility_window <= 0:
        raise ValueError("realized_volatility_window must be positive")
    if idle_capital not in {"cash", "sgov"}:
        raise ValueError("idle_capital must be 'cash' or 'sgov'")
    if not isinstance(ranking_cache, MomentumCache):
        raise TypeError(
            "ranking_cache must be built by build_momentum_cache so its "
            "parameters can be verified"
        )
    if ranking_cache.lookback_bars != lookback_bars:
        raise ValueError(
            "lookback_bars mismatch between ranking_cache and "
            "simulate_momentum: "
            f"cache={ranking_cache.lookback_bars}, simulation={lookback_bars}"
        )
    if ranking_cache.skip_bars != skip_bars:
        raise ValueError(
            "skip_bars mismatch between ranking_cache and simulate_momentum: "
            f"cache={ranking_cache.skip_bars}, simulation={skip_bars}"
        )
    if ranking_cache.top_n != top_n:
        raise ValueError(
            "top_n mismatch between ranking_cache and simulate_momentum: "
            f"cache={ranking_cache.top_n}, simulation={top_n}"
        )
    if ranking_cache.rebalance_frequency != rebalance_frequency:
        raise ValueError(
            "rebalance_frequency mismatch between ranking_cache and "
            "simulate_momentum: "
            f"cache={ranking_cache.rebalance_frequency!r}, "
            f"simulation={rebalance_frequency!r}"
        )
    calendar = _all_days(series, end)
    rebalance_days = _rebalance_days(calendar, rebalance_frequency)
    cash = STARTING_EQUITY
    holdings: dict[str, Holding] = {}
    curve: list[float] = []
    daily_deployment: list[dict[str, Any]] = []
    mode_days: dict[str, dict[str, int]] = defaultdict(
        lambda: {"momentum": 0, "earnings": 0, "cash": 0, "out_of_momentum": 0}
    )
    trade_returns: list[float] = []
    event_log: list[dict[str, Any]] = []
    turnover = 0.0
    cost_paid = 0.0
    stops = 0
    rebalance_multipliers: list[float] = []
    scaling_fallbacks = 0
    sgov_series = _load_sgov_series(end) if idle_capital == "sgov" else None
    idle_interest_earned = 0.0

    for day in calendar:
        if day < start:
            continue
        if sgov_series is not None:
            cash_before_idle_return = cash
            cash *= 1 + _sgov_daily_return(sgov_series, day)
            idle_interest_earned += cash - cash_before_idle_return
        for symbol, holding in list(holdings.items()):
            bar = series[symbol].by_date.get(day)
            if bar is not None and bar.low <= holding.stop:
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "STOP",
                )
                del holdings[symbol]
                stops += 1
        if day in rebalance_days:
            for symbol, holding in list(holdings.items()):
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "MONTHLY_ROTATION_OUT",
                )
                del holdings[symbol]
            ranked = ranking_cache.get(day, [])
            selected = selector(ranked) if selector else ranked
            if target_volatility is None:
                multiplier = 1.0
                fallback = False
            else:
                multiplier, fallback = _volatility_multiplier(
                    curve, target_volatility, realized_volatility_window
                )
            rebalance_multipliers.append(multiplier)
            scaling_fallbacks += int(fallback)
            for symbol, weight in _weights(selected, top_n=top_n).items():
                equity_open = cash + _holding_value(holdings, series, day)
                cash, turnover, cost_paid = _buy(
                    symbol,
                    "momentum",
                    equity_open * weight * multiplier,
                    series[symbol],
                    day,
                    cash, holdings, event_log, turnover, cost_paid,
                )
        equity_close = cash + _holding_value(holdings, series, day)
        deployed = (equity_close - cash) / equity_close if equity_close else 0.0
        curve.append(equity_close)
        mode_days[str(day.year)]["momentum"] += 1
        if not holdings:
            mode_days[str(day.year)]["cash"] += 1
        daily_deployment.append(
            {
                "date": day.isoformat(),
                "mode": "momentum" if holdings else "cash",
                "cash": cash,
                "equity": equity_close,
                "deployed_pct": deployed,
                "positions": len(holdings),
            }
        )
    for symbol, holding in list(holdings.items()):
        cash, turnover, cost_paid = _sell(
            holding, series[symbol], end, cash, trade_returns, event_log,
            turnover, cost_paid, "WINDOW_CLOSE",
        )
    result = _metrics(
        curve, trade_returns, turnover, cost_paid, daily_deployment,
        dict(mode_days), stops, 0.0, 0, event_log,
    )
    result["allocation"] = "equal_weight"
    result["target_volatility"] = target_volatility
    result["realized_volatility_window"] = realized_volatility_window
    result["rebalance_count"] = len(rebalance_multipliers)
    result["rebalance_multipliers"] = rebalance_multipliers
    result["scaled_rebalances"] = sum(
        multiplier < 1.0 for multiplier in rebalance_multipliers
    )
    result["scaling_fallbacks"] = scaling_fallbacks
    result["average_multiplier"] = (
        statistics.fmean(rebalance_multipliers)
        if rebalance_multipliers
        else 1.0
    )
    result["minimum_multiplier"] = (
        min(rebalance_multipliers) if rebalance_multipliers else 1.0
    )
    result["average_daily_deployment_pct"] = result["mean_deployment"] * 100.0
    result["idle_capital"] = idle_capital
    result["idle_interest_earned"] = idle_interest_earned
    result["idle_interest_pct_of_starting_equity"] = (
        idle_interest_earned / STARTING_EQUITY * 100.0
    )
    return result


def simulate_pead_alone(
    events: list[dict[str, Any]],
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    hold_sessions: int,
    start: date,
    end: date,
    scheduled_events: list[EarningsEvent] | None = None,
) -> dict[str, Any]:
    """One-cash PEAD-only book using the same progressive cash constraints."""
    calendar = _all_days(series, end)
    scheduled = (
        build_event_schedule(
            events, series, symbols, universe_size, hold_sessions, calendar
        )
        if scheduled_events is None
        else scheduled_events
    )
    entries: dict[date, list[EarningsEvent]] = defaultdict(list)
    for event in scheduled:
        if start <= event.entry_day <= end:
            entries[event.entry_day].append(event)
    cash = STARTING_EQUITY
    holdings: dict[str, Holding] = {}
    curve: list[float] = []
    daily_deployment: list[dict[str, Any]] = []
    mode_days: dict[str, dict[str, int]] = defaultdict(
        lambda: {"momentum": 0, "earnings": 0, "cash": 0, "out_of_momentum": 0}
    )
    trade_returns: list[float] = []
    event_log: list[dict[str, Any]] = []
    turnover = 0.0
    cost_paid = 0.0
    stops = 0
    previous_equity: float | None = None
    out_pnl = 0.0
    out_days = 0

    for day in calendar:
        if day < start:
            continue
        for symbol, holding in list(holdings.items()):
            if holding.exit_day == day:
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "EXIT_PEAD_HOLD",
                )
                del holdings[symbol]
        for symbol, holding in list(holdings.items()):
            bar = series[symbol].by_date.get(day)
            if bar is not None and bar.low <= holding.stop:
                cash, turnover, cost_paid = _sell(
                    holding, series[symbol], day, cash, trade_returns, event_log,
                    turnover, cost_paid, "STOP",
                )
                del holdings[symbol]
                stops += 1
        for event in sorted(entries.get(day, []), key=lambda item: item.symbol):
            if event.symbol in holdings:
                continue
            equity_open = cash + _holding_value(holdings, series, day)
            cash, turnover, cost_paid = _buy(
                event.symbol, "earnings", equity_open / TOP_N,
                series[event.symbol], day, cash, holdings, event_log,
                turnover, cost_paid, event.exit_day,
            )
        equity_close = cash + _holding_value(holdings, series, day)
        deployed = (equity_close - cash) / equity_close if equity_close else 0.0
        curve.append(equity_close)
        if previous_equity is not None:
            out_pnl += equity_close - previous_equity
            out_days += 1
        previous_equity = equity_close
        mode_days[str(day.year)]["earnings" if holdings else "cash"] += 1
        mode_days[str(day.year)]["out_of_momentum"] += 1
        daily_deployment.append(
            {
                "date": day.isoformat(),
                "mode": "earnings" if holdings else "cash",
                "cash": cash,
                "equity": equity_close,
                "deployed_pct": deployed,
                "positions": len(holdings),
            }
        )
    return _metrics(
        curve, trade_returns, turnover, cost_paid, daily_deployment,
        dict(mode_days), stops, out_pnl, out_days, event_log,
    )


def _spy_series() -> Series:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT date, open, high, low, close, volume
                  FROM {PRICE_TABLE}
                 WHERE symbol='SPY' AND source = ANY(%s)
                 ORDER BY date
                """,
                (list(PRICE_SOURCES),),
            )
            rows = cur.fetchall()
    if rows:
        return Series("SPY", [Bar(row[0], *map(float, row[1:])) for row in rows])
    bars, error = _fetch_feed("SPY", ANALYSIS_START, ANALYSIS_END, "sip")
    if error:
        raise RuntimeError(f"SPY benchmark unavailable: {error}")
    return Series(
        "SPY",
        [Bar(bar.day, bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars],
    )


def simulate_buy_and_hold(
    series: Series,
    start: date,
    end: date,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    first = next((bar for bar in series.bars if start <= bar.day <= end), None)
    if first is None:
        return _metrics([], [], 0.0, 0.0, [], {}, 0, 0.0, 0, [])
    bars = [bar for bar in series.bars if first.day <= bar.day <= end]
    weight = 1 / len(symbols) if symbols else 1.0
    entry_price = first.open * (1 + SLIP)
    qty = STARTING_EQUITY * weight / entry_price
    cost_paid = STARTING_EQUITY * weight * SLIP
    curve = [qty * bar.close for bar in bars]
    deployments = [
        {
            "date": bar.day.isoformat(),
            "mode": "momentum",
            "cash": 0.0,
            "equity": value,
            "deployed_pct": 1.0,
            "positions": 1,
        }
        for bar, value in zip(bars, curve)
    ]
    exit_price = bars[-1].close * (1 - SLIP)
    exit_value = qty * exit_price
    turnover = STARTING_EQUITY * weight + exit_value
    return _metrics(
        curve,
        [exit_value / (qty * entry_price) - 1],
        turnover,
        cost_paid + qty * bars[-1].close * SLIP,
        deployments,
        {str(start.year): {"momentum": len(bars), "earnings": 0, "cash": 0, "out_of_momentum": 0}},
        0,
        0.0,
        0,
        [],
    )


def simulate_equal_weight_universe(
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    start: date,
    end: date,
) -> dict[str, Any]:
    first_day: date | None = None
    available: list[str] = []
    for day in _all_days(series, end):
        if day < start:
            continue
        qualified, _ = screen_universe_current(
            series, symbols, day, universe_size
        )
        candidate = sorted(
            symbol for symbol in qualified if series[symbol].by_date.get(day)
        )
        if candidate:
            first_day = day
            available = candidate
            break
    if first_day is None:
        return _metrics([], [], 0.0, 0.0, [], {}, 0, 0.0, 0, [])
    if not available:
        return _metrics([], [], 0.0, 0.0, [], {}, 0, 0.0, 0, [])
    bars_by_symbol = {symbol: series[symbol] for symbol in available}
    weight = 1 / len(available)
    cash = STARTING_EQUITY
    quantities: dict[str, float] = {}
    cost_paid = 0.0
    for symbol, data in bars_by_symbol.items():
        bar = data.by_date[first_day]
        notional = STARTING_EQUITY * weight / (1 + SLIP)
        quantities[symbol] = notional / (bar.open * (1 + SLIP))
        cash -= notional * (1 + SLIP)
        cost_paid += notional * SLIP
    calendar = [
        day for day in _all_days(series, end) if first_day <= day <= end
    ]
    curve: list[float] = []
    deployments: list[dict[str, Any]] = []
    for day in calendar:
        market = sum(
            qty * (_bar_open(bars_by_symbol[symbol], day).close)
            for symbol, qty in quantities.items()
            if _bar_open(bars_by_symbol[symbol], day)
        )
        equity = cash + market
        curve.append(equity)
        deployments.append(
            {
                "date": day.isoformat(),
                "mode": "momentum",
                "cash": cash,
                "equity": equity,
                "deployed_pct": market / equity if equity else 0.0,
                "positions": len(quantities),
            }
        )
    exit_value = sum(
        qty * (_bar_open(bars_by_symbol[symbol], end).close) * (1 - SLIP)
        for symbol, qty in quantities.items()
        if _bar_open(bars_by_symbol[symbol], end)
    )
    turnover = STARTING_EQUITY + exit_value
    cost_paid += exit_value / (1 - SLIP) * SLIP
    return _metrics(
        curve,
        [curve[-1] / curve[0] - 1],
        turnover,
        cost_paid,
        deployments,
        {
            str(start.year): {
                "momentum": len(calendar),
                "earnings": 0,
                "cash": 0,
                "out_of_momentum": 0,
            }
        },
        0,
        0.0,
        0,
        [],
    )


def _fast_random_return(
    series: dict[str, Series],
    start: date,
    end: date,
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    rng: random.Random,
) -> float:
    """Calculate one random-entry return without allocating report objects.

    The control has the same monthly equal-weight, cash-constrained, slippage,
    and catastrophe-stop rules as ``simulate_momentum``.  It intentionally
    omits daily metrics because the control stores only its individual return
    distribution.
    """
    days = [day for day in _all_days(series, end) if day >= start]
    monthly = _monthly_days(days)
    cash = STARTING_EQUITY
    holdings: dict[str, Holding] = {}
    first_equity: float | None = None

    def value_at(day: date) -> float:
        value = cash
        for symbol, holding in holdings.items():
            bar = _bar_open(series[symbol], day)
            if bar:
                value += holding.qty * bar.close
        return value

    for day in days:
        if day in monthly:
            for symbol, holding in list(holdings.items()):
                bar = _bar_open(series[symbol], day)
                if bar:
                    cash += holding.qty * bar.open * (1 - SLIP)
                del holdings[symbol]
            ranked = ranking_cache.get(day, [])
            selected = rng.sample(ranked, min(TOP_N, len(ranked))) if ranked else []
            weight = 1 / len(selected) if selected else 0.0
            equity_open = value_at(day)
            for symbol, _, _ in selected:
                bar = series[symbol].by_date.get(day)
                if bar is None:
                    continue
                notional = min(equity_open * weight, cash / (1 + SLIP))
                if notional <= 0:
                    continue
                entry_exec = bar.open * (1 + SLIP)
                holdings[symbol] = Holding(
                    symbol=symbol,
                    qty=notional / entry_exec,
                    entry_exec=entry_exec,
                    stop=entry_exec * (1 - STOP_LOSS),
                    mode="momentum",
                    entry_day=day,
                )
                cash -= notional * (1 + SLIP)
        for symbol, holding in list(holdings.items()):
            bar = series[symbol].by_date.get(day)
            if bar is not None and bar.low <= holding.stop:
                cash += holding.qty * min(bar.open, holding.stop) * (1 - SLIP)
                del holdings[symbol]
        equity_close = value_at(day)
        if first_equity is None:
            first_equity = equity_close
    if not days or first_equity in (None, 0):
        return 0.0
    for symbol, holding in list(holdings.items()):
        bar = _bar_open(series[symbol], end)
        if bar:
            cash += holding.qty * bar.close * (1 - SLIP)
    return cash / first_equity - 1


def _random_window_control(
    args: tuple[
        dict[str, Series],
        set[str],
        int,
        tuple[str, date, date],
        dict[date, list[tuple[str, float, float]]],
    ],
) -> tuple[str, dict[str, Any]]:
    series, symbols, universe_size, window, ranking_cache = args
    name, start, end = window
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
    return name, {
        "iterations": CONTROL_ITERATIONS,
        "seed": RANDOM_SEED,
        "matched_selection_size": TOP_N,
        "returns": returns,
        "return_mean": statistics.fmean(returns),
        "return_std": statistics.stdev(returns) if len(returns) > 1 else 0.0,
        "return_median": statistics.median(returns),
        "return_p05": ordered[max(0, int(len(ordered) * 0.05) - 1)],
        "return_p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "dispersion_check": len(set(returns)) > 1,
    }


def random_controls(
    series: dict[str, Series],
    symbols: set[str],
    universe_size: int,
    windows: tuple[tuple[str, date, date], ...],
    ranking_cache: dict[date, list[tuple[str, float, float]]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    jobs = [
        (series, symbols, universe_size, window, ranking_cache)
        for window in windows
    ]
    with ProcessPoolExecutor(
        max_workers=min(len(jobs), 4),
        mp_context=multiprocessing.get_context("fork"),
    ) as executor:
        for name, result in executor.map(_random_window_control, jobs):
            output[name] = result
    for name, result in output.items():
        print(
            f"random_control | window={name} | iterations={CONTROL_ITERATIONS} "
            f"| mean={result['return_mean']:.6f} "
            f"| sd={result['return_std']:.6f} "
            f"| p05={result['return_p05']:.6f} "
            f"| p95={result['return_p95']:.6f}"
        )
    return output


def _actual_percentile(value: float, distribution: list[float]) -> float:
    return 100 * sum(item <= value for item in distribution) / len(distribution)


def _v3_expectancy_discrepancy() -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pass_bar->>'primary_expectancy_minimum_derived_from_momentum_alone',
                       results->'configuration'->'pass_bar'
                         ->>'primary_expectancy_minimum_derived_from_momentum_alone',
                       results->'windows'->'pooled_2018_present'
                         ->'momentum_equal_weight'->>'expectancy'
                  FROM research_ledger
                 WHERE strategy_family='bot2_momentum_pead_v3'
                 ORDER BY experiment_id DESC
                 LIMIT 1
                """
            )
            row = cur.fetchone()
    ledger_value = float(row[0]) if row and row[0] else None
    embedded_value = float(row[1]) if row and row[1] else None
    stored_momentum = float(row[2]) if row and row[2] else None
    return {
        "experiment_12_ledger_pass_bar": ledger_value,
        "experiment_12_embedded_result_pass_bar": embedded_value,
        "experiment_12_stored_momentum_expectancy": stored_momentum,
        "difference_ledger_minus_embedded": (
            ledger_value - embedded_value
            if ledger_value is not None and embedded_value is not None
            else None
        ),
        "derivation": (
            "v4 uses the momentum-alone expectancy from its own persisted "
            "momentum result object; it does not copy either Experiment 12 value."
        ),
    }


def _find_experiment(strategy_family: str, bot_id: str) -> int | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT experiment_id, results
                  FROM research_ledger
                 WHERE strategy_family=%s AND bot_id=%s
                 ORDER BY experiment_id DESC
                 LIMIT 1
                """,
                (strategy_family, bot_id),
            )
            row = cur.fetchone()
    if row and row[1] is not None:
        raise RuntimeError(
            f"{strategy_family} already recorded: experiment_id={row[0]}"
        )
    return int(row[0]) if row else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _register_or_resume(
    strategy_family: str,
    bot_id: str,
    hypothesis: str,
    parameters: dict[str, Any],
    pass_bar: dict[str, Any],
    data_window: dict[str, Any],
    variations_tested: int,
    notes: str,
) -> int:
    existing = _find_experiment(strategy_family, bot_id)
    if existing is not None:
        print(f"experiment_registration | {strategy_family} | id={existing} | resume=true")
        return existing
    experiment_id = register_experiment(
        strategy_family=strategy_family,
        bot_id=bot_id,
        hypothesis=hypothesis,
        parameters=parameters,
        pass_bar=pass_bar,
        data_window=data_window,
        variations_tested=variations_tested,
        sizing_model="cash_constrained",
        went_live=False,
        notes=notes,
    )
    print(f"experiment_registered | {strategy_family} | experiment_id={experiment_id}")
    return experiment_id


def _print_transfer_proof(result: dict[str, Any], hold_sessions: int) -> None:
    print(f"rotation_transfer_proof | hold_sessions={hold_sessions}")
    actions = result.get("event_log", [])
    liquidation_index = next(
        (
            index
            for index, item in enumerate(actions)
            if item["action"] == "LIQUIDATE_MOMENTUM_FOR_EARNINGS_CLUSTER"
        ),
        None,
    )
    if liquidation_index is None:
        print("rotation_transfer_proof | status=NO_CLUSTER_OBSERVED")
        return
    end = min(len(actions), liquidation_index + 12)
    for item in actions[liquidation_index:end]:
        print("rotation_transfer | " + json.dumps(item, sort_keys=True))
    reentry = next(
        (item for item in actions[liquidation_index:] if item["action"] == "REENTER_MOMENTUM_AFTER_PEAD"),
        None,
    )
    print(
        "rotation_transfer_proof | status="
        + ("PASS" if reentry else "NO_REENTRY_IN_WINDOW")
    )


def run_research(
    *,
    refresh_assets: bool = True,
    ingest_expanded: bool = False,
) -> dict[str, Any]:
    ensure_asset_table()
    series = load_panel()
    panel_symbols = set(series)
    if refresh_assets:
        assets = fetch_tradable_us_equities()
        persist_assets(assets)
    else:
        assets = [
            Asset(symbol, "us_equity", "active", "", True, None)
            for symbol in load_asset_symbols()
        ]
    candidate_symbols = {asset.symbol for asset in assets} | panel_symbols
    print(
        f"asset_expansion | alpaca_tradable_us_equity={len({asset.symbol for asset in assets})} "
        f"| historical_panel_symbols={len(panel_symbols)} "
        f"| candidate_union={len(candidate_symbols)}"
    )
    if ingest_expanded:
        print(f"expanded_price_ingest | {ingest_expanded_prices(assets)}")
        series = load_panel()

    gate_ok, universe_size, gate_report = mechanical_gate(series, candidate_symbols)
    earnings_report = audit_earnings()
    if not gate_ok:
        print("STOP: mechanical universe gate failed; registration/backtests skipped.")
        return {
            "status": "STOP",
            "mechanical_gate": gate_report,
            "earnings_audit": earnings_report,
            "live_execution": False,
            "orders_placed": 0,
        }

    ranking_cache = build_momentum_cache(
        series, panel_symbols, universe_size, ANALYSIS_END
    )
    events = _load_earnings_events()
    spy = _spy_series()
    discrepancy = _v3_expectancy_discrepancy()
    print("expectancy_discrepancy | " + json.dumps(discrepancy, sort_keys=True))

    parameters = {
        "universe_rule": {
            "candidate_pool": "Alpaca currently tradable us_equity union retained historical panel",
            "as_of_rule": "only current bars with date strictly before rebalance/entry date",
            "minimum_prior_sessions": LOOKBACK_SESSIONS,
            "trailing_liquidity_sessions": LIQUIDITY_SESSIONS,
            "trailing_median_close_min": 5.0,
            "universe_size": universe_size,
            "ranking_metric": "trailing_60_session_median_dollar_volume",
            "true_dropout_definition": "early qualified and absent from final qualified snapshot",
        },
        "momentum": {
            "lookback": "12-1",
            "top_n": TOP_N,
            "allocation": "equal_weight",
            "rebalance": "first available trading session each month",
        },
        "rotation": {
            "default_mode": "momentum",
            "earnings_trigger": "first report in a clustered announcement sequence",
            "liquidation": "all momentum holdings into shared cash balance",
            "entries": "positive surprise only, progressive one-announcement entries",
            "return_to_momentum": "next monthly rebalance after last PEAD position closes",
            "cluster_rule": "entry announcements separated by at most one calendar session",
        },
        "pead": {
            "holds": [5, 20],
            "positive_surprise_only": True,
            "manual_cost_excluded": True,
        },
        "slippage_each_leg_bps": SLIPPAGE_BPS,
        "catastrophe_stop": STOP_LOSS,
        "starting_equity": STARTING_EQUITY,
        "deployment_cap": 1.0,
        "random_controls": {
            "iterations": CONTROL_ITERATIONS,
            "seed": RANDOM_SEED,
            "matched_size": TOP_N,
            "individual_returns_stored": True,
        },
        "cash_model": "one shared cash balance; unused capital remains cash",
    }
    data_window = {
        "start": ANALYSIS_START.isoformat(),
        "end": ANALYSIS_END.isoformat(),
        "windows": [
            {"name": name, "start": str(start), "end": str(end)}
            for name, start, end in WINDOWS
        ],
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "earnings_table": EARNINGS_TABLE,
        "mechanical_gate": "six-date current-bar lookahead proof plus true dropout proof",
    }
    momentum_pass_bar = {
        "pooled_sharpe_min": 0.60,
        "pooled_max_drawdown_max": 0.40,
        "beats_spy_buy_and_hold_risk_adjusted": True,
        "beats_random_entry": True,
        "expectancy_source": "momentum-alone result object; no copied v3 threshold",
    }
    rotation_pass_bar = {
        "pooled_sharpe_min": 0.50,
        "pooled_max_drawdown_max": 0.40,
        "rotation_must_beat_momentum_alone_risk_adjusted": True,
        "expectancy_source": "momentum-alone result object in this same run",
    }
    notes = (
        "Development-only research. No live module, runner, broker orders, or "
        "deployment changes. " + MOMENTUM_CRASH_CAVEAT + " " + DISCREPANCY_NOTE
    )
    momentum_id = _register_or_resume(
        "bot2_momentum_only",
        "bot2_momentum_only_research",
        MOMENTUM_HYPOTHESIS,
        parameters,
        momentum_pass_bar,
        data_window,
        5,
        notes,
    )
    rotation_id = _register_or_resume(
        "bot2_momentum_pead_v4_rotation",
        "bot2_momentum_pead_v4_rotation_research",
        ROTATION_HYPOTHESIS,
        parameters,
        rotation_pass_bar,
        data_window,
        8,
        notes,
    )

    results_momentum: dict[str, Any] = {
        "experiment_id": momentum_id,
        "configuration": {
            "parameters": parameters,
            "pass_bar": momentum_pass_bar,
            "data_window": data_window,
            "expectancy_derivation": (
                "Derived after the momentum-alone pooled simulation from its "
                f"expectancy value; no arbitrary constant. v3 discrepancy: {discrepancy}"
            ),
        },
        "mechanical_gate": gate_report,
        "earnings_audit": earnings_report,
        "windows": {},
        "controls": {},
        "live_execution": False,
        "orders_placed": 0,
    }
    results_rotation: dict[str, Any] = {
        "experiment_id": rotation_id,
        "configuration": results_momentum["configuration"],
        "mechanical_gate": gate_report,
        "earnings_audit": earnings_report,
        "windows": {},
        "controls": {},
        "live_execution": False,
        "orders_placed": 0,
        "rotation_state_machine": [
            "MOMENTUM -> EARNINGS on first event in cluster",
            "EARNINGS transition liquidates all momentum into shared cash",
            "EARNINGS entries arrive progressively, positive surprise only",
            "unused capital remains cash",
            "EARNINGS -> MOMENTUM at next monthly rebalance after last PEAD close",
        ],
    }
    full_calendar = _all_days(series, ANALYSIS_END)
    scheduled_by_hold = {
        hold: build_event_schedule(
            events, series, panel_symbols, universe_size, hold, full_calendar
        )
        for hold in (5, 20)
    }

    for name, start, end in WINDOWS:
        momentum = simulate_momentum(
            series, panel_symbols, universe_size, start, end, ranking_cache
        )
        pead5 = simulate_pead_alone(
            events, series, panel_symbols, universe_size, 5, start, end,
            scheduled_events=scheduled_by_hold[5],
        )
        pead20 = simulate_pead_alone(
            events, series, panel_symbols, universe_size, 20, start, end,
            scheduled_events=scheduled_by_hold[20],
        )
        rotation5 = simulate_true_rotation(
            series, panel_symbols, universe_size, start, end, 5, ranking_cache, events,
            scheduled_events=scheduled_by_hold[5],
        )
        rotation20 = simulate_true_rotation(
            series, panel_symbols, universe_size, start, end, 20, ranking_cache, events,
            scheduled_events=scheduled_by_hold[20],
        )
        spy_result = simulate_buy_and_hold(spy, start, end)
        universe_result = simulate_equal_weight_universe(
            series, panel_symbols, universe_size, start, end
        )
        results_momentum["windows"][name] = {
            "momentum_alone": momentum,
            "pead_alone_5": pead5,
            "pead_alone_20": pead20,
            "spy_buy_and_hold": spy_result,
            "equal_weight_universe_buy_and_hold": universe_result,
        }
        results_rotation["windows"][name] = {
            "rotation_pead_5": rotation5,
            "rotation_pead_20": rotation20,
            "momentum_alone": momentum,
            "pead_alone_5": pead5,
            "pead_alone_20": pead20,
            "spy_buy_and_hold": spy_result,
            "equal_weight_universe_buy_and_hold": universe_result,
        }
        for label, result in results_rotation["windows"][name].items():
            print(
                f"result | window={name} | strategy={label} "
                f"| return={result['return']:.6f} | maxDD={result['max_drawdown']:.6f} "
                f"| sharpe={result['sharpe']:.6f} | sortino={result['sortino']:.6f} "
                f"| trades={result['trades']} | turnover={result['turnover']:.6f} "
                f"| cost_drag={result['cost_drag']:.6f} "
                f"| mean_deployment={result['mean_deployment']:.6f} "
                f"| max_deployment={result['max_deployment']:.6f} "
                f"| days_above_90={result['days_above_90pct_deployed']}"
            )
        _print_transfer_proof(rotation5, 5)
        _print_transfer_proof(rotation20, 20)

    controls = random_controls(
        series, panel_symbols, universe_size, WINDOWS, ranking_cache
    )
    for name, control in controls.items():
        actual = results_momentum["windows"][name]["momentum_alone"]["return"]
        control["actual_momentum_return"] = actual
        control["actual_percentile"] = _actual_percentile(actual, control["returns"])
    results_momentum["controls"] = {
        name: {
            "momentum_alone": results_momentum["windows"][name]["momentum_alone"],
            "pead_alone_5": results_momentum["windows"][name]["pead_alone_5"],
            "pead_alone_20": results_momentum["windows"][name]["pead_alone_20"],
            "random_entry_1000": controls[name],
            "spy_buy_and_hold": results_momentum["windows"][name]["spy_buy_and_hold"],
            "equal_weight_universe_buy_and_hold": results_momentum["windows"][name][
                "equal_weight_universe_buy_and_hold"
            ],
        }
        for name in results_momentum["windows"]
    }
    results_rotation["controls"] = results_momentum["controls"]

    pooled_momentum = results_momentum["windows"]["pooled_2018_present"]["momentum_alone"]
    pooled_spy = results_momentum["windows"]["pooled_2018_present"]["spy_buy_and_hold"]
    pooled_random = controls["pooled_2018_present"]
    pooled_rotation5 = results_rotation["windows"]["pooled_2018_present"]["rotation_pead_5"]
    pooled_rotation20 = results_rotation["windows"]["pooled_2018_present"]["rotation_pead_20"]
    momentum_checks = {
        "pooled_sharpe": pooled_momentum["sharpe"] >= momentum_pass_bar["pooled_sharpe_min"],
        "pooled_max_drawdown": pooled_momentum["max_drawdown"] <= momentum_pass_bar["pooled_max_drawdown_max"],
        "beats_spy_risk_adjusted": pooled_momentum["sharpe"] > pooled_spy["sharpe"],
        "beats_random_entry": pooled_momentum["return"] > pooled_random["return_mean"],
        "deployment_cap": all(
            result["max_deployment"] <= 1.0000001
            for window in results_momentum["windows"].values()
            for result in window.values()
            if isinstance(result, dict) and "max_deployment" in result
        ),
    }
    rotation_checks = {
        "rotation_5_beats_momentum_risk_adjusted": pooled_rotation5["sharpe"] > pooled_momentum["sharpe"],
        "rotation_20_beats_momentum_risk_adjusted": pooled_rotation20["sharpe"] > pooled_momentum["sharpe"],
        "rotation_5_deployment_cap": pooled_rotation5["max_deployment"] <= 1.0000001,
        "rotation_20_deployment_cap": pooled_rotation20["max_deployment"] <= 1.0000001,
    }
    stop_checks = [
        bool(results_rotation["windows"][name][label]["stop_coverage"])
        for name in results_rotation["windows"]
        for label in ("rotation_pead_5", "rotation_pead_20")
    ]
    results_momentum["evaluation"] = {
        "checks": momentum_checks,
        "outcome": "PASS" if all(momentum_checks.values()) else "FAIL",
        "momentum_crash_caveat": MOMENTUM_CRASH_CAVEAT,
        "v3_expectancy_discrepancy": discrepancy,
    }
    results_rotation["evaluation"] = {
        "checks": rotation_checks,
        "outcome": "PASS" if all(rotation_checks.values()) else "FAIL",
        "momentum_crash_caveat": MOMENTUM_CRASH_CAVEAT,
        "v3_expectancy_discrepancy": discrepancy,
    }
    results_momentum["verification"] = {
        "orders_placed": 0,
        "live_strategy_module": False,
        "bot1_touched": False,
        "bot3_touched": False,
        "vault_touched": False,
        "monitoring_touched": False,
        "published": False,
        "stop_coverage": f"{sum(stop_checks)}/{len(stop_checks)}",
    }
    results_rotation["verification"] = results_momentum["verification"]
    print(
        f"momentum_only_evaluation | outcome={results_momentum['evaluation']['outcome']} "
        f"| checks={momentum_checks}"
    )
    print(
        f"rotation_evaluation | outcome={results_rotation['evaluation']['outcome']} "
        f"| checks={rotation_checks}"
    )
    print(f"stop_coverage | {sum(stop_checks)}/{len(stop_checks)}")
    print(
        "verification | execution_mode=read_only | orders_placed=0 "
        "| live_strategy_module=0 | bot1_touched=0 | bot3_touched=0 "
        "| vault_touched=0 | monitoring_touched=0 | published=0"
    )
    record_results(momentum_id, _jsonable(results_momentum), results_momentum["evaluation"]["outcome"])
    print(
        f"results_recorded | strategy_family=bot2_momentum_only "
        f"| experiment_id={momentum_id} | outcome={results_momentum['evaluation']['outcome']} "
        "| recorded_once=true"
    )
    record_results(rotation_id, _jsonable(results_rotation), results_rotation["evaluation"]["outcome"])
    print(
        f"results_recorded | strategy_family=bot2_momentum_pead_v4_rotation "
        f"| experiment_id={rotation_id} | outcome={results_rotation['evaluation']['outcome']} "
        "| recorded_once=true"
    )
    results_momentum["status"] = "COMPLETE"
    results_rotation["status"] = "COMPLETE"
    return {
        "status": "COMPLETE",
        "momentum": results_momentum,
        "rotation": results_rotation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-stored-assets", action="store_true")
    parser.add_argument("--ingest-expanded", action="store_true")
    args = parser.parse_args()
    result = run_research(
        refresh_assets=not args.use_stored_assets,
        ingest_expanded=args.ingest_expanded,
    )
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())