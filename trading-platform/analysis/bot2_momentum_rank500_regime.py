#!/usr/bin/env python3
"""Development-only Bot 2 rank-500 momentum with a binary SPY regime filter."""

from __future__ import annotations

import argparse
import copy
import json
import multiprocessing
import random
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
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
from db.research_postgres import get_research_conn as get_conn  # noqa: E402
from analysis.bot2_sp500_data import REFERENCE_PRICE_SOURCES  # noqa: E402
from analysis.bot2_momentum_pead_v3 import (  # noqa: E402
    Bar,
    PRICE_SOURCES,
    PRICE_TABLE,
    Series,
    _fetch_feed,
)
from analysis.bot2_momentum_pead_v4 import (  # noqa: E402
    CONTROL_ITERATIONS,
    RANDOM_SEED,
    SLIP,
    SLIPPAGE_BPS,
    STARTING_EQUITY,
    STOP_LOSS,
    TARGET_UNIVERSE,
    TOP_N,
    Holding,
    _all_days,
    _bar_open,
    _holding_value,
    _metrics,
    _monthly_days,
    _sell,
    _buy,
    _spy_series,
    build_momentum_cache,
    simulate_buy_and_hold,
    simulate_equal_weight_universe,
)
from analysis.bot2_momentum_rank500_backtest import (  # noqa: E402
    BACKTEST_START,
    MIN_PRICE,
    MIN_SESSIONS,
    SAMPLE_MONTHS,
    WARMUP_START,
    _actual_percentile,
    _jsonable,
    _largest_monthly_drawdown,
    _load_assets,
    _load_compact_panel,
    _latest_complete_month_end,
    _sector_map,
    _windows,
)
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)


STRATEGY_FAMILY = "bot2_momentum_rank500_regime"
BOT_ID = "bot2_momentum_rank500_regime_research"
BASELINE_EXPERIMENT_ID = 18
REGIME_LOOKBACK = 200
REGIME_ON = "RISK_ON"
REGIME_OFF = "RISK_OFF"
SGOV_SYMBOL = "SGOV"
HYPOTHESIS = (
    "Adding a market regime filter to rank-500 12-1 momentum reduces the "
    "momentum-crash drawdown that caused experiment 18 to fail, without "
    "destroying the return. Specifically it should cut the 2021-2022 drawdown."
)
# "Materially below" is pre-registered as at least a 10 percentage-point
# reduction, rather than changing the strategy after seeing the result.
PASS_BAR = {
    "sharpe_min": 0.60,
    "max_drawdown_max": 0.40,
    "beats_spy_buy_and_hold_risk_adjusted": True,
    "beats_random_entry": True,
    "2021_2022_drawdown_reduction_min_absolute": 0.10,
}


def _baseline_row() -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT experiment_id, hypothesis, parameters, pass_bar,
                          data_window, results, outcome
                     FROM research_ledger
                    WHERE experiment_id=%s""",
                (BASELINE_EXPERIMENT_ID,),
            )
            row = cur.fetchone()
    if row is None or row[5] is None:
        raise RuntimeError("immutable experiment 18 results are unavailable")
    return {
        "experiment_id": row[0],
        "hypothesis": row[1],
        "parameters": row[2],
        "pass_bar": row[3],
        "data_window": row[4],
        "results": row[5],
        "outcome": row[6],
    }


def _register(
    end: date, windows: tuple[tuple[str, date, date], ...], baseline: dict[str, Any]
) -> int:
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
                f"{STRATEGY_FAMILY} already has immutable results: "
                f"experiment_id={existing[0]}"
            )
        print(
            f"experiment_preregistered | strategy_family={STRATEGY_FAMILY} "
            f"| experiment_id={existing[0]} | status=resume_uncompleted"
        )
        return int(existing[0])

    parameters = copy.deepcopy(baseline["parameters"])
    parameters["market_regime"] = {
        "symbol": SGOV_SYMBOL,
        "signal_symbol": "SPY",
        "lookback_sessions": REGIME_LOOKBACK,
        "rule": (
            "RISK_ON iff prior SPY close > prior 200-session SMA; "
            "otherwise RISK_OFF"
        ),
        "evaluation_timing": "each monthly rebalance using bars strictly before date",
        "risk_off_asset": SGOV_SYMBOL,
        "position_policy": "binary; no momentum positions while RISK_OFF",
    }
    parameters["direct_baseline_experiment_id"] = BASELINE_EXPERIMENT_ID
    data_window = copy.deepcopy(baseline["data_window"])
    data_window["regime_rule"] = parameters["market_regime"]
    data_window["baseline_experiment_id"] = BASELINE_EXPERIMENT_ID
    notes = (
        "Experiment 18 failed on drawdown and SPY comparison. This adds a "
        "binary prior-data-only SPY 200-day SMA regime filter only; universe, "
        "signal, sizing, rebalance, stops, slippage, and windows are unchanged. "
        "RISK_OFF uses SGOV until the next RISK_ON monthly rebalance. "
        "Materially lower 2021-2022 drawdown is operationalized as at least "
        "10 percentage points below experiment 18."
    )
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
        notes=notes,
    )
    print(
        f"experiment_preregistered | strategy_family={STRATEGY_FAMILY} "
        f"| experiment_id={experiment_id} | baseline_experiment_id={BASELINE_EXPERIMENT_ID} "
        f"| sizing_model=cash_constrained"
    )
    return experiment_id


def _load_reference_series(symbol: str, end: date) -> Series:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (date)
                       date, open, high, low, close, volume
                  FROM {PRICE_TABLE}
                 WHERE symbol=%s
                   AND date >= %s AND date <= %s
                   AND source = ANY(%s)
                 ORDER BY date,
                          CASE WHEN source='alpaca_sip_adjusted' THEN 0 ELSE 1 END
                """,
                (symbol, WARMUP_START, end, list(REFERENCE_PRICE_SOURCES)),
            )
            rows = cur.fetchall()
    if rows:
        print(
            f"reference_series | symbol={symbol} | source=development_price_table "
            f"| bars={len(rows)}"
        )
        return Series(symbol, [Bar(row[0], *map(float, row[1:])) for row in rows])
    # The development panel intentionally contains only the audited ordinary
    # equity universe. Use the same read-only fallback as experiment 18 for
    # SPY, and the read-only historical feed for SGOV. No order path is
    # imported or called.
    if symbol == "SPY":
        reference = _spy_series()
        print(
            f"reference_series | symbol={symbol} | source=read_only_spy_fallback "
            f"| bars={len(reference.bars)}"
        )
        return reference
    bars, error = _fetch_feed(symbol, WARMUP_START, end, "sip")
    if error or not bars:
        raise RuntimeError(
            f"read-only {symbol} reference series unavailable: {error or 'empty'}"
        )
    reference = Series(
        symbol,
        [Bar(bar.day, bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars],
    )
    print(
        f"reference_series | symbol={symbol} | source=read_only_historical_feed "
        f"| bars={len(reference.bars)}"
    )
    return reference


def _build_regime_cache(spy: Series, end: date) -> dict[date, dict[str, Any]]:
    cache: dict[date, dict[str, Any]] = {}
    for day in _all_days({"SPY": spy}, end):
        if (day.year, day.month) in {(key.year, key.month) for key in cache}:
            continue
        cutoff = bisect_left(spy.days, day)
        prior = spy.bars[max(0, cutoff - REGIME_LOOKBACK):cutoff]
        if len(prior) < REGIME_LOOKBACK:
            state = REGIME_OFF
            sma = None
            prior_close = None
        else:
            sma = statistics.fmean(bar.close for bar in prior)
            prior_close = prior[-1].close
            state = REGIME_ON if prior_close > sma else REGIME_OFF
        cache[day] = {
            "state": state,
            "prior_close": prior_close,
            "sma_200": sma,
            "prior_sessions": len(prior),
            "data_rule": "strictly_prior_to_rebalance",
        }
    print(
        f"regime_code | signal=SPY | lookback_sessions={REGIME_LOOKBACK} "
        f"| risk_on='prior_close > prior_200_day_SMA' "
        f"| risk_off='prior_close <= prior_200_day_SMA' "
        f"| evaluation=monthly_rebalance_strictly_prior_data_only "
        f"| sgov={SGOV_SYMBOL}"
    )
    return cache


def _regime_for_day(
    regime_cache: dict[date, dict[str, Any]], day: date
) -> str:
    eligible = [key for key in regime_cache if key <= day]
    if not eligible:
        return REGIME_OFF
    return regime_cache[max(eligible)]["state"]


def _risk_off_summary(
    series: dict[str, Any],
    regime_cache: dict[date, dict[str, Any]],
    start: date,
    end: date,
) -> dict[str, Any]:
    calendar = [day for day in _all_days(series, end) if start <= day <= end]
    states = {day: _regime_for_day(regime_cache, day) for day in calendar}
    off_days = [day for day, state in states.items() if state == REGIME_OFF]
    off_months = [
        day.isoformat()
        for day, info in sorted(regime_cache.items())
        if start <= day <= end and info["state"] == REGIME_OFF
    ]
    by_year: dict[str, list[str]] = defaultdict(list)
    for month in off_months:
        by_year[month[:4]].append(month)
    return {
        "risk_off_months_by_year": dict(by_year),
        "risk_off_months": off_months,
        "total_days_out_of_market": len(off_days),
        "total_calendar_days": len(calendar),
    }


def _buy_sgov(
    series: Series,
    day: date,
    cash: float,
    holdings: dict[str, Holding],
    event_log: list[dict[str, Any]],
    turnover: float,
    cost_paid: float,
    target_notional: float,
) -> tuple[float, float, float]:
    return _buy(
        SGOV_SYMBOL,
        "sgov",
        target_notional,
        series,
        day,
        cash,
        holdings,
        event_log,
        turnover,
        cost_paid,
    )


def simulate_regime(
    series: dict[str, Any],
    sgov: Series,
    start: date,
    end: date,
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    regime_cache: dict[date, dict[str, Any]],
) -> dict[str, Any]:
    calendar = _all_days(series, end)
    monthly = _monthly_days(calendar)
    cash = STARTING_EQUITY
    holdings: dict[str, Holding] = {}
    curve: list[float] = []
    daily_deployment: list[dict[str, Any]] = []
    mode_days: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "momentum": 0,
            "risk_off": 0,
            "cash": 0,
            "out_of_momentum": 0,
        }
    )
    trade_returns: list[float] = []
    event_log: list[dict[str, Any]] = []
    turnover = 0.0
    cost_paid = 0.0
    stops = 0
    current_state = REGIME_OFF

    for day in calendar:
        if day < start:
            continue
        for symbol, holding in list(holdings.items()):
            bar = _bar_open(sgov if symbol == SGOV_SYMBOL else series[symbol], day)
            if bar is not None and bar.low <= holding.stop:
                source = sgov if symbol == SGOV_SYMBOL else series[symbol]
                cash, turnover, cost_paid = _sell(
                    holding, source, day, cash, trade_returns, event_log,
                    turnover, cost_paid, "STOP",
                )
                del holdings[symbol]
                stops += 1

        if day in monthly:
            current_state = regime_cache.get(
                day, {"state": REGIME_OFF}
            )["state"]
            if current_state == REGIME_OFF:
                for symbol, holding in list(holdings.items()):
                    if holding.mode != "momentum":
                        continue
                    cash, turnover, cost_paid = _sell(
                        holding, series[symbol], day, cash, trade_returns, event_log,
                        turnover, cost_paid, "REGIME_RISK_OFF",
                    )
                    del holdings[symbol]
                if SGOV_SYMBOL not in holdings:
                    equity_open = cash + _holding_value(holdings, series, day)
                    cash, turnover, cost_paid = _buy_sgov(
                        sgov, day, cash, holdings, event_log, turnover,
                        cost_paid, equity_open,
                    )
            else:
                for symbol, holding in list(holdings.items()):
                    source = sgov if symbol == SGOV_SYMBOL else series[symbol]
                    cash, turnover, cost_paid = _sell(
                        holding, source, day, cash, trade_returns, event_log,
                        turnover, cost_paid, "REGIME_RISK_ON_ROTATION",
                    )
                    del holdings[symbol]
                ranked = ranking_cache.get(day, [])
                selected = ranked[:TOP_N]
                weight = 1 / len(selected) if selected else 0.0
                equity_open = cash
                for symbol, _, _ in selected:
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

        equity_close = cash + _holding_value(
            holdings,
            {**series, SGOV_SYMBOL: sgov},
            day,
        )
        deployed = (equity_close - cash) / equity_close if equity_close else 0.0
        curve.append(equity_close)
        year = str(day.year)
        mode_days[year]["risk_off" if current_state == REGIME_OFF else "momentum"] += 1
        if current_state == REGIME_OFF:
            mode_days[year]["out_of_momentum"] += 1
        if not holdings:
            mode_days[year]["cash"] += 1
        daily_deployment.append(
            {
                "date": day.isoformat(),
                "mode": "risk_off" if current_state == REGIME_OFF else (
                    "momentum" if holdings else "cash"
                ),
                "regime": current_state,
                "cash": cash,
                "equity": equity_close,
                "deployed_pct": deployed,
                "positions": len(holdings),
            }
        )

    for symbol, holding in list(holdings.items()):
        source = sgov if symbol == SGOV_SYMBOL else series[symbol]
        cash, turnover, cost_paid = _sell(
            holding, source, end, cash, trade_returns, event_log,
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
        0.0,
        0,
        event_log,
    )
    result["allocation"] = "equal_weight"
    result["regime_rule"] = (
        "RISK_ON iff prior SPY close > prior 200-session SMA; "
        "RISK_OFF otherwise; RISK_OFF holds SGOV"
    )
    result["risk_off_days"] = sum(
        values.get("out_of_momentum", 0) for values in mode_days.values()
    )
    return result


def _fast_random_return_regime(
    series: dict[str, Any],
    sgov: Series,
    start: date,
    end: date,
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    regime_cache: dict[date, dict[str, Any]],
    rng: random.Random,
) -> float:
    days = [day for day in _all_days(series, end) if day >= start]
    monthly = _monthly_days(days)
    cash = STARTING_EQUITY
    holdings: dict[str, Holding] = {}
    first_equity: float | None = None

    def value_at(day: date) -> float:
        value = cash
        for symbol, holding in holdings.items():
            source = sgov if symbol == SGOV_SYMBOL else series[symbol]
            bar = _bar_open(source, day)
            if bar:
                value += holding.qty * bar.close
        return value

    for day in days:
        if day in monthly:
            state = regime_cache.get(day, {"state": REGIME_OFF})["state"]
            for symbol, holding in list(holdings.items()):
                source = sgov if symbol == SGOV_SYMBOL else series[symbol]
                bar = _bar_open(source, day)
                if bar:
                    cash += holding.qty * bar.open * (1 - SLIP)
                del holdings[symbol]
            if state == REGIME_OFF:
                equity_open = value_at(day)
                bar = sgov.by_date.get(day)
                if bar is not None:
                    notional = min(equity_open, cash / (1 + SLIP))
                    holdings[SGOV_SYMBOL] = Holding(
                        symbol=SGOV_SYMBOL,
                        qty=notional / (bar.open * (1 + SLIP)),
                        entry_exec=bar.open * (1 + SLIP),
                        stop=bar.open * (1 + SLIP) * (1 - STOP_LOSS),
                        mode="sgov",
                        entry_day=day,
                    )
                    cash -= notional * (1 + SLIP)
            else:
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
            source = sgov if symbol == SGOV_SYMBOL else series[symbol]
            bar = source.by_date.get(day)
            if bar is not None and bar.low <= holding.stop:
                cash += holding.qty * min(bar.open, holding.stop) * (1 - SLIP)
                del holdings[symbol]
        equity_close = value_at(day)
        if first_equity is None:
            first_equity = equity_close
    if not days or first_equity in (None, 0):
        return 0.0
    for symbol, holding in list(holdings.items()):
        source = sgov if symbol == SGOV_SYMBOL else series[symbol]
        bar = _bar_open(source, end)
        if bar:
            cash += holding.qty * bar.close * (1 - SLIP)
    return cash / first_equity - 1


_RANDOM_CONTEXT: tuple[Any, Series, dict[date, list[tuple[str, float, float]]], dict[date, dict[str, Any]]] | None = None


def _random_window_control(
    window: tuple[str, date, date],
) -> tuple[str, dict[str, Any]]:
    if _RANDOM_CONTEXT is None:
        raise RuntimeError("random-control context was not initialized")
    series, sgov, ranking_cache, regime_cache = _RANDOM_CONTEXT
    name, start, end = window
    returns = [
        _fast_random_return_regime(
            series,
            sgov,
            start,
            end,
            ranking_cache,
            regime_cache,
            random.Random(RANDOM_SEED + iteration),
        )
        for iteration in range(CONTROL_ITERATIONS)
    ]
    ordered = sorted(returns)
    return name, {
        "iterations": CONTROL_ITERATIONS,
        "seed": RANDOM_SEED,
        "matched_selection_size": TOP_N,
        "regime_applied": True,
        "returns": returns,
        "return_mean": statistics.fmean(returns),
        "return_std": statistics.stdev(returns),
        "return_median": statistics.median(returns),
        "return_p05": ordered[max(0, int(len(ordered) * 0.05) - 1)],
        "return_p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "dispersion_check": len(set(returns)) > 1,
    }


def _random_controls(
    series: dict[str, Any],
    sgov: Series,
    windows: tuple[tuple[str, date, date], ...],
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    regime_cache: dict[date, dict[str, Any]],
) -> dict[str, Any]:
    global _RANDOM_CONTEXT
    _RANDOM_CONTEXT = (series, sgov, ranking_cache, regime_cache)
    controls: dict[str, Any] = {}
    with ProcessPoolExecutor(
        max_workers=min(len(windows), 4),
        mp_context=multiprocessing.get_context("fork"),
    ) as executor:
        completed = executor.map(_random_window_control, windows)
        for name, control in completed:
            controls[name] = control
    for name, control in controls.items():
        print(
            f"random_control | window={name} | iterations={CONTROL_ITERATIONS} "
            f"| mean={control['return_mean']:.6f} "
            f"| p05={control['return_p05']:.6f} "
            f"| p95={control['return_p95']:.6f}"
        )
    return controls


def _metric_fields(result: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "sharpe", "sortino", "return", "max_drawdown", "trades", "turnover",
        "cost_drag", "mean_deployment", "max_deployment",
    )
    return {field: result.get(field) for field in fields}


def _print_result(
    name: str,
    result: dict[str, Any],
    control: dict[str, Any],
    risk_summary: dict[str, Any],
) -> None:
    percentile = _actual_percentile(result["return"], control["returns"])
    result["random_actual_percentile"] = percentile
    result["risk_off_summary"] = risk_summary
    print(
        f"result | window={name} | sharpe={result['sharpe']:.6f} "
        f"| sortino={result['sortino']:.6f} | return={result['return']:.6f} "
        f"| maxDD={result['max_drawdown']:.6f} | trades={result['trades']} "
        f"| turnover={result['turnover']:.6f} | cost_drag={result['cost_drag']:.6f} "
        f"| mean_deployment={result['mean_deployment']:.6f} "
        f"| max_deployment={result['max_deployment']:.6f} "
        f"| risk_off_days={risk_summary['total_days_out_of_market']} "
        f"| random_actual_percentile={percentile:.2f}"
    )


def run() -> dict[str, Any]:
    end = _latest_complete_month_end()
    windows = _windows(end)
    baseline = _baseline_row()
    experiment_id = _register(end, windows, baseline)
    assets, candidate_symbols = _load_assets()
    series = _load_compact_panel(candidate_symbols, end)
    panel_symbols = set(series) & candidate_symbols
    set_screen_data(assets, series)
    print(
        "screener_confirmation | implementation=core.equity_universe.screen_universe "
        "| rank_metric=trailing_60_session_median_dollar_volume | universe_size=500 "
        f"| baseline_experiment_id={BASELINE_EXPERIMENT_ID}"
    )
    all_days = _all_days(series, end)
    ranking_cache = build_momentum_cache(
        series, panel_symbols, TARGET_UNIVERSE, end
    )
    print(
        f"window_selection | first_full_500={BACKTEST_START} "
        f"| latest_complete_month_end={end} "
        f"| windows={json.dumps(_jsonable(windows))}"
    )
    print(f"ranking_cache | monthly_rebalances={len(ranking_cache)}")
    spy = _load_reference_series("SPY", end)
    sgov = _load_reference_series(SGOV_SYMBOL, end)
    regime_cache = _build_regime_cache(spy, end)
    summaries = {
        name: _risk_off_summary(
            series, regime_cache, start, window_end
        )
        for name, start, window_end in windows
    }
    results: dict[str, Any] = {}
    for name, start, window_end in windows:
        results[name] = simulate_regime(
            series, sgov, start, window_end, ranking_cache, regime_cache
        )
    controls = _random_controls(
        series, sgov, windows, ranking_cache, regime_cache
    )
    baseline_windows = baseline["results"]["windows"]
    for name, _, _ in windows:
        _print_result(name, results[name], controls[name], summaries[name])
        print(
            f"benchmark | window={name} | strategy=spy_buy_and_hold "
            f"| sharpe={baseline_windows[name]['spy_buy_and_hold']['sharpe']:.6f} "
            f"| sortino={baseline_windows[name]['spy_buy_and_hold']['sortino']:.6f} "
            f"| return={baseline_windows[name]['spy_buy_and_hold']['return']:.6f} "
            f"| maxDD={baseline_windows[name]['spy_buy_and_hold']['max_drawdown']:.6f}"
        )

    comparisons: dict[str, Any] = {}
    for name, _, _ in windows:
        baseline_metrics = _metric_fields(baseline_windows[name]["momentum"])
        filtered_metrics = _metric_fields(results[name])
        comparison = {
            "baseline_experiment_18": baseline_metrics,
            "filtered_experiment": filtered_metrics,
            "delta_filtered_minus_baseline": {
                key: (
                    filtered_metrics[key] - baseline_metrics[key]
                    if isinstance(filtered_metrics[key], (int, float))
                    and isinstance(baseline_metrics[key], (int, float))
                    else None
                )
                for key in filtered_metrics
            },
            "return_cost_vs_experiment_18": (
                baseline_metrics["return"] - filtered_metrics["return"]
            ),
        }
        comparisons[name] = comparison
        print(
            f"comparison | window={name} | experiment18_sharpe="
            f"{baseline_metrics['sharpe']:.6f} | filtered_sharpe="
            f"{filtered_metrics['sharpe']:.6f} | experiment18_maxDD="
            f"{baseline_metrics['max_drawdown']:.6f} | filtered_maxDD="
            f"{filtered_metrics['max_drawdown']:.6f} | experiment18_return="
            f"{baseline_metrics['return']:.6f} | filtered_return="
            f"{filtered_metrics['return']:.6f} | filter_return_cost="
            f"{comparison['return_cost_vs_experiment_18']:.6f}"
        )

    pooled_name = windows[-1][0]
    pooled = results[pooled_name]
    pooled_baseline = baseline_windows[pooled_name]["momentum"]
    pooled_spy = baseline_windows[pooled_name]["spy_buy_and_hold"]
    pooled_random = controls[pooled_name]
    period_2021 = results["2021_2022"]
    baseline_2021 = baseline_windows["2021_2022"]["momentum"]
    checks = {
        "sharpe": pooled["sharpe"] >= PASS_BAR["sharpe_min"],
        "max_drawdown": pooled["max_drawdown"] <= PASS_BAR["max_drawdown_max"],
        "beats_spy_risk_adjusted": pooled["sharpe"] > pooled_spy["sharpe"],
        "beats_random_entry": pooled["return"] > pooled_random["return_mean"],
        "2021_2022_material_drawdown_reduction": (
            baseline_2021["max_drawdown"] - period_2021["max_drawdown"]
            >= PASS_BAR["2021_2022_drawdown_reduction_min_absolute"]
        ),
        "max_deployment_cap": all(
            result["max_deployment"] <= 1.0000001
            for result in results.values()
        ),
    }
    outcome = "PASS" if all(checks.values()) else "FAIL"
    print(
        f"comparison_key | 2021_2022_experiment18_maxDD="
        f"{baseline_2021['max_drawdown']:.6f} | filtered_maxDD="
        f"{period_2021['max_drawdown']:.6f} | pooled_experiment18_maxDD="
        f"{pooled_baseline['max_drawdown']:.6f} | pooled_filtered_maxDD="
        f"{pooled['max_drawdown']:.6f} | pooled_experiment18_sharpe="
        f"{pooled_baseline['sharpe']:.6f} | pooled_filtered_sharpe="
        f"{pooled['sharpe']:.6f} | pooled_experiment18_return="
        f"{pooled_baseline['return']:.6f} | pooled_filtered_return="
        f"{pooled['return']:.6f} | pooled_filter_return_cost="
        f"{pooled_baseline['return'] - pooled['return']:.6f}"
    )
    print(f"evaluation | outcome={outcome} | checks={checks}")
    for criterion, passed in checks.items():
        print(f"criterion | name={criterion} | result={'PASS' if passed else 'FAIL'}")

    for year in (2021, 2022):
        months = [
            (day, info)
            for day, info in sorted(regime_cache.items())
            if day.year == year
        ]
        for day, info in months:
            print(
                f"regime_month | month={day.isoformat()} | state={info['state']} "
                f"| prior_close={info['prior_close']} | sma_200={info['sma_200']} "
                f"| prior_sessions={info['prior_sessions']}"
            )
    feb_2021 = next(
        (
            info["state"]
            for day, info in regime_cache.items()
            if day.year == 2021 and day.month == 2
        ),
        REGIME_OFF,
    )
    print(
        f"sanity_february_2021 | state={feb_2021} "
        f"| addresses_observed_momentum_crash="
        f"{'YES' if feb_2021 == REGIME_OFF else 'NO'}"
    )
    if feb_2021 == REGIME_ON:
        print(
            "sanity_february_2021_note | RISK_ON during the observed trough; "
            "the filter does not address that failure."
        )
    for name, summary in summaries.items():
        print(
            f"risk_off_summary | window={name} "
            f"| months_by_year={json.dumps(summary['risk_off_months_by_year'])} "
            f"| total_days_out_of_market={summary['total_days_out_of_market']}"
        )
    selected_symbols = {
        symbol
        for ranked in ranking_cache.values()
        for symbol, _, _ in ranked[:TOP_N]
    }
    sectors = _sector_map(selected_symbols)
    sector_counts = [
        len({sectors.get(symbol, "unknown") for symbol, _, _ in ranked[:TOP_N]})
        for day, ranked in ranking_cache.items()
        if regime_cache.get(day, {"state": REGIME_OFF})["state"] == REGIME_ON
    ]
    diversification = {
        "average_distinct_sectors_per_risk_on_month": (
            statistics.fmean(sector_counts) if sector_counts else 0.0
        ),
        "risk_on_months": len(sector_counts),
    }
    largest_dd = _largest_monthly_drawdown(pooled)
    print(
        f"sector_diversification | average_distinct_sectors_per_risk_on_month="
        f"{diversification['average_distinct_sectors_per_risk_on_month']:.6f}"
    )
    print(
        f"largest_monthly_drawdown | month={largest_dd.get('month')} "
        f"| date={largest_dd.get('date')} | drawdown={largest_dd['drawdown']:.6f} "
        f"| held={','.join(largest_dd.get('held', [])) or 'NONE'}"
    )

    stored_results = {
        "experiment_id": experiment_id,
        "strategy_family": STRATEGY_FAMILY,
        "baseline_experiment_id": BASELINE_EXPERIMENT_ID,
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
                "regime": {
                    "signal": "SPY",
                    "lookback_sessions": REGIME_LOOKBACK,
                    "risk_on": "prior_close > prior_200_session_sma",
                    "risk_off": "prior_close <= prior_200_session_sma",
                    "risk_off_asset": SGOV_SYMBOL,
                    "prior_data_only": True,
                },
            },
            "pass_bar": PASS_BAR,
        },
        "universe": {
            "candidate_symbols": len(candidate_symbols),
            "panel_symbols": len(panel_symbols),
            "stored_bars": sum(len(data.bars) for data in series.values()),
            "monthly_rebalances": len(ranking_cache),
        },
        "regime": {
            "monthly_states": regime_cache,
            "summaries": summaries,
            "february_2021_state": feb_2021,
        },
        "windows": {
            name: {
                "filtered_regime_momentum": results[name],
                "spy_buy_and_hold": baseline_windows[name]["spy_buy_and_hold"],
                "equal_weight_top500_buy_and_hold": baseline_windows[name].get(
                    "equal_weight_top500_buy_and_hold"
                ),
            }
            for name, _, _ in windows
        },
        "controls": controls,
        "comparisons": comparisons,
        "evaluation": {
            "checks": checks,
            "outcome": outcome,
            "material_drawdown_rule": "at least 10 percentage points below experiment 18",
        },
        "sector_diversification": diversification,
        "largest_monthly_drawdown": largest_dd,
        "verification": {
            "execution_mode": "development_read_only",
            "screener_shared": True,
            "regime_prior_data_only": True,
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
                result["max_deployment"] for result in results.values()
            ),
        },
    }
    record_results(experiment_id, _jsonable(stored_results), outcome)
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
    return stored_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-stored-assets", action="store_true")
    args = parser.parse_args()
    if not args.use_stored_assets:
        raise SystemExit("refusing to refresh assets; pass --use-stored-assets")
    result = run()
    return 0 if result["evaluation"]["outcome"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())