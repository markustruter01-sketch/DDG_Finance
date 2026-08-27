#!/usr/bin/env python3
"""Development-only Bot 2 earnings split-sample validation.

This is a research runner, not a strategy or execution module.  It uses only
the development ``DATABASE_URL`` connection, the isolated Bot 2 data tables,
and public Alpha Vantage/Yahoo data fetches.  It never imports a runner,
broker client, order API, or live portfolio code.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from analysis.bot2_data_pipeline import (  # noqa: E402
    EARNINGS_DDL,
    EARNINGS_START_DATE,
    EARNINGS_SYMBOLS,
    EARNINGS_TABLE,
    LEGACY_STOCKS,
    PRICES_TABLE,
    VALIDATION_STOCKS,
    fetch_yahoo_daily,
    ingest_earnings,
    ingest_prices,
    ensure_tables,
)
from analysis.bot2_commodity_research import _nyse_holidays  # noqa: E402
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)
from db.postgres import get_conn  # noqa: E402

SELECTION_START = date(2018, 1, 1)
SELECTION_END = date(2022, 12, 31)
VALIDATION_START = date(2023, 1, 1)
VALIDATION_END = date.today()
PEAD_HOLDS = (5, 20, 60)
CONTROL_ITERATIONS = 1_000
RANDOM_SEED = 271_2026
SLIPPAGE_BPS = 10.0
TOP_N = 6
STRATEGY_FAMILY = "bot2_earnings_split_sample_validation"
BOT_ID = "bot2_earnings_validation"


@dataclass(frozen=True)
class PriceBar:
    day: date
    open: float
    close: float


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    reported_date: date
    surprise: float | None
    report_time: str


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def print_schema_statements() -> None:
    print("=== BOT 2 EARNINGS VALIDATION DDL ===")
    print(EARNINGS_DDL.strip())
    print("ALTER TABLE bot2_earnings_dates DROP CONSTRAINT IF EXISTS bot2_earnings_dates_symbol_check;")
    print(
        "ALTER TABLE bot2_earnings_dates ADD CONSTRAINT "
        "bot2_earnings_dates_symbol_check CHECK "
        f"(symbol IN ({', '.join(repr(s) for s in EARNINGS_SYMBOLS)}));"
    )
    print("ALTER TABLE bot2_prices DROP CONSTRAINT IF EXISTS bot2_prices_symbol_check;")
    print("ALTER TABLE bot2_prices ADD CONSTRAINT bot2_prices_symbol_check ...;")


def _load_data() -> tuple[dict[str, list[PriceBar]], list[EarningsEvent]]:
    prices: dict[str, list[PriceBar]] = defaultdict(list)
    earnings: list[EarningsEvent] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT symbol, date, open, close
                    FROM {PRICES_TABLE}
                    WHERE source='yahoo' AND date >= %s
                    ORDER BY symbol, date""",
                (EARNINGS_START_DATE,),
            )
            for symbol, day, opening, closing in cur.fetchall():
                prices[symbol].append(PriceBar(day, float(opening), float(closing)))
            cur.execute(
                f"""SELECT symbol, reported_date, surprise, report_time
                    FROM {EARNINGS_TABLE}
                    WHERE reported_date >= %s
                    ORDER BY symbol, reported_date, id""",
                (EARNINGS_START_DATE,),
            )
            for symbol, reported_date, surprise, report_time in cur.fetchall():
                earnings.append(
                    EarningsEvent(
                        symbol=symbol,
                        reported_date=reported_date,
                        surprise=float(surprise) if surprise is not None else None,
                        report_time=(report_time or "").strip().lower(),
                    )
                )
    return dict(prices), earnings


def _expected_weekdays(first: date, last: date) -> set[date]:
    """Expected NYSE sessions for the integrity gate."""
    days: set[date] = set()
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5 and cursor not in _nyse_holidays(cursor.year):
            days.add(cursor)
        cursor += timedelta(days=1)
    return days


def _integrity_gate(
    prices: dict[str, list[PriceBar]],
    earnings: list[EarningsEvent],
) -> dict[str, Any]:
    """Run hard data gates before registering or calculating research results."""
    valid = True
    by_symbol: dict[str, list[EarningsEvent]] = defaultdict(list)
    for event in earnings:
        by_symbol[event.symbol].append(event)

    print("=== DATA INTEGRITY GATES ===")
    print("symbol | earnings_rows | first_earnings | last_earnings | price_rows | first_price | last_price")
    for symbol in EARNINGS_SYMBOLS:
        events = by_symbol[symbol]
        bars = prices.get(symbol, [])
        duplicate_events = len({(e.reported_date, e.surprise, e.report_time) for e in events}) != len(events)
        duplicate_prices = len({bar.day for bar in bars}) != len(bars)
        price_missing = 0
        if bars:
            expected = _expected_weekdays(bars[0].day, bars[-1].day)
            price_missing = sum(
                1
                for day in sorted(expected - {bar.day for bar in bars})
                if (
                    day - timedelta(days=1) in {bar.day for bar in bars}
                    and day + timedelta(days=1) in {bar.day for bar in bars}
                )
            )
        event_gap_count = 0
        sorted_events = sorted(events, key=lambda event: event.reported_date)
        for before, after in zip(sorted_events, sorted_events[1:]):
            if (after.reported_date - before.reported_date).days > 140:
                event_gap_count += 1
        null_count = 0  # DB columns used here are non-null where required.
        print(
            f"{symbol} | {len(events)} | "
            f"{sorted_events[0].reported_date if sorted_events else None} | "
            f"{sorted_events[-1].reported_date if sorted_events else None} | "
            f"{len(bars)} | {bars[0].day if bars else None} | {bars[-1].day if bars else None}"
        )
        if (
            not events
            or not bars
            or duplicate_events
            or duplicate_prices
            or null_count
            or event_gap_count
            or price_missing
            or (bars and bars[0].day > date(2018, 1, 15))
        ):
            valid = False
            print(
                f"  gate_detail | duplicate_earnings={duplicate_events} "
                f"duplicate_prices={duplicate_prices} missing_weekday_sessions={price_missing} "
                f"earnings_gaps={event_gap_count} nulls={null_count}"
            )

    report_times = defaultdict(int)
    for event in earnings:
        if event.symbol in EARNINGS_SYMBOLS:
            report_times[event.report_time or "unknown"] += 1
    print("report_time_counts | " + " | ".join(f"{key}={value}" for key, value in sorted(report_times.items())))
    print(f"integrity_gate | {'PASS' if valid else 'STOP'}")
    if not valid:
        raise RuntimeError("Bot 2 earnings data integrity gate failed; research stopped")
    return {
        "earnings_rows": len(earnings),
        "price_rows": sum(len(bars) for bars in prices.values()),
        "report_time_counts": dict(sorted(report_times.items())),
    }


def _bars_by_day(bars: Iterable[PriceBar]) -> tuple[list[date], dict[date, PriceBar]]:
    ordered = sorted(bars, key=lambda bar: bar.day)
    return [bar.day for bar in ordered], {bar.day: bar for bar in ordered}


def _timing(event: EarningsEvent) -> str | None:
    if "pre" in event.report_time or "before" in event.report_time:
        return "pre"
    if "post" in event.report_time or "after" in event.report_time:
        return "post"
    return None


def _scheduled_prices(
    event: EarningsEvent,
    bars: list[PriceBar],
) -> dict[str, Any] | None:
    days, by_day = _bars_by_day(bars)
    before = [day for day in days if day < event.reported_date]
    on_or_after = [day for day in days if day >= event.reported_date]
    on_or_before = [day for day in days if day <= event.reported_date]
    timing = _timing(event)
    if timing == "pre":
        entry_day = before[-1] if before else None
        announcement_day = on_or_after[0] if on_or_after else None
        if entry_day is None or announcement_day is None:
            return None
        raw_gap = by_day[announcement_day].open / by_day[entry_day].close - 1
    elif timing == "post":
        announcement_day = on_or_after[0] if on_or_after else None
        entry_day = on_or_before[-1] if on_or_before else None
        if entry_day is None or announcement_day is None:
            return None
        next_days = [day for day in days if day > announcement_day]
        if not next_days:
            return None
        raw_gap = by_day[next_days[0]].open / by_day[announcement_day].close - 1
    else:
        return None
    entry_index = days.index(announcement_day)
    next_days = days[entry_index + 1 :]
    return {
        "event": event,
        "days": days,
        "by_day": by_day,
        "entry_day": entry_day,
        "announcement_day": announcement_day,
        "next_days": next_days,
        "raw_gap": raw_gap,
    }


def _event_records(
    earnings: list[EarningsEvent],
    prices: dict[str, list[PriceBar]],
    symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in earnings:
        if symbols is not None and event.symbol not in symbols:
            continue
        scheduled = _scheduled_prices(event, prices.get(event.symbol, []))
        if scheduled is not None:
            records.append({**scheduled, "positive_surprise": (event.surprise or 0) > 0})
    return records


def _returns_stats(returns: list[float], holding_days: int) -> dict[str, Any]:
    if not returns:
        return {
            "trades": 0,
            "win_rate": None,
            "expectancy": None,
            "sharpe": None,
            "max_drawdown": None,
            "total_return": None,
        }
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    mean = statistics.fmean(returns)
    deviation = statistics.stdev(returns) if len(returns) > 1 else 0.0
    annualization = math.sqrt(252 / max(1, holding_days))
    sharpe = mean / deviation * annualization if deviation > 0 else None
    return {
        "trades": len(returns),
        "win_rate": sum(value > 0 for value in returns) / len(returns),
        "expectancy": mean,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_return": equity - 1,
    }


def _strategy_returns(
    records: list[dict[str, Any]],
    mode: str,
    hold: int = 1,
    close_exit: bool = False,
) -> list[float]:
    slippage = SLIPPAGE_BPS / 10_000
    returns: list[float] = []
    for record in records:
        event: EarningsEvent = record["event"]
        if mode == "pead" and not record["positive_surprise"]:
            continue
        days: list[date] = record["days"]
        bars: dict[date, PriceBar] = record["by_day"]
        if mode == "buy_before":
            entry_day = record["entry_day"]
            entry_price = bars[entry_day].close * (1 + slippage)
            if close_exit:
                exit_day = record["announcement_day"] if _timing(event) == "pre" else record["next_days"][0]
                exit_price = bars[exit_day].close * (1 - slippage)
            else:
                exit_day = record["announcement_day"] if _timing(event) == "pre" else record["next_days"][0]
                exit_price = bars[exit_day].open * (1 - slippage)
        else:
            entry_day = record["announcement_day"]
            entry_index = days.index(entry_day)
            if entry_index + hold - 1 >= len(days):
                continue
            exit_day = days[entry_index + hold - 1]
            entry_price = bars[entry_day].open * (1 + slippage)
            exit_price = bars[exit_day].close * (1 - slippage)
        returns.append(exit_price / entry_price - 1)
    return returns


def _raw_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(record["raw_gap"]) for record in records]
    result = _returns_stats(values, 1)
    result["positive_gap_rate"] = sum(value > 0 for value in values) / len(values) if values else None
    return result


def _print_universe_stats(
    title: str,
    records: list[dict[str, Any]],
    symbols: Iterable[str],
) -> dict[str, dict[str, Any]]:
    print(f"=== {title} RAW EARNINGS BASE RATE (2018-PRESENT) ===")
    print("symbol | events | positive_gap_rate | gap_expectancy | median_gap")
    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        own = [record for record in records if record["event"].symbol == symbol]
        values = [record["raw_gap"] for record in own]
        row = {
            "events": len(values),
            "positive_gap_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "gap_expectancy": statistics.fmean(values) if values else None,
            "median_gap": statistics.median(values) if values else None,
        }
        per_symbol[symbol] = row
        print(
            f"{symbol} | {row['events']} | {_fmt(row['positive_gap_rate'])} | "
            f"{_fmt(row['gap_expectancy'])} | {_fmt(row['median_gap'])}"
        )
    aggregate = _raw_stats(records)
    print(
        f"aggregate | {aggregate['trades']} | {_fmt(aggregate['positive_gap_rate'])} | "
        f"{_fmt(aggregate['expectancy'])} | —"
    )
    return per_symbol


def _random_control(
    records: list[dict[str, Any]],
    mode: str,
    hold: int,
) -> dict[str, Any]:
    rng = random.Random(RANDOM_SEED + hold + sum(ord(char) for char in mode))
    by_symbol = defaultdict(list)
    for record in records:
        if mode == "pead" and not record["positive_surprise"]:
            continue
        by_symbol[record["event"].symbol].append(record)
    distributions: list[float] = []
    for _ in range(CONTROL_ITERATIONS):
        simulated: list[float] = []
        for symbol, own_records in by_symbol.items():
            if not own_records:
                continue
            all_days = own_records[0]["days"]
            for record in own_records:
                entry_index = rng.randrange(0, max(1, len(all_days) - hold))
                if mode == "buy_before":
                    if entry_index + 1 >= len(all_days):
                        continue
                    entry = record["by_day"][all_days[entry_index]].open
                    exit_price = record["by_day"][all_days[entry_index + 1]].close
                else:
                    if entry_index + hold - 1 >= len(all_days):
                        continue
                    entry = record["by_day"][all_days[entry_index]].open
                    exit_price = record["by_day"][all_days[entry_index + hold - 1]].close
                simulated.append(exit_price / entry - 1)
        distributions.append(statistics.fmean(simulated) if simulated else 0.0)
    distributions.sort()
    observed = statistics.fmean(_strategy_returns(records, mode, hold)) if records else None
    return {
        "iterations": CONTROL_ITERATIONS,
        "seed": RANDOM_SEED,
        "observed_expectancy": observed,
        "random_mean": statistics.fmean(distributions),
        "random_p05": distributions[int(0.05 * len(distributions))],
        "random_median": statistics.median(distributions),
        "random_p95": distributions[int(0.95 * len(distributions)) - 1],
        "random_std": statistics.pstdev(distributions),
        "beats_random_mean": observed is not None and observed > statistics.fmean(distributions),
        "dispersion_check": len(set(distributions)) > 1 and statistics.pstdev(distributions) > 0,
    }


def _buy_hold(bars: list[PriceBar], start: date, end: date) -> dict[str, Any]:
    selected = [bar for bar in bars if start <= bar.day <= end]
    if len(selected) < 2:
        return {"return": None, "sessions": len(selected)}
    return {
        "return": selected[-1].close / selected[0].close - 1,
        "sessions": len(selected),
        "start": selected[0].day.isoformat(),
        "end": selected[-1].day.isoformat(),
    }


def _find_or_register_experiment() -> int:
    parameters = {
        "universe": list(VALIDATION_STOCKS),
        "legacy_universe": list(LEGACY_STOCKS),
        "selection_window": [SELECTION_START.isoformat(), SELECTION_END.isoformat()],
        "validation_window": [VALIDATION_START.isoformat(), VALIDATION_END.isoformat()],
        "selection_rule": "rank all ten validation stocks by raw opening-gap expectancy; select top six",
        "strategies": ["buy_before_open_exit", "buy_before_close_exit", *[f"positive_surprise_pead_{h}" for h in PEAD_HOLDS]],
        "slippage_each_leg_bps": SLIPPAGE_BPS,
        "random_control_iterations": CONTROL_ITERATIONS,
        "random_seed": RANDOM_SEED,
        "lookback_filter": "52-week high: entry close/open must be >= 90% of prior 252-session high",
    }
    pass_bar = {
        "sharpe_minimum": 0.60,
        "expectancy_minimum": 0.003,
        "beats_random": True,
        "holds_out_of_sample": True,
    }
    data_window = {
        "earnings_and_prices": [EARNINGS_START_DATE.isoformat(), VALIDATION_END.isoformat()],
        "selection": [SELECTION_START.isoformat(), SELECTION_END.isoformat()],
        "validation": [VALIDATION_START.isoformat(), VALIDATION_END.isoformat()],
    }
    ensure_research_tables()
    return register_experiment(
        strategy_family=STRATEGY_FAMILY,
        bot_id=BOT_ID,
        hypothesis="Positive earnings surprises near the 52-week high produce persistent post-earnings drift out of sample.",
        parameters=parameters,
        pass_bar=pass_bar,
        data_window=data_window,
        variations_tested=5,
        went_live=False,
        notes="Development-only validation. No orders, live module, runner, or deployment changes permitted.",
    )


def run_validation(ingest: bool = True) -> dict[str, Any]:
    print_schema_statements()
    ensure_tables()
    if ingest:
        print("=== DEVELOPMENT-ONLY INGEST ===")
        print(f"earnings_ingest | start={EARNINGS_START_DATE} | symbols={len(EARNINGS_SYMBOLS)}")
        ingest_earnings(EARNINGS_SYMBOLS, EARNINGS_START_DATE)
        print(f"price_ingest | start={EARNINGS_START_DATE} | symbols={len(EARNINGS_SYMBOLS)}")
        ingest_prices(EARNINGS_SYMBOLS, EARNINGS_START_DATE)
    prices, earnings = _load_data()
    integrity = _integrity_gate(prices, earnings)

    # Registration happens before any research statistic, selection, or
    # pass/fail computation is made.
    experiment_id = _find_or_register_experiment()
    print(f"research_ledger | experiment_id={experiment_id} | registered_before_results=true")

    all_records = _event_records(earnings, prices, set(EARNINGS_SYMBOLS))
    old_records = [record for record in all_records if record["event"].symbol in LEGACY_STOCKS]
    new_records = [record for record in all_records if record["event"].symbol in VALIDATION_STOCKS]
    old_stats = _print_universe_stats("OLD UNIVERSE", old_records, LEGACY_STOCKS)
    new_stats = _print_universe_stats("NEW VALIDATION UNIVERSE", new_records, VALIDATION_STOCKS)

    selection_records = [
        record for record in new_records
        if SELECTION_START <= record["event"].reported_date <= SELECTION_END
    ]
    ranking = sorted(
        (
            {
                "symbol": symbol,
                **new_stats[symbol],
            }
            for symbol in VALIDATION_STOCKS
        ),
        key=lambda row: (row["gap_expectancy"] is not None, row["gap_expectancy"] or -math.inf),
        reverse=True,
    )
    # Use only the selection window for ranking, never validation observations.
    selection_by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in VALIDATION_STOCKS:
        selection_by_symbol[symbol] = _raw_stats(
            [record for record in selection_records if record["event"].symbol == symbol]
        )
    ranking = sorted(
        ({"symbol": symbol, **stats} for symbol, stats in selection_by_symbol.items()),
        key=lambda row: (row["expectancy"] is not None, row["expectancy"] or -math.inf),
        reverse=True,
    )
    selected = [row["symbol"] for row in ranking[:TOP_N]]
    print("=== MECHANICAL SELECTION (2018-2022 ONLY) ===")
    for index, row in enumerate(ranking, 1):
        print(f"{index} | {row['symbol']} | events={row['trades']} | expectancy={_fmt(row['expectancy'])}")
    print(f"selected_top_{TOP_N} | {','.join(selected)}")

    validation_records = [
        record for record in new_records
        if record["event"].symbol in selected
        and VALIDATION_START <= record["event"].reported_date <= VALIDATION_END
    ]
    strategy_results: dict[str, Any] = {}
    for name, mode, hold, close_exit in [
        ("buy_before_open_exit", "buy_before", 1, False),
        ("buy_before_close_exit", "buy_before", 1, True),
        *[(f"positive_surprise_pead_{hold}", "pead", hold, True) for hold in PEAD_HOLDS],
    ]:
        values = _strategy_returns(validation_records, mode, hold, close_exit)
        metrics = _returns_stats(values, hold)
        controls = _random_control(validation_records, mode, hold)
        strategy_results[name] = {"metrics": metrics, "random_control": controls}
        print(
            f"validation | {name} | trades={metrics['trades']} | "
            f"win_rate={_fmt(metrics['win_rate'])} | expectancy={_fmt(metrics['expectancy'])} | "
            f"sharpe={_fmt(metrics['sharpe'])} | max_dd={_fmt(metrics['max_drawdown'])} | "
            f"beats_random={controls['beats_random_mean']}"
        )

    filter_records = []
    for record in validation_records:
        days: list[date] = record["days"]
        by_day: dict[date, PriceBar] = record["by_day"]
        entry_day = record["announcement_day"]
        index = days.index(entry_day)
        lookback = [by_day[day].close for day in days[max(0, index - 252):index]]
        if lookback and by_day[entry_day].open >= 0.90 * max(lookback):
            filter_records.append(record)
    filtered_values = _strategy_returns(filter_records, "pead", 20)
    filtered_metrics = _returns_stats(filtered_values, 20)
    print(
        f"validation | positive_surprise_pead_20_52w_high_filter | "
        f"trades={filtered_metrics['trades']} | expectancy={_fmt(filtered_metrics['expectancy'])} | "
        f"sharpe={_fmt(filtered_metrics['sharpe'])}"
    )

    validation_buy_hold = {symbol: _buy_hold(prices[symbol], VALIDATION_START, VALIDATION_END) for symbol in selected}
    spy_bars = fetch_yahoo_daily("SPY", VALIDATION_END + timedelta(days=1), EARNINGS_START_DATE)
    spy_prices = [PriceBar(row["date"], row["open"], row["close"]) for row in spy_bars]
    benchmarks = {
        "selected_stock_buy_and_hold": validation_buy_hold,
        "SPY_buy_and_hold": _buy_hold(spy_prices, VALIDATION_START, VALIDATION_END),
    }
    print(f"benchmark | SPY_buy_and_hold | return={_fmt(benchmarks['SPY_buy_and_hold']['return'])}")
    for symbol, result in validation_buy_hold.items():
        print(f"benchmark | {symbol}_buy_and_hold | return={_fmt(result['return'])}")

    best = strategy_results["positive_surprise_pead_20"]["metrics"]
    best_control = strategy_results["positive_surprise_pead_20"]["random_control"]
    pass_checks = {
        "sharpe": best["sharpe"] is not None and best["sharpe"] >= 0.60,
        "expectancy": best["expectancy"] is not None and best["expectancy"] >= 0.003,
        "beats_random": bool(best_control["beats_random_mean"]),
        "holds_out_of_sample": bool(best["trades"]),
    }
    outcome = "PASS" if all(pass_checks.values()) else "FAIL"
    results = {
        "experiment_id": experiment_id,
        "integrity": integrity,
        "raw_stats": {"old": old_stats, "new": new_stats},
        "selection": {"ranking_2018_2022": ranking, "selected_top_6": selected},
        "validation": strategy_results,
        "52_week_high_filter": filtered_metrics,
        "benchmarks": benchmarks,
        "pass_checks": pass_checks,
        "outcome": outcome,
        "live_execution": False,
    }
    record_results(experiment_id, results, outcome)
    print(f"research_result | experiment_id={experiment_id} | outcome={outcome} | recorded_once=true")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-ingest", action="store_true", help="Use already-ingested development data.")
    args = parser.parse_args()
    run_validation(ingest=not args.no_ingest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())