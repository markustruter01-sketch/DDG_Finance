#!/usr/bin/env python3
"""Run the preregistered 64-combination rank-500 momentum sweep.

This is a development-only research job.  It reads the recovered Helium panel
through the explicit research connection and appends one row per parameter
combination to ``exploration_runs``.  It never calls a research-ledger
registration/result function, changes the price panel, or touches live
trading state.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM = _ROOT / "trading-platform"
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from db.research_postgres import (  # noqa: E402
    get_research_conn,
    research_dsn_host,
)
from analysis.bot2_momentum_pead_v4 import (  # noqa: E402
    SLIP,
    STARTING_EQUITY,
    STOP_LOSS,
    _all_days,
    _bar_before,
    _buy,
    _holding_value,
    _metrics,
    _sell,
    screen_universe_current,
)
from analysis.bot2_momentum_rank500_backtest import (  # noqa: E402
    PRICE_SOURCES,
    PRICE_TABLE,
    TARGET_UNIVERSE,
    WARMUP_START,
    _load_compact_panel,
    _latest_complete_month_end,
)
from core.equity_universe import eligible_asset_records  # noqa: E402


LOOKBACK_MONTHS = (3, 6, 9, 12)
SKIP_MONTHS = (0, 1)
TOP_NS = (10, 20, 30, 50)
REBALANCE_MODES = ("monthly", "quarterly")
BACKTEST_START = date(2019, 2, 1)
STRATEGY_FAMILY = "bot2_momentum_rank500_sweep"
SOURCE = "strategy_bench_sweep"
CSV_PATH = _ROOT / "backups" / "strategy-bench-rank500-sweep-20260903.csv"
CACHE_PATH = _ROOT / ".cache" / "strategy-bench-rank500-rank-cache.json"
PROGRESS_PATH = _ROOT / ".cache" / "strategy-bench-rank500-progress.json"
SCREEN_PROGRESS_PATH = _ROOT / ".cache" / "strategy-bench-rank500-screen-progress.json"


def _month_shift(day: date, months: int) -> date:
    ordinal = day.year * 12 + day.month - 1 + months
    year, month_zero = divmod(ordinal, 12)
    return date(year, month_zero + 1, min(day.day, 28))


def _monthly_days(days: Iterable[date]) -> list[date]:
    output: list[date] = []
    seen: set[tuple[int, int]] = set()
    for day in sorted(days):
        key = (day.year, day.month)
        if key not in seen:
            seen.add(key)
            output.append(day)
    return output


def _rebalance_days(days: list[date], mode: str, start: date) -> list[date]:
    monthly = [day for day in _monthly_days(days) if day >= start]
    if mode == "monthly":
        return monthly
    base = start.year * 12 + start.month
    return [
        day
        for day in monthly
        if ((day.year * 12 + day.month) - base) % 3 == 0
    ]


def _load_audited_candidates() -> set[str]:
    """Read the audited candidate names without issuing DDL."""
    with get_research_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT symbol, asset_class, status, exchange, tradable, name
                  FROM bot2_mechanical_assets
                 WHERE asset_class='us_equity'
                   AND instrument_classification='ordinary_equity'
                """
            )
            records = [
                {
                    "symbol": row[0],
                    "asset_class": row[1],
                    "status": row[2],
                    "exchange": row[3],
                    "tradable": row[4],
                    "name": row[5],
                }
                for row in cur.fetchall()
            ]
    eligible, funnel = eligible_asset_records(records)
    candidates = {str(row["symbol"]).upper() for row in eligible}
    print(
        f"asset_preflight | stored_assets={len(records)} "
        f"| static_eligible={funnel['asset_eligible_records']} "
        f"| candidate_symbols={len(candidates)}"
    )
    if not candidates:
        raise RuntimeError("audited asset table produced no research candidates")
    return candidates


def _rank_cache(
    series: dict[str, Any],
    symbols: set[str],
    end: date,
    lookback_months: int,
    skip_months: int,
    screen_cache: dict[date, set[str]],
) -> dict[date, list[tuple[str, float, float]]]:
    """Build point-in-time rankings for one lookback/skip pair."""
    cache: dict[date, list[tuple[str, float, float]]] = {}
    for rebalance_day in _monthly_days(_all_days(series, end)):
        screened = screen_cache[rebalance_day]
        ranked: list[tuple[str, float, float]] = []
        endpoint_day = _month_shift(rebalance_day, -skip_months)
        start_day = _month_shift(
            rebalance_day, -(lookback_months + skip_months)
        )
        for symbol in screened & symbols:
            data = series[symbol]
            endpoint = _bar_before(data, endpoint_day)
            beginning = _bar_before(data, start_day)
            if endpoint is None or beginning is None or beginning.close <= 0:
                continue
            momentum = endpoint.close / beginning.close - 1
            cutoff = bisect_left(data.days, rebalance_day)
            returns = [
                data.bars[index].close / data.bars[index - 1].close - 1
                for index in range(max(1, cutoff - 63), cutoff)
                if data.bars[index - 1].close > 0
            ]
            volatility = statistics.pstdev(returns) * math.sqrt(252) if returns else 0.0
            if momentum > 0 and volatility > 0:
                ranked.append((symbol, momentum, volatility))
        cache[rebalance_day] = sorted(
            ranked, key=lambda item: (-item[1], item[0])
        )[: max(TOP_NS)]
    return cache


def _simulate(
    series: dict[str, Any],
    start: date,
    end: date,
    calendar: list[date],
    ranking_cache: dict[date, list[tuple[str, float, float]]],
    top_n: int,
    rebalance_mode: str,
) -> dict[str, Any]:
    calendar = [day for day in calendar if day >= start and day <= end]
    rebalance_days = set(_rebalance_days(calendar, rebalance_mode, start))
    cash = STARTING_EQUITY
    holdings: dict[str, Any] = {}
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

    for day in calendar:
        for symbol, holding in list(holdings.items()):
            bar = series[symbol].by_date.get(day)
            if bar is not None and bar.low <= holding.stop:
                cash, turnover, cost_paid = _sell(
                    holding,
                    series[symbol],
                    day,
                    cash,
                    trade_returns,
                    event_log,
                    turnover,
                    cost_paid,
                    "STOP",
                )
                del holdings[symbol]
                stops += 1
        if day in rebalance_days:
            for symbol, holding in list(holdings.items()):
                cash, turnover, cost_paid = _sell(
                    holding,
                    series[symbol],
                    day,
                    cash,
                    trade_returns,
                    event_log,
                    turnover,
                    cost_paid,
                    "MONTHLY_ROTATION_OUT",
                )
                del holdings[symbol]
            selected = ranking_cache.get(day, [])[:top_n]
            weight = 1 / len(selected) if selected else 0.0
            equity_open = cash + _holding_value(holdings, series, day)
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
            holding,
            series[symbol],
            end,
            cash,
            trade_returns,
            event_log,
            turnover,
            cost_paid,
            "WINDOW_CLOSE",
        )

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
    return result


def _spec_hash(parameters: dict[str, Any], end: date) -> str:
    payload = {
        "strategy_family": STRATEGY_FAMILY,
        "parameters": parameters,
        "data_window": {
            "warmup_start": WARMUP_START.isoformat(),
            "backtest_start": BACKTEST_START.isoformat(),
            "backtest_end": end.isoformat(),
            "price_table": PRICE_TABLE,
            "price_sources": list(PRICE_SOURCES),
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _record_once(
    parameters: dict[str, Any],
    end: date,
    result: dict[str, Any],
) -> int:
    data_window = {
        "warmup_start": WARMUP_START.isoformat(),
        "backtest_start": BACKTEST_START.isoformat(),
        "backtest_end": end.isoformat(),
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "screener_implementation": "core.equity_universe.screen_universe",
        "evaluation": "descriptive_only; no pass declared",
    }
    spec_hash = _spec_hash(parameters, end)
    with get_research_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id FROM exploration_runs WHERE spec_hash=%s",
                (spec_hash,),
            )
            existing = cur.fetchone()
            if existing is not None:
                return int(existing[0])
            cur.execute(
                """
                INSERT INTO exploration_runs
                    (strategy_family, parameters, data_window, spec_hash, source,
                     sharpe, return_pct, max_drawdown, notes)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING run_id
                """,
                (
                    STRATEGY_FAMILY,
                    json.dumps(parameters, sort_keys=True),
                    json.dumps(data_window, sort_keys=True),
                    spec_hash,
                    SOURCE,
                    result["sharpe"],
                    result["return"] * 100,
                    result["max_drawdown"],
                    (
                        "descriptive_only; no pass declared; "
                        "engine=rank500_momentum_cash_constrained"
                    ),
                ),
            )
            return int(cur.fetchone()[0])


def _surface_assessment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {
        (
            row["lookback_months"],
            row["skip_month"],
            row["top_n"],
            row["rebalance"],
        ): row["sharpe"]
        for row in rows
    }
    deltas: list[float] = []
    for key, value in by_key.items():
        lookback, skip, top_n, mode = key
        for other in (
            (lookback, skip, top_n, "quarterly" if mode == "monthly" else "monthly"),
            (lookback, skip, 20 if top_n != 20 else 10, mode),
        ):
            if other in by_key:
                deltas.append(abs(value - by_key[other]))
    sharpes = [row["sharpe"] for row in rows]
    overall_range = max(sharpes) - min(sharpes)
    median_neighbor_delta = statistics.median(deltas) if deltas else 0.0
    return {
        "sharpe_min": min(sharpes),
        "sharpe_max": max(sharpes),
        "sharpe_range": overall_range,
        "median_neighbor_absolute_delta": median_neighbor_delta,
        "max_neighbor_absolute_delta": max(deltas) if deltas else 0.0,
        "neighbor_pairs": len(deltas),
        "assessment": (
            "descriptively smoother across the tested one-factor neighbors"
            if overall_range and median_neighbor_delta < overall_range / 3
            else "descriptively spiky or locally uneven across the tested neighbors"
        ),
    }


def _cache_payload(
    end: date,
    candidates: set[str],
    calendar: list[date],
    rank_caches: dict[tuple[int, int], dict[date, list[tuple[str, float, float]]]],
) -> dict[str, Any]:
    return {
        "version": 1,
        "end": end.isoformat(),
        "candidate_count": len(candidates),
        "calendar": [day.isoformat() for day in calendar],
        "rank_caches": {
            f"{lookback}:{skip}": {
                day.isoformat(): [
                    [symbol, momentum, volatility]
                    for symbol, momentum, volatility in rankings
                ]
                for day, rankings in cache.items()
            }
            for (lookback, skip), cache in rank_caches.items()
        },
    }


def _load_cached_rankings(
    end: date,
) -> tuple[list[date], dict[tuple[int, int], dict[date, list[tuple[str, float, float]]]]] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("version") != 1 or payload.get("end") != end.isoformat():
        return None
    calendar = [date.fromisoformat(value) for value in payload["calendar"]]
    rank_caches = {}
    for key, values in payload["rank_caches"].items():
        lookback_text, skip_text = key.split(":")
        rank_caches[(int(lookback_text), int(skip_text))] = {
            date.fromisoformat(day): [
                (str(symbol), float(momentum), float(volatility))
                for symbol, momentum, volatility in rankings
            ]
            for day, rankings in values.items()
        }
    return calendar, rank_caches


def _cached_symbols(
    rank_caches: dict[tuple[int, int], dict[date, list[tuple[str, float, float]]]],
) -> set[str]:
    return {
        symbol
        for cache in rank_caches.values()
        for rankings in cache.values()
        for symbol, _, _ in rankings
    }


def _load_progress() -> dict[str, dict[str, Any]]:
    if not PROGRESS_PATH.exists():
        return {}
    return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))


def _load_screen_progress(end: date, candidate_count: int) -> dict[date, set[str]]:
    if not SCREEN_PROGRESS_PATH.exists():
        return {}
    try:
        payload = json.loads(SCREEN_PROGRESS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != 1 or payload.get("end") != end.isoformat():
        return {}
    if payload.get("candidate_count") != candidate_count:
        return {}
    return {
        date.fromisoformat(day): set(symbols)
        for day, symbols in payload.get("screen_cache", {}).items()
    }


def _save_screen_progress(
    end: date,
    candidate_count: int,
    screen_cache: dict[date, set[str]],
) -> None:
    SCREEN_PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCREEN_PROGRESS_PATH.write_text(
        json.dumps(
            {
                "version": 1,
                "end": end.isoformat(),
                "candidate_count": candidate_count,
                "screen_cache": {
                    day.isoformat(): sorted(symbols)
                    for day, symbols in screen_cache.items()
                },
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _progress_key(lookback: int, skip: int, top_n: int, rebalance: str) -> str:
    return f"{lookback}|{skip}|{top_n}|{rebalance}"


def run(output_path: Path = CSV_PATH) -> list[dict[str, Any]]:
    end = _latest_complete_month_end()
    candidates = _load_audited_candidates()
    print(
        f"SWEEP_PROVENANCE | database=heliumdb | host={research_dsn_host()} "
        f"| price_table={PRICE_TABLE} | price_sources={list(PRICE_SOURCES)} "
        f"| warmup={WARMUP_START} | start={BACKTEST_START} | end={end}"
    )
    cached = _load_cached_rankings(end)
    if cached is None:
        series = _load_compact_panel(candidates, end)
        symbols = set(series) & candidates
        if not symbols:
            raise RuntimeError("research panel has no overlap with audited candidates")
        all_days = _all_days(series, end)
        print(
            f"SWEEP_PANEL | candidates={len(candidates)} | panel_symbols={len(symbols)} "
            f"| stored_bars={sum(len(item.bars) for item in series.values())}"
        )
        screen_cache = _load_screen_progress(end, len(candidates))
        monthly_days = _monthly_days(all_days)
        for index, rebalance_day in enumerate(monthly_days, 1):
            if rebalance_day in screen_cache:
                continue
            if rebalance_day < BACKTEST_START:
                screen_cache[rebalance_day] = set()
                _save_screen_progress(end, len(candidates), screen_cache)
                continue
            screened, _ = screen_universe_current(
                series,
                symbols,
                rebalance_day,
                TARGET_UNIVERSE,
            )
            screen_cache[rebalance_day] = screened
            if index == 1 or index % 12 == 0 or index == len(monthly_days):
                print(
                    f"SCREEN_CACHE | month={index}/{len(monthly_days)} "
                    f"| date={rebalance_day} | symbols={len(screened)}"
                )
            _save_screen_progress(end, len(candidates), screen_cache)
        rank_caches = {}
        for lookback in LOOKBACK_MONTHS:
            for skip in SKIP_MONTHS:
                print(f"RANK_CACHE | lookback_months={lookback} | skip_month={skip}")
                rank_caches[(lookback, skip)] = _rank_cache(
                    series, symbols, end, lookback, skip, screen_cache
                )
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(
                _cache_payload(end, candidates, all_days, rank_caches),
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        calendar = all_days
    else:
        calendar, rank_caches = cached
        symbols = _cached_symbols(rank_caches)
        if not symbols:
            raise RuntimeError("cached rank results contain no selected symbols")
        print(
            f"RANK_CACHE | loaded={CACHE_PATH} | selected_symbols={len(symbols)} "
            f"| calendar_days={len(calendar)}"
        )
        series = _load_compact_panel(symbols, end)
    if not series:
        raise RuntimeError("research panel has no rows for selected symbols")
    print(
        f"SWEEP_PANEL | candidates={len(candidates)} | panel_symbols={len(series)} "
        f"| stored_bars={sum(len(item.bars) for item in series.values())}"
    )

    progress = _load_progress()
    rows: list[dict[str, Any]] = []

    combinations = [
        (lookback, skip, top_n, rebalance)
        for lookback in LOOKBACK_MONTHS
        for skip in SKIP_MONTHS
        for top_n in TOP_NS
        for rebalance in REBALANCE_MODES
    ]
    for index, (lookback, skip, top_n, rebalance) in enumerate(combinations, 1):
        key = _progress_key(lookback, skip, top_n, rebalance)
        if key in progress:
            row = progress[key]
            rows.append(row)
            print(
                f"SWEEP_RESUME | index={index}/64 | run_id={row['run_id']} "
                f"| lookback={lookback} | skip={skip} | top_n={top_n} "
                f"| rebalance={rebalance}"
            )
            continue
        result = _simulate(
            series,
            BACKTEST_START,
            end,
            calendar,
            rank_caches[(lookback, skip)],
            top_n,
            rebalance,
        )
        parameters = {
            "universe_size": TARGET_UNIVERSE,
            "lookback_months": lookback,
            "skip_month": skip,
            "top_n": top_n,
            "rebalance": rebalance,
            "allocation": "equal_weight",
            "slippage_each_leg_bps": 10,
            "catastrophe_stop": STOP_LOSS,
            "max_deployment": 1.0,
            "momentum_definition": (
                "close before rebalance month minus skip months divided by "
                "close before rebalance month minus lookback plus skip months"
            ),
        }
        run_id = _record_once(parameters, end, result)
        row = {
            "lookback_months": lookback,
            "skip_month": skip,
            "top_n": top_n,
            "rebalance": rebalance,
            "sharpe": result["sharpe"],
            "return": result["return"],
            "return_pct": result["return"] * 100,
            "max_drawdown": result["max_drawdown"],
            "max_drawdown_pct": result["max_drawdown"] * 100,
            "trades": result["trades"],
            "turnover": result["turnover"],
            "run_id": run_id,
        }
        rows.append(row)
        progress[key] = row
        PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_PATH.write_text(
            json.dumps(progress, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        print(
            f"SWEEP_ROW | index={index}/64 | run_id={run_id} "
            f"| lookback={lookback} | skip={skip} | top_n={top_n} "
            f"| rebalance={rebalance} | sharpe={row['sharpe']:.9f} "
            f"| return={row['return']:.9f} | maxDD={row['max_drawdown']:.9f} "
            f"| trades={row['trades']} | turnover={row['turnover']:.9f}"
        )

    rows.sort(
        key=lambda row: (
            -row["sharpe"],
            -row["return"],
            row["lookback_months"],
            row["skip_month"],
            row["top_n"],
            row["rebalance"],
        )
    )
    fieldnames = [
        "lookback_months",
        "skip_month",
        "top_n",
        "rebalance",
        "sharpe",
        "return",
        "return_pct",
        "max_drawdown",
        "max_drawdown_pct",
        "trades",
        "turnover",
        "run_id",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\nCOMPLETE_SORTED_RESULTS")
    print("lookback_months,skip_month,top_n,rebalance,sharpe,return_pct,max_drawdown_pct,trades,turnover,run_id")
    for row in rows:
        print(
            f"{row['lookback_months']},{row['skip_month']},{row['top_n']},"
            f"{row['rebalance']},{row['sharpe']:.9f},{row['return_pct']:.6f},"
            f"{row['max_drawdown_pct']:.6f},{row['trades']},"
            f"{row['turnover']:.9f},{row['run_id']}"
        )
    noise_floor = math.sqrt(2 * math.log(len(rows))) / math.sqrt(7.5)
    print(f"\nNOISE_FLOOR | N={len(rows)} | years=7.5 | sharpe={noise_floor:.9f}")
    print("SURFACE_ASSESSMENT | " + json.dumps(_surface_assessment(rows), sort_keys=True))
    print(f"CSV | path={output_path} | rows={len(rows)}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    args = parser.parse_args()
    rows = run(args.csv)
    if len(rows) != 64:
        raise SystemExit(f"expected 64 combinations, got {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())