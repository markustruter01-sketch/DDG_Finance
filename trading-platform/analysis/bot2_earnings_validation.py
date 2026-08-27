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
    ALL_SYMBOLS,
    LEGACY_STOCKS,
    PRICES_TABLE,
    VALIDATION_STOCKS,
    fetch_yahoo_daily,
    ingest_earnings,
    ingest_prices,
    ensure_tables,
    _nyse_holidays,
)
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
STRATEGY_FAMILY = "bot2_earnings_universe_v2"
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
    fiscal_date_ending: date | None
    reported_eps: float | None
    estimated_eps: float | None
    surprise: float | None
    report_time: str
    source: str


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
    print(
        "ALTER TABLE bot2_earnings_dates ADD COLUMN IF NOT EXISTS "
        "source TEXT NOT NULL DEFAULT 'alphavantage';"
    )
    print("ALTER TABLE bot2_earnings_dates DROP CONSTRAINT IF EXISTS bot2_earnings_dates_source_check;")
    print(
        "ALTER TABLE bot2_earnings_dates ADD CONSTRAINT "
        "bot2_earnings_dates_source_check CHECK (source IN ('alphavantage', 'manual'));"
    )
    print("ALTER TABLE bot2_prices DROP CONSTRAINT IF EXISTS bot2_prices_symbol_check;")
    print(
        "ALTER TABLE bot2_prices ADD CONSTRAINT bot2_prices_symbol_check CHECK "
        f"(symbol IN ({', '.join(repr(s) for s in ALL_SYMBOLS)}));"
    )


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
                f"""SELECT symbol, reported_date, fiscal_date_ending,
                           reported_eps, estimated_eps, surprise, report_time, source
                    FROM {EARNINGS_TABLE}
                    WHERE reported_date >= %s
                    ORDER BY symbol, reported_date, id""",
                (EARNINGS_START_DATE,),
            )
            for (
                symbol,
                reported_date,
                fiscal_date_ending,
                reported_eps,
                estimated_eps,
                surprise,
                report_time,
                source,
            ) in cur.fetchall():
                earnings.append(
                    EarningsEvent(
                        symbol=symbol,
                        reported_date=reported_date,
                        fiscal_date_ending=fiscal_date_ending,
                        reported_eps=float(reported_eps) if reported_eps is not None else None,
                        estimated_eps=float(estimated_eps) if estimated_eps is not None else None,
                        surprise=float(surprise) if surprise is not None else None,
                        report_time=(report_time or "").strip().lower(),
                        source=source or "alphavantage",
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
    print(
        "symbol | earnings_rows | first_earnings | last_earnings | "
        "missing_fiscal_quarters | nulls | fiscal_year_type | price_rows | first_price | last_price"
    )
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
        sorted_events = sorted(events, key=lambda event: event.reported_date)
        fiscal_events = sorted(
            (event for event in events if event.fiscal_date_ending is not None),
            key=lambda event: event.fiscal_date_ending,
        )
        fiscal_gap_count = 0
        for before, after in zip(fiscal_events, fiscal_events[1:]):
            month_delta = (
                (after.fiscal_date_ending.year - before.fiscal_date_ending.year) * 12
                + after.fiscal_date_ending.month - before.fiscal_date_ending.month
            )
            if month_delta > 4:
                fiscal_gap_count += max(1, round(month_delta / 3) - 1)
        null_count = sum(
            event.fiscal_date_ending is None or not event.report_time
            for event in events
        )
        eps_null_count = sum(
            event.reported_eps is None or event.estimated_eps is None
            for event in events
        )
        fiscal_year_type = _fiscal_year_type(symbol)
        print(
            f"{symbol} | {len(events)} | "
            f"{sorted_events[0].reported_date if sorted_events else None} | "
            f"{sorted_events[-1].reported_date if sorted_events else None} | "
            f"{fiscal_gap_count} | required={null_count},eps={eps_null_count} | "
            f"{fiscal_year_type} | {len(bars)} | {bars[0].day if bars else None} | "
            f"{bars[-1].day if bars else None}"
        )
        if (
            not events
            or not bars
            or duplicate_events
            or duplicate_prices
            or null_count
            or fiscal_gap_count
            or price_missing
            or (bars and bars[0].day > date(2018, 1, 15))
        ):
            valid = False
            print(
                f"  gate_detail | duplicate_earnings={duplicate_events} "
                f"duplicate_prices={duplicate_prices} missing_weekday_sessions={price_missing} "
                f"missing_fiscal_quarters={fiscal_gap_count} required_nulls={null_count} "
                f"eps_nulls={eps_null_count}"
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


def _fiscal_year_type(symbol: str) -> str:
    known_offsets = {
        "COST": "offset (Sep-Aug)",
        "MSFT": "offset (Jul-Jun)",
        "PG": "offset (Jul-Jun)",
        "AAPL": "offset (Oct-Sep)",
        "V": "offset (Oct-Sep)",
    }
    return known_offsets.get(symbol, "calendar (Jan-Dec)")


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
        close_to_close = by_day[announcement_day].close / by_day[entry_day].close - 1
        prior_close_day = entry_day
    elif timing == "post":
        announcement_day = on_or_after[0] if on_or_after else None
        entry_day = on_or_before[-1] if on_or_before else None
        if entry_day is None or announcement_day is None:
            return None
        next_days = [day for day in days if day > announcement_day]
        if not next_days:
            return None
        raw_gap = by_day[next_days[0]].open / by_day[announcement_day].close - 1
        close_to_close = by_day[next_days[0]].close / by_day[announcement_day].close - 1
        prior_close_day = announcement_day
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
        "close_to_close": close_to_close,
        "prior_close_day": prior_close_day,
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
    close_values = [float(record["close_to_close"]) for record in records]
    result["close_to_close"] = _returns_stats(close_values, 1)
    result["gap_sd"] = statistics.stdev(values) if len(values) > 1 else 0.0
    result["close_to_close_sd"] = (
        statistics.stdev(close_values) if len(close_values) > 1 else 0.0
    )
    return result


def _print_universe_stats(
    title: str,
    records: list[dict[str, Any]],
    symbols: Iterable[str],
) -> dict[str, dict[str, Any]]:
    print(f"=== {title} RAW EARNINGS BASE RATE (2018-PRESENT) ===")
    print(
        "symbol | events | positive_gap_rate | mean_gap | median_gap | gap_sd | "
        "close_to_close_mean | close_to_close_median | close_to_close_sd"
    )
    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        own = [record for record in records if record["event"].symbol == symbol]
        values = [record["raw_gap"] for record in own]
        row = {
            "events": len(values),
            "positive_gap_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "gap_expectancy": statistics.fmean(values) if values else None,
            "median_gap": statistics.median(values) if values else None,
            "gap_sd": statistics.stdev(values) if len(values) > 1 else 0.0,
            "close_to_close_mean": statistics.fmean(
                [record["close_to_close"] for record in own]
            ) if own else None,
            "close_to_close_median": statistics.median(
                [record["close_to_close"] for record in own]
            ) if own else None,
            "close_to_close_sd": statistics.stdev(
                [record["close_to_close"] for record in own]
            ) if len(own) > 1 else 0.0,
        }
        per_symbol[symbol] = row
        print(
            f"{symbol} | {row['events']} | {_fmt(row['positive_gap_rate'])} | "
            f"{_fmt(row['gap_expectancy'])} | {_fmt(row['median_gap'])} | "
            f"{_fmt(row['gap_sd'])} | {_fmt(row['close_to_close_mean'])} | "
            f"{_fmt(row['close_to_close_median'])} | {_fmt(row['close_to_close_sd'])}"
        )
    aggregate = _raw_stats(records)
    print(
        f"aggregate | {aggregate['trades']} | {_fmt(aggregate['positive_gap_rate'])} | "
        f"{_fmt(aggregate['expectancy'])} | — | {_fmt(aggregate['gap_sd'])} | "
        f"{_fmt(aggregate['close_to_close']['expectancy'])} | — | "
        f"{_fmt(aggregate['close_to_close_sd'])}"
    )
    return per_symbol


def _random_control(
    records: list[dict[str, Any]],
    mode: str,
    hold: int,
    close_exit: bool = False,
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
                    entry = record["by_day"][all_days[entry_index]].close
                    exit_bar = record["by_day"][all_days[entry_index + 1]]
                    exit_price = exit_bar.close if close_exit else exit_bar.open
                else:
                    if entry_index + hold - 1 >= len(all_days):
                        continue
                    entry = record["by_day"][all_days[entry_index]].open
                    exit_price = record["by_day"][all_days[entry_index + hold - 1]].close
                simulated.append(exit_price / entry - 1)
        distributions.append(statistics.fmean(simulated) if simulated else 0.0)
    distributions.sort()
    observed_returns = _strategy_returns(records, mode, hold, close_exit)
    observed = statistics.fmean(observed_returns) if observed_returns else None
    actual_sd = statistics.stdev(observed_returns) if len(observed_returns) > 1 else 0.0
    expected_spread = 3.29 * actual_sd / math.sqrt(max(1, len(observed_returns)))
    spread = distributions[int(0.95 * len(distributions)) - 1] - distributions[int(0.05 * len(distributions))]
    return {
        "iterations": CONTROL_ITERATIONS,
        "seed": RANDOM_SEED,
        "observed_expectancy": observed,
        "random_mean": statistics.fmean(distributions),
        "random_p05": distributions[int(0.05 * len(distributions))],
        "random_median": statistics.median(distributions),
        "random_p95": distributions[int(0.95 * len(distributions)) - 1],
        "random_std": statistics.pstdev(distributions),
        "actual_return_sd": actual_sd,
        "spread_p95_p05": spread,
        "expected_spread_from_actual_sd": expected_spread,
        "dispersion_sanity": (
            statistics.pstdev(distributions) > 0
            and spread >= max(0.001, expected_spread * 0.25)
        ),
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


def _window_records(records: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [
        record for record in records
        if start <= record["event"].reported_date <= end
    ]


def _near_52_week_high(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for record in records:
        days: list[date] = record["days"]
        by_day: dict[date, PriceBar] = record["by_day"]
        prior_day = record["prior_close_day"]
        prior_index = days.index(prior_day)
        trailing = [
            by_day[day].close
            for day in days[max(0, prior_index - 251):prior_index + 1]
        ]
        if trailing and by_day[prior_day].close >= 0.90 * max(trailing):
            filtered.append(record)
    return filtered


def _report_variant(
    label: str,
    records: list[dict[str, Any]],
    mode: str,
    hold: int,
    close_exit: bool,
) -> dict[str, Any]:
    values = _strategy_returns(records, mode, hold, close_exit)
    metrics = _returns_stats(values, hold)
    controls = _random_control(records, mode, hold, close_exit)
    print(
        f"strategy | {label} | trades={metrics['trades']} | "
        f"return={_fmt(metrics['total_return'])} | win_rate={_fmt(metrics['win_rate'])} | "
        f"expectancy={_fmt(metrics['expectancy'])} | sharpe={_fmt(metrics['sharpe'])} | "
        f"maxDD={_fmt(metrics['max_drawdown'])} | random_mean={_fmt(controls['random_mean'])} | "
        f"random_sd={_fmt(controls['random_std'])} | "
        f"random_P05_P95_spread={_fmt(controls['spread_p95_p05'])} | "
        f"actual_return_sd={_fmt(controls['actual_return_sd'])} | "
        f"dispersion_sanity={controls['dispersion_sanity']} | "
        f"beats_random={controls['beats_random_mean']}"
    )
    return {"metrics": metrics, "random_control": controls}


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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT experiment_id, results FROM research_ledger "
                "WHERE strategy_family=%s ORDER BY experiment_id DESC LIMIT 1",
                (STRATEGY_FAMILY,),
            )
            existing = cur.fetchone()
    if existing is not None:
        if existing[1] is not None:
            raise RuntimeError(
                f"research experiment already has immutable results: experiment_id={existing[0]}"
            )
        return int(existing[0])
    return register_experiment(
        strategy_family="bot2_earnings_universe_v2",
        bot_id=BOT_ID,
        hypothesis=(
            "Stocks selected for business predictability rather than past earnings "
            "performance show a positive and persistent post-earnings edge. PEAD "
            "(entering after a known positive surprise) outperforms entering before "
            "the report."
        ),
        parameters=parameters,
        pass_bar=pass_bar,
        data_window=data_window,
        variations_tested=2,
        went_live=False,
        notes="Development-only validation. No orders, live module, runner, or deployment changes permitted.",
    )


def run_validation(ingest: bool = True) -> dict[str, Any]:
    print_schema_statements()
    ensure_tables()
    # The experiment is registered before loading or computing any research
    # statistic.  Results are written only once, through record_results().
    experiment_id = _find_or_register_experiment()
    print(f"research_ledger | experiment_id={experiment_id} | registered_before_results=true")
    if ingest:
        print("=== DEVELOPMENT-ONLY INGEST ===")
        print(f"earnings_ingest | start={EARNINGS_START_DATE} | symbols={len(EARNINGS_SYMBOLS)}")
        ingest_earnings(EARNINGS_SYMBOLS, EARNINGS_START_DATE)
        print(f"price_ingest | start={EARNINGS_START_DATE} | symbols={len(EARNINGS_SYMBOLS)}")
        ingest_prices(EARNINGS_SYMBOLS, EARNINGS_START_DATE)
    prices, earnings = _load_data()
    integrity = _integrity_gate(prices, earnings)

    all_records = _event_records(earnings, prices, set(EARNINGS_SYMBOLS))
    old_records = [record for record in all_records if record["event"].symbol in LEGACY_STOCKS]
    new_records = [record for record in all_records if record["event"].symbol in VALIDATION_STOCKS]
    old_stats = _print_universe_stats("OLD UNIVERSE", old_records, LEGACY_STOCKS)
    new_stats = _print_universe_stats("NEW VALIDATION UNIVERSE", new_records, VALIDATION_STOCKS)

    selection_records = _window_records(new_records, SELECTION_START, SELECTION_END)
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

    selected_records = [record for record in new_records if record["event"].symbol in selected]
    windows = {
        "selection_2018_2022": _window_records(selected_records, SELECTION_START, SELECTION_END),
        "validation_2023_present": _window_records(selected_records, VALIDATION_START, VALIDATION_END),
        "pooled_2018_present": selected_records,
    }
    variants = [
        ("buy_before_open_exit", "buy_before", 1, False),
        ("buy_before_close_exit", "buy_before", 1, True),
        *[(f"positive_surprise_pead_{hold}", "pead", hold, True) for hold in PEAD_HOLDS],
    ]
    strategy_results: dict[str, Any] = {}
    for name, mode, hold, close_exit in variants:
        strategy_results[name] = {}
        for window_name, window in windows.items():
            strategy_results[name][window_name] = _report_variant(
                f"{window_name}|{name}", window, mode, hold, close_exit
            )

    filter_results: dict[str, Any] = {}
    for name, mode, hold, close_exit in variants[2:]:
        filter_results[name] = {}
        for window_name, window in windows.items():
            filtered = _near_52_week_high(window)
            filter_results[name][window_name] = _report_variant(
                f"{window_name}|{name}|52_week_high_filter",
                filtered,
                mode,
                hold,
                close_exit,
            )

    validation_records = windows["validation_2023_present"]
    validation_buy_hold = {
        symbol: _buy_hold(prices[symbol], VALIDATION_START, VALIDATION_END)
        for symbol in VALIDATION_STOCKS
    }
    spy_bars = fetch_yahoo_daily("SPY", VALIDATION_END + timedelta(days=1), EARNINGS_START_DATE)
    spy_prices = [PriceBar(row["date"], row["open"], row["close"]) for row in spy_bars]
    benchmarks = {
        "validation_stock_buy_and_hold": validation_buy_hold,
        "SPY_buy_and_hold": _buy_hold(spy_prices, VALIDATION_START, VALIDATION_END),
    }
    print(f"benchmark | SPY_buy_and_hold | return={_fmt(benchmarks['SPY_buy_and_hold']['return'])}")
    for symbol, result in validation_buy_hold.items():
        print(f"benchmark | {symbol}_buy_and_hold | return={_fmt(result['return'])}")

    primary = strategy_results["positive_surprise_pead_20"]["validation_2023_present"]
    primary_metrics = primary["metrics"]
    primary_control = primary["random_control"]
    buy_before_candidates = [
        strategy_results[name]["validation_2023_present"]["metrics"]["expectancy"]
        for name in ("buy_before_open_exit", "buy_before_close_exit")
        if strategy_results[name]["validation_2023_present"]["metrics"]["expectancy"] is not None
    ]
    pead_candidates = [
        strategy_results[f"positive_surprise_pead_{hold}"]["validation_2023_present"]["metrics"]["expectancy"]
        for hold in PEAD_HOLDS
        if strategy_results[f"positive_surprise_pead_{hold}"]["validation_2023_present"]["metrics"]["expectancy"] is not None
    ]
    better_strategy = "PEAD" if pead_candidates and (
        not buy_before_candidates or max(pead_candidates) > max(buy_before_candidates)
    ) else "buy-before"
    holds_out_of_sample = bool(
        primary_metrics["trades"]
        and primary_metrics["expectancy"] is not None
        and primary_metrics["expectancy"] > 0
    )
    pass_checks = {
        "sharpe": primary_metrics["sharpe"] is not None and primary_metrics["sharpe"] >= 0.60,
        "expectancy": primary_metrics["expectancy"] is not None and primary_metrics["expectancy"] >= 0.003,
        "beats_random": bool(primary_control["beats_random_mean"]),
        "holds_out_of_sample": holds_out_of_sample,
    }
    outcome = "PASS" if all(pass_checks.values()) else "FAIL"
    print(
        f"selection_holdout | top6_validation_positive_surprise_pead_20_expectancy="
        f"{_fmt(primary_metrics['expectancy'])} | holds_out_of_sample={holds_out_of_sample}"
    )
    print(f"strategy_comparison | better_on_validation_expectancy={better_strategy}")
    print(
        f"pass_bar | sharpe={pass_checks['sharpe']} | expectancy={pass_checks['expectancy']} | "
        f"beats_random={pass_checks['beats_random']} | holds_out_of_sample={pass_checks['holds_out_of_sample']}"
    )
    results = {
        "experiment_id": experiment_id,
        "integrity": integrity,
        "raw_stats": {"old": old_stats, "new": new_stats},
        "selection": {"ranking_2018_2022": ranking, "selected_top_6": selected},
        "validation": strategy_results,
        "52_week_high_filter": filter_results,
        "benchmarks": benchmarks,
        "pass_checks": pass_checks,
        "better_strategy_on_validation_expectancy": better_strategy,
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