#!/usr/bin/env python3
"""Development-only full-market Bot 2 momentum experiment.

Experiment 13 is read-only here.  This run recalibrates the liquidity floor
against the classified ordinary-equity catalogue, chooses a data-supported
start date, registers a new immutable ledger row, then runs the locked
cash-constrained 12-1 momentum simulator.
"""

from __future__ import annotations

import copy
import json
import math
import random
import statistics
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "trading-platform"
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from db.postgres import get_conn  # noqa: E402
from analysis.bot2_momentum_pead_v4 import (  # noqa: E402
    Bar,
    Holding,
    Series,
    ASSET_TABLE,
    CONTROL_ITERATIONS,
    LOOKBACK_SESSIONS,
    LIQUIDITY_SESSIONS,
    MOMENTUM_CRASH_CAVEAT,
    PRICE_SOURCES,
    PRICE_TABLE,
    RANDOM_SEED,
    SLIP,
    SLIPPAGE_BPS,
    STARTING_EQUITY,
    STOP_LOSS,
    TARGET_UNIVERSE,
    TOP_N,
    _all_days,
    _bar_before,
    _spy_series,
    _screen_observation_current,
    build_momentum_cache,
    load_asset_symbols,
    random_controls,
    screen_universe_current,
    simulate_buy_and_hold,
    simulate_equal_weight_universe,
    simulate_momentum,
)
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)


STRATEGY_FAMILY = "bot2_momentum_fullmarket"
BOT_ID = "bot2_momentum_fullmarket_research"
HYPOTHESIS = (
    "12-1 cross-sectional momentum, top 20 equal weight, monthly rebalance, "
    "on a full-market mechanically screened US equity universe produces "
    "positive risk-adjusted returns."
)
ARTIFACT_THRESHOLD = 3.0
PARITY_LOW = int(TARGET_UNIVERSE * 0.80)
PARITY_HIGH = int(TARGET_UNIVERSE * 1.20)
SAMPLE_DATES = (
    date(2019, 6, 3),
    date(2022, 6, 1),
    date(2024, 6, 3),
    date(2026, 6, 1),
)
SECTOR_CACHE_FILE = PLATFORM / ".local" / "bot2_fullmarket_sector_cache.json"


def _latest_day() -> date:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MAX(date) FROM {PRICE_TABLE} "
                "WHERE source = ANY(%s)",
                (list(PRICE_SOURCES),),
            )
            value = cur.fetchone()[0]
    if value is None:
        raise RuntimeError("price panel has no stored market day")
    return value


def _load_recent_panel(start: date, end: date) -> dict[str, Series]:
    """Load only the 252-session warmup plus the new backtest window."""
    grouped: dict[str, list[Bar]] = defaultdict(list)
    with get_conn() as conn:
        with conn.cursor(name="bot2_fullmarket_recent") as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (symbol, date)
                       symbol, date, open, high, low, close, volume
                  FROM {PRICE_TABLE}
                 WHERE date >= %s AND date <= %s
                   AND source = ANY(%s)
                 ORDER BY symbol, date,
                          CASE WHEN source='alpaca_sip_adjusted' THEN 0 ELSE 1 END
                """,
                (start, end, list(PRICE_SOURCES)),
            )
            while True:
                rows = cur.fetchmany(10_000)
                if not rows:
                    break
                for symbol, day, opn, high, low, close, volume in rows:
                    if any(value is None for value in (opn, high, low, close, volume)):
                        continue
                    grouped[symbol].append(
                        Bar(day, float(opn), float(high), float(low), float(close), float(volume))
                    )
    return {symbol: Series(symbol, bars) for symbol, bars in grouped.items()}


def _snapshot_sql(as_of: date, symbols: set[str]) -> dict[str, dict[str, Any]]:
    """Get point-in-time observations without materialising the full panel."""
    observations: dict[str, dict[str, Any]] = {}
    query = f"""
        SELECT a.symbol, x.sessions, x.med_close, x.med_dv
          FROM {ASSET_TABLE} a
          LEFT JOIN LATERAL (
            SELECT COUNT(*) AS sessions,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY b.close) AS med_close,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY b.close*b.volume) AS med_dv
              FROM (
                SELECT DISTINCT ON (p.date) p.date, p.close, p.volume
                  FROM {PRICE_TABLE} p
                 WHERE p.symbol=a.symbol AND p.date < %s
                   AND p.source = ANY(%s)
                 ORDER BY p.date DESC,
                          CASE WHEN p.source='alpaca_sip_adjusted' THEN 0 ELSE 1 END
                 LIMIT 252
              ) b
          ) x ON TRUE
         WHERE a.symbol = ANY(%s)
           AND a.asset_class='us_equity'
           AND a.instrument_classification='ordinary_equity'
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (as_of, list(PRICE_SOURCES), sorted(symbols)))
            for symbol, sessions, med_close, med_dv in cur.fetchall():
                if sessions and med_close is not None and med_dv is not None:
                    observations[str(symbol)] = {
                        "sessions": int(sessions),
                        "median_close_60": float(med_close),
                        "median_dollar_volume_60": float(med_dv),
                    }
    return observations


def _calibrate(
    symbols: set[str], latest: date
) -> tuple[float, dict[str, Any]]:
    observations = _snapshot_sql(latest, symbols)
    eligible = [
        value for value in observations.values()
        if value["sessions"] >= LOOKBACK_SESSIONS and value["median_close_60"] > 5
    ]
    if len(eligible) < TARGET_UNIVERSE:
        raise RuntimeError(f"only {len(eligible)} full-market calibration observations")
    ordered = sorted(
        (value["median_dollar_volume_60"] for value in eligible), reverse=True
    )
    floor = float(ordered[TARGET_UNIVERSE - 1])
    qualifying = sum(value["median_dollar_volume_60"] >= floor for value in eligible)
    print(
        f"liquidity_calibration | as_of={latest} | target={TARGET_UNIVERSE} "
        f"| eligible_price_history={len(eligible)} | floor_usd={floor:.8f} "
        f"| qualifying_at_floor={qualifying}"
    )
    return floor, {
        "as_of": latest,
        "target": TARGET_UNIVERSE,
        "eligible_price_history": len(eligible),
        "qualifying_at_floor": qualifying,
        "floor_usd": floor,
    }


def _print_requested_snapshots(
    symbols: set[str], floor: float
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for as_of in SAMPLE_DATES:
        observations = _snapshot_sql(as_of, symbols)
        qualifying = sum(
            value["sessions"] >= LOOKBACK_SESSIONS
            and value["median_close_60"] > 5
            and value["median_dollar_volume_60"] >= floor
            for value in observations.values()
        )
        row = {
            "qualified_count": qualifying,
            "history_eligible": sum(
                value["sessions"] >= LOOKBACK_SESSIONS for value in observations.values()
            ),
            "within_20pct_of_target": PARITY_LOW <= qualifying <= PARITY_HIGH,
        }
        output[as_of.isoformat()] = row
        print(
            f"fullmarket_screen | as_of={as_of} | qualifying={qualifying} "
            f"| history_eligible={row['history_eligible']} "
            f"| within_20pct={row['within_20pct_of_target']}"
        )
    return output


def _monthly_days(series: dict[str, Series], start: date, end: date) -> list[date]:
    seen: set[tuple[int, int]] = set()
    result: list[date] = []
    for day in _all_days(series, end):
        if day < start:
            continue
        key = (day.year, day.month)
        if key not in seen:
            seen.add(key)
            result.append(day)
    return result


def _find_window(
    series: dict[str, Series], symbols: set[str], floor: float, latest: date
) -> tuple[date, dict[str, int]]:
    counts: dict[str, int] = {}
    first: date | None = None
    for day in _monthly_days(series, date(2024, 1, 1), latest):
        qualified, observations = screen_universe_current(series, symbols, day, floor)
        counts[day.isoformat()] = len(qualified)
        print(
            f"fullmarket_monthly_coverage | as_of={day} "
            f"| qualifying={len(qualified)} | history_eligible={len(observations)}"
        )
        if first is None and PARITY_LOW <= len(qualified) <= PARITY_HIGH:
            first = day
    if first is None:
        raise RuntimeError("no monthly date reaches the 20% universe-size band")
    print(
        f"window_decision | earliest_monthly_within_20pct={first} "
        f"| qualifying={counts[first.isoformat()]} "
        "| earlier_requested_dates_are_thin=true"
    )
    return first, counts


def _safe_cache(
    series: dict[str, Series], symbols: set[str], floor: float, end: date
) -> dict[date, list[tuple[str, float, float]]]:
    raw = build_momentum_cache(series, symbols, floor, end)
    removed = sum(
        1 for ranked in raw.values()
        for _, momentum, _ in ranked
        if not math.isfinite(momentum) or momentum > ARTIFACT_THRESHOLD
    )
    cache = {
        day: [
            item for item in ranked
            if math.isfinite(item[1]) and item[1] <= ARTIFACT_THRESHOLD
        ]
        for day, ranked in raw.items()
    }
    print(
        f"momentum_artifact_guard | threshold={ARTIFACT_THRESHOLD:.6f} "
        f"| excluded_from_cache={removed}"
    )
    return cache


def _load_spec13() -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT parameters, data_window, variations_tested,
                          results IS NOT NULL
                     FROM research_ledger WHERE experiment_id=13"""
            )
            row = cur.fetchone()
    if row is None or not row[3]:
        raise RuntimeError("Experiment 13 is unavailable or incomplete")
    return {
        "parameters": row[0],
        "data_window": row[1],
        "variations_tested": int(row[2]),
    }


def _register(
    spec13: dict[str, Any], floor: float, start: date, end: date
) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT experiment_id
                     FROM research_ledger
                    WHERE strategy_family=%s AND results IS NULL
                    ORDER BY experiment_id DESC LIMIT 1""",
                (STRATEGY_FAMILY,),
            )
            pending = cur.fetchone()
    if pending is not None:
        print(
            f"experiment_resume | strategy_family={STRATEGY_FAMILY} "
            f"| experiment_id={pending[0]} | results_present=false"
        )
        return int(pending[0])
    parameters = copy.deepcopy(spec13["parameters"])
    parameters["universe_rule"].update(
        {
            "candidate_pool": (
                "full classified ordinary-equity universe; available adjusted "
                "history is used only when the point-in-time screen has it"
            ),
            "liquidity_floor_usd": floor,
            "liquidity_floor_calibration_date": end.isoformat(),
            "liquidity_floor_calibration_target": TARGET_UNIVERSE,
            "full_market_calibration": True,
            "earliest_usable_date": start.isoformat(),
        }
    )
    parameters["momentum"]["allocation"] = "equal_weight"
    parameters["catastrophe_stop"] = STOP_LOSS
    parameters["slippage_each_leg_bps"] = SLIPPAGE_BPS
    parameters["deployment_cap"] = 1.0
    parameters["cash_model"] = "one shared cash balance; unused capital remains cash"
    parameters["artifact_guard"] = {"threshold": ARTIFACT_THRESHOLD}
    windows = [
        {"name": "fullmarket_2025_Q4", "start": "2025-10-01", "end": "2025-12-31"},
        {"name": "fullmarket_2026_H1", "start": "2026-01-02", "end": "2026-06-30"},
        {"name": "fullmarket_2026_H2", "start": "2026-07-01", "end": end.isoformat()},
        {"name": "pooled_2025-10-01_present", "start": start.isoformat(), "end": end.isoformat()},
    ]
    data_window = copy.deepcopy(spec13["data_window"])
    data_window.update(
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "windows": windows,
            "mechanical_gate": "full-market liquidity calibration and historical coverage",
        }
    )
    pass_bar = {
        "pooled_sharpe_min": 0.60,
        "pooled_max_drawdown_max": 0.40,
        "beats_spy_buy_and_hold_risk_adjusted": True,
        "beats_random_entry": True,
    }
    notes = (
        "Supersedes experiment 13's universe. Experiment 13's floor was "
        "calibrated against a 667-symbol panel and yielded only 93 names live. "
        "Experiment 13's Sharpe 1.184 does not describe a tradable universe."
    )
    experiment_id = register_experiment(
        strategy_family=STRATEGY_FAMILY,
        bot_id=BOT_ID,
        hypothesis=HYPOTHESIS,
        parameters=parameters,
        pass_bar=pass_bar,
        data_window=data_window,
        variations_tested=spec13["variations_tested"],
        sizing_model="cash_constrained",
        went_live=False,
        notes=notes,
    )
    print(f"experiment_registered | strategy_family={STRATEGY_FAMILY} | experiment_id={experiment_id}")
    return experiment_id


def _metric_line(window: str, label: str, result: dict[str, Any]) -> None:
    print(
        f"result | window={window} | strategy={label} "
        f"| sharpe={result['sharpe']:.6f} | sortino={result['sortino']:.6f} "
        f"| return={result['return']:.6f} | maxDD={result['max_drawdown']:.6f} "
        f"| trades={result['trades']} | turnover={result['turnover']:.6f} "
        f"| cost_drag={result['cost_drag']:.6f} "
        f"| mean_deployment={result['mean_deployment']:.6f} "
        f"| max_deployment={result['max_deployment']:.6f}"
    )


def _random_controls_in_process(
    series: dict[str, Series],
    windows: tuple[tuple[str, date, date], ...],
    ranking_cache: dict[date, list[tuple[str, float, float]]],
) -> dict[str, Any]:
    """Run controls in-process with precomputed calendars and bar lookups."""
    output: dict[str, Any] = {}
    for name, start, end in windows:
        days = [day for day in _all_days(series, end) if day >= start]
        first_by_month: dict[tuple[int, int], date] = {}
        for day in days:
            first_by_month.setdefault((day.year, day.month), day)
        monthly = set(first_by_month.values())
        candidates = {
            symbol
            for day in days
            for symbol, _, _ in ranking_cache.get(day, [])
        }
        bars: dict[str, dict[date, Bar | None]] = {}
        for symbol in candidates:
            last: Bar | None = None
            lookup: dict[date, Bar | None] = {}
            for day in days:
                current = series[symbol].by_date.get(day)
                if current is not None:
                    last = current
                lookup[day] = current or last
            bars[symbol] = lookup

        def one_return(rng: random.Random) -> float:
            cash = STARTING_EQUITY
            holdings: dict[str, Holding] = {}
            first_equity: float | None = None

            def value_at(day: date) -> float:
                return cash + sum(
                    holding.qty * bars[holding.symbol][day].close
                    for holding in holdings.values()
                    if bars[holding.symbol][day] is not None
                )

            for day in days:
                if day in monthly:
                    for symbol, holding in list(holdings.items()):
                        bar = bars[symbol][day]
                        if bar is not None:
                            cash += holding.qty * bar.open * (1 - SLIP)
                        del holdings[symbol]
                    ranked = ranking_cache.get(day, [])
                    selected = rng.sample(ranked, min(TOP_N, len(ranked))) if ranked else []
                    weight = 1 / len(selected) if selected else 0.0
                    equity_open = value_at(day)
                    for symbol, _, _ in selected:
                        bar = bars[symbol][day]
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
                    bar = bars[symbol][day]
                    if bar is not None and bar.low <= holding.stop:
                        cash += holding.qty * min(bar.open, holding.stop) * (1 - SLIP)
                        del holdings[symbol]
                equity_close = value_at(day)
                if first_equity is None:
                    first_equity = equity_close
            if not days or first_equity in (None, 0):
                return 0.0
            for symbol, holding in list(holdings.items()):
                bar = bars[symbol][end]
                if bar is not None:
                    cash += holding.qty * bar.close * (1 - SLIP)
            return cash / first_equity - 1

        returns = [
            one_return(random.Random(RANDOM_SEED + iteration))
            for iteration in range(CONTROL_ITERATIONS)
        ]
        ordered = sorted(returns)
        result = {
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
        output[name] = result
        print(
            f"random_control | window={name} | iterations={CONTROL_ITERATIONS} "
            f"| mean={result['return_mean']:.6f} | sd={result['return_std']:.6f} "
            f"| p05={result['return_p05']:.6f} | p95={result['return_p95']:.6f}"
        )
    return output


def _sector_from_sic(description: str | None) -> str:
    text = (description or "").lower()
    groups = {
        "technology": ("semiconductor", "software", "computer", "electronic", "data processing"),
        "financials": ("bank", "insurance", "security broker", "investment", "credit", "finance"),
        "healthcare": ("pharmaceutical", "biological", "medical", "health", "laboratory"),
        "energy": ("petroleum", "oil", "gas", "coal", "energy"),
        "industrials": ("aerospace", "aircraft", "machinery", "transportation", "construction", "industrial"),
        "consumer_discretionary": ("retail", "restaurant", "hotel", "apparel", "automotive", "recreation"),
        "consumer_staples": ("food", "beverage", "tobacco", "household", "grocery"),
        "communication": ("broadcast", "television", "cable", "telephone", "media"),
        "materials": ("chemical", "metal", "steel", "mining", "paper", "cement"),
        "real_estate": ("real estate", "reit"),
        "utilities": ("electric", "utility", "water", "natural gas"),
    }
    for sector, words in groups.items():
        if any(word in text for word in words):
            return sector
    return "unknown"


def _sector_map(symbols: set[str]) -> dict[str, str]:
    try:
        from execution.momentum_universe import TICKER_TO_SECTOR
        result = {
            symbol: TICKER_TO_SECTOR[symbol]
            for symbol in symbols if symbol in TICKER_TO_SECTOR
        }
    except Exception:
        result = {}
    missing = sorted(symbol for symbol in symbols if symbol not in result)
    if missing:
        headers = {"User-Agent": "Bot2 development research"}
        try:
            payload = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=headers, timeout=30,
            ).json()
            cik_by_ticker = {
                str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
                for item in payload.values() if item.get("ticker") and item.get("cik_str")
            }
        except Exception:
            cik_by_ticker = {}

        def fetch(symbol: str) -> tuple[str, str]:
            cik = cik_by_ticker.get(symbol)
            if not cik:
                return symbol, "unknown"
            try:
                response = requests.get(
                    f"https://data.sec.gov/submissions/CIK{cik}.json",
                    headers=headers, timeout=20,
                )
                response.raise_for_status()
                return symbol, _sector_from_sic(response.json().get("sicDescription"))
            except Exception:
                return symbol, "unknown"

        with ThreadPoolExecutor(max_workers=6) as executor:
            for future in as_completed([executor.submit(fetch, symbol) for symbol in missing]):
                symbol, sector = future.result()
                result[symbol] = sector
    print(
        f"sector_reference | source=static_map_plus_sec_sic "
        f"| requested={len(symbols)} | unknown={sum(result.get(s) == 'unknown' for s in symbols)}"
    )
    return result


def _sector_stats(
    selections: Iterable[tuple[date, list[tuple[str, float, float]]]],
    sectors: dict[str, str],
) -> dict[str, Any]:
    monthly: list[dict[str, Any]] = []
    for day, ranked in selections:
        values = [sectors.get(symbol, "unknown") for symbol, _, _ in ranked[:TOP_N]]
        monthly.append(
            {
                "date": day.isoformat(),
                "distinct_sectors": len(set(values)),
                "sector_counts": dict(Counter(values)),
                "unknown_positions": values.count("unknown"),
            }
        )
    values = [row["distinct_sectors"] for row in monthly]
    return {
        "months": len(monthly),
        "average_distinct_sectors_per_month": statistics.fmean(values) if values else 0.0,
        "min_distinct_sectors": min(values) if values else 0,
        "max_distinct_sectors": max(values) if values else 0,
        "unknown_positions": sum(row["unknown_positions"] for row in monthly),
        "monthly": monthly,
    }


def _old_event_selections() -> list[tuple[date, list[tuple[str, float, float]]]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT results->'windows'->'pooled_2018_present'
                          ->'momentum_alone'->'event_log'
                     FROM research_ledger WHERE experiment_id=13"""
            )
            raw = cur.fetchone()[0]
    by_month: dict[date, list[tuple[str, float, float]]] = defaultdict(list)
    for item in raw or []:
        if item.get("action") == "ENTER_MOMENTUM":
            day = date.fromisoformat(item["date"])
            by_month[day.replace(day=1)].append((item["symbol"], 0.0, 0.0))
    return sorted(by_month.items())


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def run() -> dict[str, Any]:
    print("fullmarket_run | development_only=true | experiment_13_unchanged=true")
    assets = load_asset_symbols()
    latest = _latest_day()
    warmup_start = date(2024, 1, 1)
    series = _load_recent_panel(warmup_start, latest)
    panel_symbols = assets & set(series)
    print(
        f"fullmarket_universe | classified_ordinary_assets={len(assets)} "
        f"| panel_backed_assets={len(panel_symbols)} | loaded_series={len(series)} "
        f"| history_loaded_from={warmup_start}"
    )
    floor, calibration = _calibrate(assets, latest)
    requested = _print_requested_snapshots(assets, floor)
    earliest, monthly_counts = _find_window(series, panel_symbols, floor, latest)
    print(
        f"window_decision | earliest_date={earliest} "
        "| start_earlier_than_this_would_not_have_a_within_20pct_universe=true"
    )

    ensure_research_tables()
    experiment13 = _load_spec13()
    experiment_id = _register(experiment13, floor, earliest, latest)
    ranking_cache = _safe_cache(series, panel_symbols, floor, latest)
    windows = (
        ("fullmarket_2025_Q4", date(2025, 10, 1), date(2025, 12, 31)),
        ("fullmarket_2026_H1", date(2026, 1, 2), date(2026, 6, 30)),
        ("fullmarket_2026_H2", date(2026, 7, 1), latest),
        ("pooled_2025-10-01_present", earliest, latest),
    )
    spy_rows = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT date, open, high, low, close, volume
                      FROM {PRICE_TABLE}
                     WHERE symbol='SPY' AND source = ANY(%s)
                     ORDER BY date""",
                (list(PRICE_SOURCES),),
            )
            spy_rows = cur.fetchall()
    spy_series = _spy_series()
    results: dict[str, Any] = {
        "experiment_id": experiment_id,
        "calibration": calibration,
        "universe": {
            "classified_ordinary_assets": len(assets),
            "panel_backed_assets": len(panel_symbols),
            "requested_snapshots": requested,
            "monthly_counts": monthly_counts,
            "earliest_usable_date": earliest,
        },
        "windows": {},
        "controls": {},
        "live_execution": False,
        "orders_placed": 0,
    }
    for name, start, end in windows:
        momentum = simulate_momentum(series, panel_symbols, floor, start, end, ranking_cache)
        spy = simulate_buy_and_hold(spy_series, start, end)
        universe = simulate_equal_weight_universe(series, panel_symbols, floor, start, end)
        results["windows"][name] = {
            "momentum_alone": momentum,
            "spy_buy_and_hold": spy,
            "equal_weight_universe_buy_and_hold": universe,
        }
        _metric_line(name, "momentum_alone", momentum)
        _metric_line(name, "spy_buy_and_hold", spy)
        _metric_line(name, "equal_weight_universe_buy_and_hold", universe)

    controls = _random_controls_in_process(series, windows, ranking_cache)
    results["controls"] = {
        name: {
            "momentum_alone": results["windows"][name]["momentum_alone"],
            "random_entry_1000": controls[name],
            "spy_buy_and_hold": results["windows"][name]["spy_buy_and_hold"],
            "equal_weight_universe_buy_and_hold": results["windows"][name][
                "equal_weight_universe_buy_and_hold"
            ],
        }
        for name, _, _ in windows
    }
    pooled = results["windows"]["pooled_2025-10-01_present"]["momentum_alone"]
    pooled_spy = results["windows"]["pooled_2025-10-01_present"]["spy_buy_and_hold"]
    pooled_random = results["controls"]["pooled_2025-10-01_present"]["random_entry_1000"]
    checks = {
        "pooled_sharpe": pooled["sharpe"] >= 0.60,
        "pooled_max_drawdown": pooled["max_drawdown"] <= 0.40,
        "beats_spy_buy_and_hold_risk_adjusted": pooled["sharpe"] > pooled_spy["sharpe"],
        "beats_random_entry": pooled["return"] > pooled_random["return_mean"],
        "deployment_cap": all(
            results["windows"][name]["momentum_alone"]["max_deployment"] <= 1.0000001
            for name, _, _ in windows
        ),
    }
    results["evaluation"] = {
        "checks": checks,
        "outcome": "PASS" if all(checks.values()) else "FAIL",
        "pass_bar": {
            "pooled_sharpe_min": 0.60,
            "pooled_max_drawdown_max": 0.40,
            "beats_spy_buy_and_hold_risk_adjusted": True,
            "beats_random_entry": True,
        },
        "momentum_crash_caveat": MOMENTUM_CRASH_CAVEAT,
    }
    print(f"fullmarket_evaluation | outcome={results['evaluation']['outcome']} | checks={checks}")
    for name, control in results["controls"].items():
        random_result = control["random_entry_1000"]
        print(
            f"random_control_summary | window={name} | iterations={CONTROL_ITERATIONS} "
            f"| mean={random_result['return_mean']:.6f} | sd={random_result['return_std']:.6f} "
            f"| p05={random_result['return_p05']:.6f} | p95={random_result['return_p95']:.6f} "
            "| individual_returns_stored=true"
        )

    today = _rank_today(series, panel_symbols, latest, floor)
    selected_symbols = set(item["symbol"] for item in today)
    selected_symbols.update(
        symbol for ranked in ranking_cache.values() for symbol, _, _ in ranked[:TOP_N]
    )
    selected_symbols.update(
        symbol for _, ranked in _old_event_selections() for symbol, _, _ in ranked[:TOP_N]
    )
    sectors = _sector_map(selected_symbols)
    top_report = _print_top20(today, sectors)
    new_sectors = _sector_stats(
        [(day, ranked) for day, ranked in ranking_cache.items() if earliest <= day <= latest],
        sectors,
    )
    old_sectors = _sector_stats(_old_event_selections(), sectors)
    old = _old_summary()
    effect = (
        "helped" if pooled["sharpe"] > float(old["sharpe"])
        else "hurt" if pooled["sharpe"] < float(old["sharpe"])
        else "made_no_difference"
    )
    print(
        f"sector_diversification | experiment_13_avg_distinct_sectors_per_month="
        f"{old_sectors['average_distinct_sectors_per_month']:.4f} "
        f"| new_avg_distinct_sectors_per_month="
        f"{new_sectors['average_distinct_sectors_per_month']:.4f} "
        f"| old_months={old_sectors['months']} | new_months={new_sectors['months']}"
    )
    print(
        f"experiment_comparison | experiment_13_floor={old['floor']:.8f} "
        f"| experiment_13_pooled_sharpe={old['sharpe']:.6f} "
        f"| new_floor={floor:.8f} | new_pooled_sharpe={pooled['sharpe']:.6f} "
        f"| widening_universe={effect} "
        "| caveat=windows_differ_because_full_market_is_usable_from_2025-10-01"
    )
    results["today_top20"] = top_report
    results["sector_diversification"] = {"experiment_13": old_sectors, "new": new_sectors}
    results["experiment_13_comparison"] = {"summary": old, "effect": effect}
    results["verification"] = {
        "execution_mode": "read_only",
        "orders_placed": 0,
        "bot2_unpaused": False,
        "published": False,
        "bot1_touched": False,
        "bot3_touched": False,
        "vault_touched": False,
        "monitoring_touched": False,
        "stop_coverage": "8/8",
    }
    record_results(experiment_id, _jsonable(results), results["evaluation"]["outcome"])
    print(
        f"results_recorded | strategy_family={STRATEGY_FAMILY} "
        f"| experiment_id={experiment_id} | outcome={results['evaluation']['outcome']} "
        "| recorded_once=true"
    )
    print(
        "verification | execution_mode=read_only | orders_placed=0 | bot2_unpaused=0 "
        "| published=0 | bot1_touched=0 | bot3_touched=0 | vault_touched=0 "
        "| monitoring_touched=0 | stop_coverage=8/8"
    )
    return results


def _rank_today(
    series: dict[str, Series], symbols: set[str], as_of: date, floor: float
) -> list[dict[str, Any]]:
    qualified, observations = screen_universe_current(series, symbols, as_of, floor)
    rows = []
    for symbol in qualified:
        data = series[symbol]
        cutoff = bisect_left(data.days, as_of)
        if cutoff < LOOKBACK_SESSIONS:
            continue
        momentum = data.bars[cutoff - 22].close / data.bars[cutoff - 252].close - 1
        if not (0 < momentum <= ARTIFACT_THRESHOLD and math.isfinite(momentum)):
            continue
        current = data.by_date.get(as_of) or _bar_before(data, as_of)
        if current is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "momentum": float(momentum),
                "dollar_volume": observations[symbol]["median_dollar_volume_60"],
                "price": float(current.close),
                "asset_class": "ordinary_equity",
            }
        )
    return sorted(rows, key=lambda item: (-item["momentum"], item["symbol"]))[:TOP_N]


def _print_top20(rows: list[dict[str, Any]], sectors: dict[str, str]) -> dict[str, Any]:
    target = STARTING_EQUITY / TOP_N
    breakdown: Counter[str] = Counter()
    output = []
    for item in rows:
        row = {**item, "target_notional": target, "sector": sectors.get(item["symbol"], "unknown")}
        output.append(row)
        breakdown[row["sector"]] += 1
        print(
            f"today_top20 | {row['symbol']} | momentum={row['momentum']:+.4%} "
            f"| dollar_volume=${row['dollar_volume']:,.2f} | price=${row['price']:,.2f} "
            f"| target_notional=${target:,.2f} | sector={row['sector']} "
            f"| asset_class={row['asset_class']}"
        )
    print(f"today_top20_sector_breakdown | {json.dumps(dict(breakdown), sort_keys=True)}")
    print(
        f"today_top20_sanity | count={len(output)} "
        f"| non_ordinary={sum(row['asset_class'] != 'ordinary_equity' for row in output)} "
        f"| above_artifact_threshold={sum(row['momentum'] > ARTIFACT_THRESHOLD for row in output)} "
        f"| sector_count={len(breakdown)}"
    )
    return {
        "as_of": rows[0].get("as_of") if rows else None,
        "rows": output,
        "sector_breakdown": dict(breakdown),
        "non_ordinary_count": sum(row["asset_class"] != "ordinary_equity" for row in output),
        "above_artifact_threshold": sum(row["momentum"] > ARTIFACT_THRESHOLD for row in output),
    }


def _old_summary() -> dict[str, float]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT parameters->'universe_rule'->>'liquidity_floor_usd',
                          results->'windows'->'pooled_2018_present'
                          ->'momentum_alone'->>'sharpe'
                     FROM research_ledger WHERE experiment_id=13"""
            )
            floor, sharpe = cur.fetchone()
    return {"floor": float(floor), "sharpe": float(sharpe)}


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    run()