#!/usr/bin/env python3
"""Development-only mechanical-universe research for Bot 2 v3.

The candidate universe is the union of Alpaca's currently tradable US-equity
symbols and the retained historical price panel.  Membership is never inferred
from a constituent list: a symbol qualifies on a rebalance date only when its
own observations strictly before that date contain 252 sessions, a trailing
60-session median close above $5, and a locked liquidity floor.

This module has no live-strategy or order-placement imports.  Its only database
writes are the asset-list audit and the single immutable research-ledger result
record after all data gates pass.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import sys
import time
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import psycopg2.extras
import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402

from analysis.bot2_data_pipeline import EARNINGS_SYMBOLS, EARNINGS_TABLE  # noqa: E402
from analysis.bot2_sp500_data import (  # noqa: E402
    ALPACA_BARS_URL,
    PRICE_TABLE,
    PRICE_SOURCES,
    _fetch_feed,
)
from analysis.research_ledger import (  # noqa: E402
    ensure_research_tables,
    record_results,
    register_experiment,
)


ANALYSIS_START = date(2018, 1, 1)
ANALYSIS_END = date.today() - timedelta(days=1)
UNIVERSE_GATE_FILE = (
    Path(__file__).resolve().parents[1] / ".local" / "bot2_universe_gate.json"
)
CALIBRATION_DATE = date(2019, 6, 3)
LOOKBACK_SESSIONS = 252
LIQUIDITY_SESSIONS = 60
LOCKED_LIQUIDITY_FLOOR = 62_406_698.54
MAX_ADJUSTED_CLOSE_RATIO = 10.0
TARGET_UNIVERSE = 500
TOP_N = 20
SLIPPAGE_BPS = 10.0
STOP_LOSS = 0.20
STARTING_EQUITY = 100_000.0
CONTROL_ITERATIONS = 1_000
RANDOM_SEED = 271_2026
PEAD_SYMBOLS = EARNINGS_SYMBOLS
SAMPLE_DATES = (
    date(2019, 6, 3),
    date(2022, 6, 1),
    date(2024, 6, 3),
    date(2026, 6, 1),
)
PARITY_REFERENCE_COUNTS = {
    date(2019, 6, 3): 500,
    date(2022, 6, 1): 575,
    date(2024, 6, 3): 571,
    date(2026, 6, 1): 603,
}
WINDOWS: tuple[tuple[str, date, date], ...] = (
    ("selection_2018_2022", date(2018, 1, 1), date(2022, 12, 30)),
    ("validation_2023_present", date(2023, 1, 3), ANALYSIS_END),
    ("pooled_2018_present", date(2018, 1, 1), ANALYSIS_END),
)

ASSET_TABLE = "bot2_mechanical_assets"
ASSET_AUDIT_TABLE = "bot2_mechanical_asset_audit"
ASSET_COVERAGE_TABLE = "bot2_mechanical_asset_coverage"
MOMENTUM_ARTEFACT_THRESHOLD = 3.0
ORDINARY_SHARE_NAME_PATTERNS = (
    re.compile(r"\bcommon stock\b", re.IGNORECASE),
    re.compile(r"\bcommon shares?\b", re.IGNORECASE),
    re.compile(r"\bordinary shares?\b", re.IGNORECASE),
    re.compile(r"\bamerican depositary shares?\b", re.IGNORECASE),
)
ASSET_DDL = f"""
CREATE TABLE IF NOT EXISTS {ASSET_TABLE} (
    symbol       TEXT PRIMARY KEY,
    asset_class  TEXT NOT NULL,
    status       TEXT NOT NULL,
    exchange     TEXT,
    tradable     BOOLEAN NOT NULL,
    fractionable BOOLEAN,
    name         TEXT,
    instrument_classification TEXT NOT NULL DEFAULT 'unknown',
    source       TEXT NOT NULL DEFAULT 'alpaca_trading_assets',
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE {ASSET_TABLE} ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE {ASSET_TABLE}
    ADD COLUMN IF NOT EXISTS instrument_classification TEXT NOT NULL DEFAULT 'unknown';
CREATE TABLE IF NOT EXISTS {ASSET_AUDIT_TABLE} (
    symbol       TEXT PRIMARY KEY,
    asset_class  TEXT NOT NULL,
    status       TEXT NOT NULL,
    exchange     TEXT,
    tradable     BOOLEAN NOT NULL,
    name         TEXT,
    instrument_classification TEXT NOT NULL,
    included     BOOLEAN NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS {ASSET_COVERAGE_TABLE} (
    symbol       TEXT PRIMARY KEY,
    row_count    INTEGER NOT NULL,
    first_date   DATE,
    last_date    DATE,
    category     TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Series:
    symbol: str
    bars: list[Bar]

    def __post_init__(self) -> None:
        self.bars.sort(key=lambda bar: bar.day)
        self.by_date = {bar.day: bar for bar in self.bars}
        self.days = [bar.day for bar in self.bars]


@dataclass(frozen=True)
class Asset:
    symbol: str
    asset_class: str
    status: str
    exchange: str
    tradable: bool
    fractionable: bool | None
    name: str = ""
    instrument_classification: str = "unknown"


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def classify_alpaca_asset(raw: Any) -> str:
    """Use provider metadata, with a conservative positive ordinary-share test."""
    explicit = _enum_value(
        getattr(raw, "instrument_type", None)
        or getattr(raw, "security_type", None)
        or getattr(raw, "asset_type", None)
    ).lower()
    if explicit in {"common_stock", "ordinary_share", "stock", "equity"}:
        return "ordinary_equity"
    if explicit in {
        "etf", "etn", "fund", "mutual_fund", "preferred", "warrant",
        "right", "unit", "closed_end_fund",
    }:
        return "non_ordinary"
    name = _enum_value(getattr(raw, "name", ""))
    if name and any(pattern.search(name) for pattern in ORDINARY_SHARE_NAME_PATTERNS):
        return "ordinary_equity"
    return "unknown"


LAST_ASSET_FILTER_REPORT: dict[str, Any] = {}


def fetch_tradable_us_equities() -> list[Asset]:
    """Read the Alpaca asset catalogue; this never calls an order endpoint."""
    global LAST_ASSET_FILTER_REPORT
    from alpaca.trading.client import TradingClient

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError("ALPACA_API_KEY/ALPACA_SECRET_KEY are required for asset discovery")
    client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
    raw_assets = list(client.get_all_assets())
    output: list[Asset] = []
    included = 0
    non_ordinary = 0
    unknown = 0
    us_equities = 0
    for raw in raw_assets:
        asset_class = _enum_value(getattr(raw, "asset_class", ""))
        if asset_class != "us_equity":
            continue
        us_equities += 1
        classification = classify_alpaca_asset(raw)
        if classification == "non_ordinary":
            non_ordinary += 1
        elif classification == "unknown":
            unknown += 1
        symbol = str(getattr(raw, "symbol", "")).strip().upper()
        if not symbol or classification != "ordinary_equity":
            continue
        included += 1
        output.append(
            Asset(
                symbol=symbol,
                asset_class=asset_class,
                status=_enum_value(getattr(raw, "status", "")),
                exchange=_enum_value(getattr(raw, "exchange", "")),
                tradable=bool(getattr(raw, "tradable", False)),
                fractionable=(
                    bool(getattr(raw, "fractionable"))
                    if getattr(raw, "fractionable", None) is not None
                    else None
                ),
                name=_enum_value(getattr(raw, "name", "")),
                instrument_classification=classification,
            )
        )
    LAST_ASSET_FILTER_REPORT = {
        "total_assets": len(raw_assets),
        "alpaca_us_equity_assets": us_equities,
        "ordinary_equity_assets": included,
        "excluded_non_ordinary": non_ordinary,
        "excluded_unknown_metadata": unknown,
        "metadata_complete": unknown == 0,
        "provider_limitation": (
            "Alpaca exposes descriptive names but no dedicated security-type "
            "field; unknown instruments are excluded until Polygon/Massive "
            "reference tickers or a licensed security master supplies a type."
            if unknown else None
        ),
    }
    print(
        f"asset_filter | total={len(raw_assets)} | us_equity={us_equities} "
        f"| ordinary_equity={included} | excluded_non_ordinary={non_ordinary} "
        f"| excluded_unknown={unknown}"
    )
    if unknown:
        print(f"asset_filter | LIMITATION | {LAST_ASSET_FILTER_REPORT['provider_limitation']}")
    return sorted({asset.symbol: asset for asset in output}.values(), key=lambda item: item.symbol)


def ensure_asset_table() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ASSET_DDL)


def persist_assets(assets: Iterable[Asset]) -> None:
    rows = [
        (
            asset.symbol,
            asset.asset_class,
            asset.status,
            asset.exchange,
            asset.tradable,
            asset.fractionable,
            asset.name,
            asset.instrument_classification,
        )
        for asset in assets
    ]
    ensure_asset_table()
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"""
                INSERT INTO {ASSET_TABLE}
                    (symbol, asset_class, status, exchange, tradable, fractionable,
                     name, instrument_classification)
                VALUES %s
                ON CONFLICT (symbol) DO UPDATE SET
                    asset_class=EXCLUDED.asset_class,
                    status=EXCLUDED.status,
                    exchange=EXCLUDED.exchange,
                    tradable=EXCLUDED.tradable,
                    fractionable=EXCLUDED.fractionable,
                    name=EXCLUDED.name,
                    instrument_classification=EXCLUDED.instrument_classification,
                    observed_at=NOW()
                """,
                rows,
            )


def load_panel() -> dict[str, Series]:
    """Load one adjusted bar per symbol/day, preferring SIP over IEX."""
    grouped: dict[str, list[Bar]] = defaultdict(list)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (symbol, date)
                       symbol, date, open, high, low, close, volume
                  FROM {PRICE_TABLE}
                 WHERE source = ANY(%s)
                 ORDER BY symbol, date,
                          CASE WHEN source = 'alpaca_sip_adjusted' THEN 0 ELSE 1 END
                """,
                (list(PRICE_SOURCES),),
            )
            for symbol, day, opn, high, low, close, volume in cur.fetchall():
                values = (opn, high, low, close, volume)
                if any(value is None for value in values):
                    continue
                grouped[symbol].append(
                    Bar(day, float(opn), float(high), float(low), float(close), float(volume))
                )
    return {symbol: Series(symbol, bars) for symbol, bars in grouped.items()}


def load_asset_symbols() -> set[str]:
    ensure_asset_table()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT symbol FROM {ASSET_TABLE} "
                "WHERE asset_class='us_equity' "
                "AND instrument_classification='ordinary_equity'"
            )
            return {row[0] for row in cur.fetchall()}


def coverage_report(candidate_symbols: Iterable[str]) -> dict[str, Any]:
    """Report stored per-symbol history coverage without fetching new data."""
    symbols = set(candidate_symbols)
    coverage_rows: dict[str, tuple[int, date | None, date | None, int]] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, COUNT(*), MIN(date), MAX(date), COUNT(DISTINCT source)
                  FROM {PRICE_TABLE}
                 WHERE symbol = ANY(%s) AND source = ANY(%s)
                 GROUP BY symbol
                """,
                (sorted(symbols), list(PRICE_SOURCES)),
            )
            coverage_rows = {
                str(symbol): (int(row_count), first_date, last_date, int(source_count))
                for symbol, row_count, first_date, last_date, source_count in cur.fetchall()
            }
            persisted_rows = []
            for symbol in sorted(symbols):
                row_count, first_date, last_date, source_count = coverage_rows.get(
                    symbol, (0, None, None, 0)
                )
                category = (
                    "no_price_data"
                    if row_count == 0
                    else "partial_history"
                    if row_count < LOOKBACK_SESSIONS
                    else "history_eligible"
                )
                persisted_rows.append(
                    (symbol, row_count, first_date, last_date, category, source_count)
                )
            if persisted_rows:
                psycopg2.extras.execute_values(
                    cur,
                    f"""
                    INSERT INTO {ASSET_COVERAGE_TABLE}
                        (symbol, row_count, first_date, last_date, category, source_count)
                    VALUES %s
                    ON CONFLICT (symbol) DO UPDATE SET
                        row_count=EXCLUDED.row_count,
                        first_date=EXCLUDED.first_date,
                        last_date=EXCLUDED.last_date,
                        category=EXCLUDED.category,
                        source_count=EXCLUDED.source_count,
                        observed_at=NOW()
                    """,
                    persisted_rows,
                )
    counts = {symbol: row[0] for symbol, row in coverage_rows.items()}
    complete = sorted(symbol for symbol in symbols if counts.get(symbol, 0) >= LOOKBACK_SESSIONS)
    partial = sorted(symbol for symbol in symbols if 0 < counts.get(symbol, 0) < LOOKBACK_SESSIONS)
    none = sorted(symbol for symbol in symbols if counts.get(symbol, 0) == 0)
    report = {
        "total_symbols": len(symbols),
        "symbols_with_at_least_252_sessions": len(complete),
        "symbols_with_partial_history": len(partial),
        "symbols_with_no_history": len(none),
        "complete_examples": complete[:20],
        "partial_examples": partial[:20],
        "none_examples": none[:20],
    }
    print(
        f"history_coverage | total={report['total_symbols']} "
        f"| >=252={report['symbols_with_at_least_252_sessions']} "
        f"| partial={report['symbols_with_partial_history']} "
        f"| none={report['symbols_with_no_history']}"
    )
    return report


def ingest_expanded_prices(
    assets: Iterable[Asset],
    start: date = ANALYSIS_START,
    end: date = ANALYSIS_END,
    batch_size: int = 100,
) -> dict[str, int]:
    """Optional batch ingestion for newly discovered assets.

    The default research run intentionally does not issue thousands of history
    requests.  This explicit opt-in uses only the Alpaca market-data endpoint
    and writes to the already isolated Bot 2 price panel.
    """
    symbols = sorted({asset.symbol for asset in assets})
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError("Alpaca credentials are required for expanded price ingestion")
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
    counts = {
        "batches": 0,
        "bars": 0,
        "failed_batches": 0,
        "quarantined_symbols": 0,
        "rate_limit_retries": 0,
        "split_batches": 0,
    }

    def fetch_rows(batch: list[str], label: str) -> list[tuple[Any, ...]]:
        """Fetch a batch, splitting 400 responses so one bad symbol cannot poison it."""
        params = {
            "symbols": ",".join(batch),
            "timeframe": "1Day",
            "start": f"{start.isoformat()}T00:00:00Z",
            "end": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            "adjustment": "all",
            "feed": "sip",
            "limit": 10_000,
        }
        rows: list[tuple[Any, ...]] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            try:
                for attempt in range(6):
                    response = requests.get(
                        ALPACA_BARS_URL, headers=headers, params=params, timeout=90
                    )
                    if response.status_code != 429:
                        response.raise_for_status()
                        break
                    if attempt == 5:
                        response.raise_for_status()
                    wait_seconds = min(32, 2 ** attempt)
                    counts["rate_limit_retries"] += 1
                    print(f"expanded_price_rate_limit | batch={label} | retry_in={wait_seconds}s")
                    time.sleep(wait_seconds)
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status == 400 and len(batch) > 1:
                    counts["split_batches"] += 1
                    midpoint = len(batch) // 2
                    return (
                        fetch_rows(batch[:midpoint], f"{label}a")
                        + fetch_rows(batch[midpoint:], f"{label}b")
                    )
                if status == 400 and len(batch) == 1:
                    counts["quarantined_symbols"] += 1
                    print(
                        f"expanded_price_symbol | symbol={batch[0]} "
                        "| ERROR=HTTP 400 | action=quarantined"
                    )
                    return []
                raise
            payload = response.json()
            for symbol, raw_bars in (payload.get("bars") or {}).items():
                for raw in raw_bars or []:
                    rows.append(
                        (
                            symbol,
                            str(raw["t"])[:10],
                            float(raw["o"]),
                            float(raw["h"]),
                            float(raw["l"]),
                            float(raw["c"]),
                            float(raw["v"]),
                            "alpaca_sip_adjusted",
                        )
                    )
            page_token = payload.get("next_page_token")
            if not page_token:
                return rows

    for offset in range(0, len(symbols), max(1, batch_size)):
        batch = symbols[offset : offset + batch_size]
        try:
            label = f"{offset + 1}-{offset + len(batch)}"
            rows = fetch_rows(batch, label)
            if rows:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(
                            cur,
                            f"""
                            INSERT INTO {PRICE_TABLE}
                                (symbol,date,open,high,low,close,volume,source)
                            VALUES %s
                            ON CONFLICT (symbol,date,source) DO UPDATE SET
                                open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                                close=EXCLUDED.close, volume=EXCLUDED.volume
                            """,
                            rows,
                        )
            batch_bars = len(rows)
            counts["bars"] += batch_bars
            counts["batches"] += 1
            print(
                f"expanded_price_batch | {label}/{len(symbols)} "
                f"| rows={batch_bars}"
            )
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            counts["failed_batches"] += 1
            print(
                f"expanded_price_batch | {offset + 1}-{offset + len(batch)}/{len(symbols)} "
                f"| ERROR={type(exc).__name__}: {exc}"
            )
    return counts


def _asof_bars(series: Series, as_of: date) -> list[Bar]:
    return [bar for bar in series.bars if bar.day < as_of]


def has_adjusted_price_artifact(bars: list[Bar]) -> bool:
    """Flag impossible-looking adjusted-price discontinuities for review."""
    for previous, current in zip(bars, bars[1:]):
        if previous.close <= 0 or current.close <= 0:
            continue
        ratio = current.close / previous.close
        if ratio > MAX_ADJUSTED_CLOSE_RATIO or ratio < 1 / MAX_ADJUSTED_CLOSE_RATIO:
            return True
    return False


def _screen_observation(series: Series, as_of: date) -> dict[str, Any] | None:
    cutoff = bisect_left(series.days, as_of)
    if cutoff < LOOKBACK_SESSIONS:
        return None
    trailing = series.bars[cutoff - LIQUIDITY_SESSIONS : cutoff]
    median_close = statistics.median(bar.close for bar in trailing)
    median_dollar_volume = statistics.median(bar.close * bar.volume for bar in trailing)
    return {
        "last_data_day": series.bars[cutoff - 1].day,
        "sessions_available": cutoff,
        "median_close_60": median_close,
        "median_dollar_volume_60": median_dollar_volume,
        "uses_future_data": False,
    }


def choose_liquidity_floor(
    series: dict[str, Series],
    as_of: date = CALIBRATION_DATE,
    target: int = TARGET_UNIVERSE,
) -> float:
    observations = [
        item["median_dollar_volume_60"]
        for item in (
            _screen_observation(value, as_of) for value in series.values()
        )
        if item is not None and item["median_close_60"] > 5
    ]
    if len(observations) < target:
        raise RuntimeError(
            f"liquidity calibration has only {len(observations)} candidates; "
            f"needs {target}"
        )
    ordered = sorted(observations, reverse=True)
    return float(ordered[target - 1])


def screen_universe(
    series: dict[str, Series],
    candidates: Iterable[str],
    as_of: date,
    liquidity_floor: float,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    qualified: set[str] = set()
    observations: dict[str, dict[str, Any]] = {}
    for symbol in sorted(set(candidates)):
        data = series.get(symbol)
        observation = _screen_observation(data, as_of) if data else None
        if observation is None:
            continue
        observations[symbol] = observation
        if (
            observation["median_dollar_volume_60"] >= liquidity_floor
            and observation["median_close_60"] > 5
            and not observation["uses_future_data"]
        ):
            qualified.add(symbol)
    return qualified, observations


def screen_funnel(
    series: dict[str, Series],
    candidates: Iterable[str],
    as_of: date,
    liquidity_floor: float = LOCKED_LIQUIDITY_FLOOR,
) -> dict[str, Any]:
    """Apply gates in order and retain counts for the data-parity report."""
    counts = {
        "total_candidates": len(set(candidates)),
        "no_price_data": 0,
        "fewer_than_252_sessions": 0,
        "below_liquidity_floor": 0,
        "median_close_le_5": 0,
        "corporate_action_artifacts": 0,
        "qualifying": 0,
    }
    qualified: set[str] = set()
    observations: dict[str, dict[str, Any]] = {}
    for symbol in sorted(set(candidates)):
        data = series.get(symbol)
        prior = _asof_bars(data, as_of) if data else []
        if not prior:
            counts["no_price_data"] += 1
            continue
        if len(prior) < LOOKBACK_SESSIONS:
            counts["fewer_than_252_sessions"] += 1
            continue
        if has_adjusted_price_artifact(prior):
            counts["corporate_action_artifacts"] += 1
            continue
        trailing = prior[-LIQUIDITY_SESSIONS:]
        med_close = statistics.median(bar.close for bar in trailing)
        med_dollar_volume = statistics.median(bar.close * bar.volume for bar in trailing)
        observations[symbol] = {
            "last_data_day": prior[-1].day,
            "sessions_available": len(prior),
            "median_close_60": med_close,
            "median_dollar_volume_60": med_dollar_volume,
            "uses_future_data": any(bar.day >= as_of for bar in prior),
        }
        if med_dollar_volume < liquidity_floor:
            counts["below_liquidity_floor"] += 1
            continue
        if med_close <= 5:
            counts["median_close_le_5"] += 1
            continue
        qualified.add(symbol)
    counts["qualifying"] = len(qualified)
    return {"counts": counts, "qualified": qualified, "observations": observations}


def current_screen_report(
    series: dict[str, Series],
    candidates: Iterable[str],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Print today's fixed-pipeline funnel and safe diagnostic top 20."""
    as_of = as_of or date.today()
    funnel = screen_funnel(series, candidates, as_of, LOCKED_LIQUIDITY_FLOOR)
    ranked: list[dict[str, Any]] = []
    for symbol in sorted(funnel["qualified"]):
        data = series[symbol]
        prior = _asof_bars(data, as_of)
        momentum = prior[-22].close / prior[-252].close - 1
        if not math.isfinite(momentum):
            continue
        if momentum > MOMENTUM_ARTEFACT_THRESHOLD:
            print(
                f"momentum_artifact | symbol={symbol} | momentum={momentum:.6f} "
                f"| threshold={MOMENTUM_ARTEFACT_THRESHOLD:.6f} "
                "| action=excluded_pending_review"
            )
            continue
        ranked.append(
            {
                "symbol": symbol,
                "momentum": momentum,
                "median_dollar_volume": funnel["observations"][symbol][
                    "median_dollar_volume_60"
                ],
                "median_close": funnel["observations"][symbol]["median_close_60"],
                "asset_class": "ordinary_equity",
            }
        )
    ranked.sort(key=lambda item: (-item["momentum"], item["symbol"]))
    print(
        f"today_funnel | as_of={as_of} | "
        f"{json.dumps(funnel['counts'], sort_keys=True)}"
    )
    print(
        "today_top_20 | symbol | momentum | median_dollar_volume | "
        "median_close | target_notional | asset_class"
    )
    target_notional = STARTING_EQUITY / TOP_N
    for item in ranked[:TOP_N]:
        print(
            f"today_top_20 | {item['symbol']} | {item['momentum']:+.4%} | "
            f"${item['median_dollar_volume']:,.2f} | "
            f"${item['median_close']:,.2f} | ${target_notional:,.2f} | "
            f"{item['asset_class']}"
        )
    included_non_ordinary = sum(
        item["asset_class"] != "ordinary_equity" for item in ranked
    )
    print(
        f"today_sanity | included_non_ordinary={included_non_ordinary} "
        f"| artifact_excluded={len(funnel['qualified']) - len(ranked)} "
        f"| sector_concentration_review=required"
    )
    return {"funnel": funnel["counts"], "top_20": ranked[:TOP_N]}


def persist_universe_gate(valid: bool, report: dict[str, Any]) -> None:
    """Write a local development gate consumed by the paused live module."""
    UNIVERSE_GATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE_GATE_FILE.write_text(
        json.dumps(
            {
                "status": "PASS" if valid else "STOP",
                "historical_parity_required": True,
                "report": _jsonable(report),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _first_available_day(series: dict[str, Series], year: int, month: int = 6) -> date:
    wanted = date(year, month, 1)
    days = sorted({day for data in series.values() for day in data.days if day >= wanted})
    if not days:
        raise RuntimeError(f"no price session available after {wanted}")
    return days[0]


def mechanical_gate(
    series: dict[str, Series],
    candidate_symbols: set[str],
) -> tuple[bool, float, dict[str, Any]]:
    floor = LOCKED_LIQUIDITY_FLOOR
    print(
        f"liquidity_floor | locked_usd={floor:.2f} "
        f"| source=experiment_13 | retuning=disabled"
    )
    snapshots: dict[str, Any] = {}
    valid = True
    print(
        "mechanical_sample | as_of | qualified | history_eligible | "
        "median_dollar_volume_floor | future_rows"
    )
    for as_of in SAMPLE_DATES:
        funnel = screen_funnel(series, candidate_symbols, as_of, floor)
        qualified = funnel["qualified"]
        observations = funnel["observations"]
        future_rows = sum(
            int(item["uses_future_data"]) for item in observations.values()
        )
        snapshots[as_of.isoformat()] = {
            "qualified": sorted(qualified),
            "qualified_count": len(qualified),
            "history_eligible": len(observations),
            "future_rows": future_rows,
            "observations": observations,
            "funnel": funnel["counts"],
        }
        print(
            f"mechanical_sample | {as_of} | {len(qualified)} | {len(observations)} | "
            f"{floor:.2f} | {future_rows} | funnel={json.dumps(funnel['counts'], sort_keys=True)}"
        )
        if future_rows or len(qualified) == 0:
            valid = False

        expected = PARITY_REFERENCE_COUNTS.get(as_of)
        if expected is not None:
            lower = expected * 0.80
            upper = expected * 1.20
            parity_ok = lower <= len(qualified) <= upper
            print(
                f"parity_gate | as_of={as_of} | expected={expected} "
                f"| observed={len(qualified)} | tolerance=20% "
                f"| {'PASS' if parity_ok else 'FAIL'}"
            )
            if not parity_ok:
                valid = False

    first_set = set(snapshots[SAMPLE_DATES[0].isoformat()]["qualified"])
    last_set = set(snapshots[SAMPLE_DATES[-1].isoformat()]["qualified"])
    dropouts = sorted(first_set - last_set)
    early_delisted = sorted(
        symbol
        for symbol in first_set
        if series[symbol].bars[-1].day < SAMPLE_DATES[-1]
    )
    print(
        f"mechanical_dropout | early_date={SAMPLE_DATES[0]} | late_date={SAMPLE_DATES[-1]} "
        f"| early_qualified_later_absent={len(dropouts)} "
        f"| early_qualified_data_ended_before_late={len(early_delisted)}"
    )
    print(
        "mechanical_dropout_symbols | "
        + ",".join(early_delisted[:30] if early_delisted else ["NONE"])
    )
    if len(dropouts) == 0:
        print("mechanical_dropout_gate | STOP | no symbols drop out over time")
        valid = False
    if len(early_delisted) < 3:
        print(
            "mechanical_delisted_gate | STOP | "
            f"expected_at_least=3 observed={len(early_delisted)}"
        )
        valid = False
    else:
        print(f"mechanical_delisted_gate | PASS | observed={len(early_delisted)}")

    annual: dict[str, Any] = {}
    previous: set[str] = set()
    print("year | as_of | universe_count | additions | drops | median_dollar_volume | artifacts")
    for year in range(2019, ANALYSIS_END.year + 1):
        as_of = _first_available_day(series, year)
        current, observations = screen_universe(series, candidate_symbols, as_of, floor)
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

    missing_price_symbols = sorted(candidate_symbols - set(series))
    artifact_flags = {
        "candidate_symbols": len(candidate_symbols),
        "price_backed_symbols": len(set(series)),
        "missing_price_history": len(missing_price_symbols),
        "missing_price_examples": missing_price_symbols[:30],
        "panel_symbols_with_no_bars": sorted(symbol for symbol, value in series.items() if not value.bars),
    }
    print(
        f"data_artifact_flags | candidate_symbols={artifact_flags['candidate_symbols']} "
        f"| price_backed={artifact_flags['price_backed_symbols']} "
        f"| missing_price_history={artifact_flags['missing_price_history']} "
        f"| panel_empty={len(artifact_flags['panel_symbols_with_no_bars'])}"
    )
    return valid, floor, {
        "liquidity_floor": floor,
        "sample_dates": snapshots,
        "annual": annual,
        "dropouts": dropouts,
        "early_delisted": early_delisted,
        "artifact_flags": artifact_flags,
    }


def audit_earnings() -> dict[str, Any]:
    valid = True
    manual_cost = 0
    rows_by_symbol: dict[str, int] = {}
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
                manual_cost += int(manual_rows) if symbol == "COST" else 0
                print(f"earnings_audit | {symbol} | {rows} | {manual_rows} | {signal_rows}")
                if not rows or (symbol != "COST" and not signal_rows):
                    valid = False
    print(
        f"earnings_cost_rule | manual_rows_excluded={manual_cost} "
        "| COST is never included from source=manual"
    )
    print(f"earnings_audit_gate | {'PASS' if valid else 'STOP'}")
    if not valid:
        raise RuntimeError("Bot 2 earnings audit failed")
    return {"rows_by_symbol": rows_by_symbol, "manual_cost_rows_excluded": manual_cost}


def _is_signal_earnings_event(
    symbol: str,
    surprise: float | None,
    report_time: str | None,
    source: str | None,
) -> bool:
    """Apply the frozen PEAD event filters before any return calculation."""
    if symbol not in PEAD_SYMBOLS or source == "manual" or surprise is None or surprise <= 0:
        return False
    timing = (report_time or "").lower()
    return "pre" in timing or "before" in timing or "post" in timing or "after" in timing


def _daily_dates(series: dict[str, Series]) -> list[date]:
    return sorted({day for data in series.values() for day in data.days})


def _bar_at_or_before(data: Series, day: date) -> Bar | None:
    index = bisect_left(data.days, day)
    return data.bars[index - 1] if index else None


def _bar_on_open(data: Series, day: date) -> Bar | None:
    return data.by_date.get(day) or _bar_at_or_before(data, day)


def _monthly_rebalance_days(days: Iterable[date]) -> set[date]:
    result: set[date] = set()
    seen: set[tuple[int, int]] = set()
    for day in sorted(days):
        key = (day.year, day.month)
        if key not in seen:
            result.add(day)
            seen.add(key)
    return result


def _momentum_candidates(
    series: dict[str, Series],
    symbols: set[str],
    day: date,
    liquidity_floor: float,
) -> list[tuple[str, float, float]]:
    screened, _ = screen_universe(series, symbols, day, liquidity_floor)
    ranked: list[tuple[str, float, float]] = []
    for symbol in screened:
        data = series[symbol]
        cutoff = bisect_left(data.days, day)
        if cutoff < LOOKBACK_SESSIONS:
            continue
        # 12–1 momentum: 252-session lookback, skipping the most recent month.
        momentum = data.bars[cutoff - 22].close / data.bars[cutoff - 252].close - 1
        returns = [
            data.bars[index].close / data.bars[index - 1].close - 1
            for index in range(max(1, cutoff - 63), cutoff)
            if data.bars[index - 1].close > 0
        ]
        volatility = statistics.pstdev(returns) * math.sqrt(252) if returns else 0.0
        if momentum > MOMENTUM_ARTEFACT_THRESHOLD:
            print(
                f"momentum_artifact | symbol={symbol} | "
                f"momentum={momentum:.6f} | threshold={MOMENTUM_ARTEFACT_THRESHOLD:.6f} "
                "| action=excluded_pending_review"
            )
            continue
        if momentum > 0 and volatility > 0:
            ranked.append((symbol, momentum, volatility))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def build_momentum_cache(
    series: dict[str, Series],
    symbols: set[str],
    liquidity_floor: float,
    end: date,
) -> dict[date, list[tuple[str, float, float]]]:
    """Compute each monthly signal once and reuse it across variants/controls."""
    days = [day for day in _daily_dates(series) if day <= end]
    return {
        day: _momentum_candidates(series, symbols, day, liquidity_floor)
        for day in _monthly_rebalance_days(days)
    }


def _metrics(
    curve: list[float],
    trade_returns: list[float],
    turnover: float,
    mode_days: dict[str, dict[str, int]],
    stops: int,
    max_deployment: float,
) -> dict[str, Any]:
    daily_returns = [
        curve[index] / curve[index - 1] - 1
        for index in range(1, len(curve))
        if curve[index - 1] > 0
    ]
    mean = statistics.fmean(daily_returns) if daily_returns else 0.0
    deviation = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0
    peak = curve[0] if curve else STARTING_EQUITY
    max_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak if peak else 0.0)
    return {
        "return": curve[-1] / curve[0] - 1 if curve and curve[0] else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe": mean / deviation * math.sqrt(252) if deviation else 0.0,
        "expectancy": statistics.fmean(trade_returns) if trade_returns else 0.0,
        "trades": len(trade_returns),
        "turnover": turnover / curve[0] if curve and curve[0] else 0.0,
        "stops": stops,
        "max_deployment": max_deployment,
        "mode_days": mode_days,
        "daily_returns": daily_returns,
    }


def _weights(
    ranked: list[tuple[str, float, float]],
    allocation: str,
) -> dict[str, float]:
    selected = ranked[:TOP_N]
    if not selected:
        return {}
    if allocation == "equal_weight":
        return {symbol: 1.0 / len(selected) for symbol, _, _ in selected}
    inverse = {symbol: 1.0 / volatility for symbol, _, volatility in selected}
    total = sum(inverse.values())
    return {symbol: value / total for symbol, value in inverse.items()}


def simulate_momentum(
    series: dict[str, Series],
    symbols: set[str],
    liquidity_floor: float,
    start: date,
    end: date,
    allocation: str = "equal_weight",
    selector: Callable[[list[tuple[str, float, float]]], list[tuple[str, float, float]]] | None = None,
    ranking_cache: dict[date, list[tuple[str, float, float]]] | None = None,
) -> dict[str, Any]:
    days = [day for day in _daily_dates(series) if day <= end]
    rebalance_days = _monthly_rebalance_days(days)
    ranking_cache = ranking_cache or build_momentum_cache(
        series, symbols, liquidity_floor, end
    )
    slip = SLIPPAGE_BPS / 10_000
    cash = STARTING_EQUITY
    holdings: dict[str, dict[str, float]] = {}
    curve: list[float] = []
    trade_returns: list[float] = []
    turnover = 0.0
    stops = 0
    max_deployment = 0.0
    mode_days: dict[str, dict[str, int]] = defaultdict(lambda: {"invested": 0, "cash": 0})

    def equity_at(day: date, use_open: bool = False) -> float:
        value = cash
        for symbol, holding in holdings.items():
            bar = _bar_on_open(series[symbol], day) if use_open else _bar_at_or_before(series[symbol], day)
            if bar:
                value += holding["qty"] * (bar.open if use_open else bar.close)
        return value

    for day in days:
        if day in rebalance_days:
            equity_open = equity_at(day, use_open=True)
            for symbol, holding in list(holdings.items()):
                bar = _bar_on_open(series[symbol], day)
                if bar is None:
                    continue
                exit_price = bar.open * (1 - slip)
                value = holding["qty"] * exit_price
                cash += value
                turnover += value
                trade_returns.append(exit_price / holding["entry_price"] - 1)
                del holdings[symbol]
            ranked = ranking_cache.get(day, [])
            chosen = selector(ranked) if selector else ranked
            selected = chosen[:TOP_N]
            weights = _weights(selected, allocation)
            for symbol, weight in weights.items():
                bar = _bar_on_open(series[symbol], day)
                if bar is None:
                    continue
                entry_price = bar.open * (1 + slip)
                notional = min(equity_open * weight, cash)
                if notional <= 0:
                    continue
                cash -= notional
                turnover += notional
                holdings[symbol] = {
                    "qty": notional / entry_price,
                    "entry_price": entry_price,
                    "stop": entry_price * (1 - STOP_LOSS),
                }
        for symbol, holding in list(holdings.items()):
            bar = series[symbol].by_date.get(day)
            if bar is not None and bar.low <= holding["stop"]:
                exit_price = min(bar.open, holding["stop"]) * (1 - slip)
                value = holding["qty"] * exit_price
                cash += value
                turnover += value
                trade_returns.append(exit_price / holding["entry_price"] - 1)
                stops += 1
                del holdings[symbol]
        equity_close = equity_at(day)
        if start <= day <= end:
            curve.append(equity_close)
            deployed = (
                sum(
                    holding["qty"] * (_bar_at_or_before(series[symbol], day).close)
                    for symbol, holding in holdings.items()
                    if _bar_at_or_before(series[symbol], day) is not None
                )
                / equity_close
                if equity_close > 0
                else 0.0
            )
            max_deployment = max(max_deployment, deployed)
            mode_days[str(day.year)]["invested" if holdings else "cash"] += 1
        if day >= end:
            break
    for symbol, holding in list(holdings.items()):
        bar = _bar_at_or_before(series[symbol], end)
        if bar:
            exit_price = bar.close * (1 - slip)
            trade_returns.append(exit_price / holding["entry_price"] - 1)
            turnover += holding["qty"] * exit_price
    return _metrics(curve, trade_returns, turnover, dict(mode_days), stops, max_deployment)


def _load_earnings_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT symbol, reported_date, surprise, report_time, source
                  FROM {EARNINGS_TABLE}
                 WHERE reported_date >= %s AND source <> 'manual'
                 ORDER BY reported_date, symbol, id
                """,
                (ANALYSIS_START,),
            )
            for symbol, reported_date, surprise, report_time, source in cur.fetchall():
                if not _is_signal_earnings_event(
                    symbol,
                    float(surprise) if surprise is not None else None,
                    report_time,
                    source,
                ):
                    continue
                timing = (report_time or "").lower()
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


def _event_schedule(
    events: list[dict[str, Any]],
    series: dict[str, Series],
    hold_sessions: int,
    liquidity_floor: float,
    candidate_symbols: set[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event in events:
        data = series.get(event["symbol"])
        if data is None:
            continue
        if "post" in event["report_time"] or "after" in event["report_time"]:
            entry_days = [day for day in data.days if day > event["reported_date"]]
        elif "pre" in event["report_time"] or "before" in event["report_time"]:
            entry_days = [day for day in data.days if day >= event["reported_date"]]
        else:
            continue
        if not entry_days:
            continue
        entry_day = entry_days[0]
        screened, _ = screen_universe(
            series, candidate_symbols, entry_day, liquidity_floor
        )
        if event["symbol"] not in screened:
            continue
        entry_index = data.days.index(entry_day)
        exit_index = entry_index + hold_sessions - 1
        if exit_index >= len(data.days):
            continue
        output.append(
            {
                **event,
                "entry_day": entry_day,
                "exit_day": data.days[exit_index],
            }
        )
    return output


def simulate_pead(
    events: list[dict[str, Any]],
    series: dict[str, Series],
    candidate_symbols: set[str],
    liquidity_floor: float,
    hold_sessions: int,
    start: date,
    end: date,
) -> dict[str, Any]:
    scheduled = _event_schedule(
        events, series, hold_sessions, liquidity_floor, candidate_symbols
    )
    entries = defaultdict(list)
    exits = defaultdict(list)
    for event in scheduled:
        if start <= event["entry_day"] <= end:
            entries[event["entry_day"]].append(event)
            exits[event["exit_day"]].append(event)
    days = [day for day in _daily_dates(series) if start <= day <= end]
    slip = SLIPPAGE_BPS / 10_000
    cash = STARTING_EQUITY
    positions: list[dict[str, Any]] = []
    curve: list[float] = []
    trade_returns: list[float] = []
    turnover = 0.0
    stops = 0
    max_deployment = 0.0
    mode_days: dict[str, dict[str, int]] = defaultdict(lambda: {"invested": 0, "cash": 0})
    for day in days:
        for position in list(positions):
            if position["exit_day"] != day:
                continue
            bar = series[position["symbol"]].by_date.get(day)
            if bar is None:
                continue
            exit_price = bar.open * (1 - slip)
            value = position["qty"] * exit_price
            cash += value
            turnover += value
            trade_returns.append(exit_price / position["entry_price"] - 1)
            positions.remove(position)
        new_events = [
            event for event in entries.get(day, [])
            if not any(position["symbol"] == event["symbol"] for position in positions)
        ]
        for event in sorted(new_events, key=lambda item: item["symbol"]):
            bar = series[event["symbol"]].by_date.get(day)
            if bar is None:
                continue
            equity_open = cash + sum(
                position["qty"] * series[position["symbol"]].by_date[day].open
                for position in positions
                if day in series[position["symbol"]].by_date
            )
            allocation = 1.0 / max(1, len(new_events))
            entry_price = bar.open * (1 + slip)
            notional = min(equity_open * allocation, cash)
            if notional <= 0:
                continue
            cash -= notional
            turnover += notional
            positions.append(
                {
                    "symbol": event["symbol"],
                    "entry_price": entry_price,
                    "qty": notional / entry_price,
                    "stop": entry_price * (1 - STOP_LOSS),
                    "exit_day": event["exit_day"],
                }
            )
        for position in list(positions):
            bar = series[position["symbol"]].by_date.get(day)
            if bar is not None and bar.low <= position["stop"]:
                exit_price = min(bar.open, position["stop"]) * (1 - slip)
                value = position["qty"] * exit_price
                cash += value
                turnover += value
                trade_returns.append(exit_price / position["entry_price"] - 1)
                positions.remove(position)
                stops += 1
        for position in list(positions):
            if position["exit_day"] != day:
                continue
            bar = series[position["symbol"]].by_date.get(day)
            if bar is None:
                continue
            exit_price = bar.close * (1 - slip)
            value = position["qty"] * exit_price
            cash += value
            turnover += value
            trade_returns.append(exit_price / position["entry_price"] - 1)
            positions.remove(position)
        equity_close = cash + sum(
            position["qty"] * series[position["symbol"]].by_date[day].close
            for position in positions
            if day in series[position["symbol"]].by_date
        )
        curve.append(equity_close)
        deployed_value = equity_close - cash
        max_deployment = max(
            max_deployment, deployed_value / equity_close if equity_close else 0.0
        )
        mode_days[str(day.year)]["invested" if positions else "cash"] += 1
    return _metrics(curve, trade_returns, turnover, dict(mode_days), stops, max_deployment)


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


def simulate_spy(series: Series, start: date, end: date) -> dict[str, Any]:
    bars = [bar for bar in series.bars if start <= bar.day <= end]
    if len(bars) < 2:
        return _metrics([], [], 0.0, {}, 0, 0.0)
    slip = SLIPPAGE_BPS / 10_000
    entry = bars[0].open * (1 + slip)
    curve = [bar.close / entry * STARTING_EQUITY * (1 - slip) for bar in bars]
    return _metrics(
        curve,
        [curve[-1] / curve[0] - 1],
        STARTING_EQUITY * 2 * slip,
        {str(start.year): {"invested": len(bars), "cash": 0}},
        0,
        1.0,
    )


def random_controls(
    series: dict[str, Series],
    symbols: set[str],
    liquidity_floor: float,
    start: date,
    end: date,
    ranking_cache: dict[date, list[tuple[str, float, float]]] | None = None,
) -> dict[str, Any]:
    outcomes: list[float] = []
    sharpes: list[float] = []
    for iteration in range(CONTROL_ITERATIONS):
        rng = random.Random(RANDOM_SEED + iteration)

        def select(ranked: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
            size = min(TOP_N, len(ranked))
            return rng.sample(ranked, size) if size else []

        result = simulate_momentum(
            series,
            symbols,
            liquidity_floor,
            start,
            end,
            "equal_weight",
            select,
            ranking_cache,
        )
        outcomes.append(result["return"])
        sharpes.append(result["sharpe"])
    outcomes.sort()
    sharpes.sort()
    return {
        "iterations": CONTROL_ITERATIONS,
        "seed": RANDOM_SEED,
        "matched_selection_size": TOP_N,
        "return_mean": statistics.fmean(outcomes) if outcomes else 0.0,
        "return_median": statistics.median(outcomes) if outcomes else 0.0,
        "return_p05": outcomes[max(0, int(len(outcomes) * 0.05) - 1)] if outcomes else 0.0,
        "return_p95": outcomes[min(len(outcomes) - 1, int(len(outcomes) * 0.95))] if outcomes else 0.0,
        "sharpe_mean": statistics.fmean(sharpes) if sharpes else 0.0,
        "dispersion_check": len(set(outcomes)) > 1,
    }


def _find_experiment() -> int | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT experiment_id, results
                  FROM research_ledger
                 WHERE strategy_family='bot2_momentum_pead_v3'
                 ORDER BY experiment_id DESC
                 LIMIT 1
                """
            )
            row = cur.fetchone()
    if row and row[1] is not None:
        raise RuntimeError(f"bot2_momentum_pead_v3 already recorded: experiment_id={row[0]}")
    return int(row[0]) if row else None


def _jsonable(value: Any) -> Any:
    """Convert audit objects to the JSON shape required by research_ledger."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def run_research(
    *,
    refresh_assets: bool = True,
    ingest_expanded: bool = False,
) -> dict[str, Any]:
    ensure_asset_table()
    series = load_panel()
    if refresh_assets:
        assets = fetch_tradable_us_equities()
        persist_assets(assets)
    else:
        assets = [
            Asset(symbol, "us_equity", "active", "", True, None)
            for symbol in load_asset_symbols()
        ]
    candidate_symbols = set(asset.symbol for asset in assets)
    panel_symbols = set(series) & candidate_symbols
    print(
        f"asset_expansion | ordinary_equity_assets={len(candidate_symbols)} "
        f"| historical_panel_symbols={len(panel_symbols)} "
        f"| candidate_union={len(candidate_symbols)}"
    )
    if ingest_expanded:
        print(f"expanded_price_ingest | {ingest_expanded_prices(assets)}")

    series = load_panel()
    panel_symbols = set(series) & candidate_symbols
    coverage = coverage_report(candidate_symbols)
    print(
        f"asset_coverage | total={coverage['total_symbols']} "
        f"| >=252={coverage['symbols_with_at_least_252_sessions']} "
        f"| partial={coverage['symbols_with_partial_history']} "
        f"| none={coverage['symbols_with_no_history']}"
    )
    today_report = current_screen_report(series, candidate_symbols)
    gate_ok, liquidity_floor, gate_report = mechanical_gate(series, candidate_symbols)
    gate_report["today"] = today_report
    persist_universe_gate(gate_ok, gate_report)
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

    # The pass bar is derived from a fully specified momentum-alone baseline,
    # then frozen before registration and before any PEAD result is calculated.
    ranking_cache = build_momentum_cache(
        series, panel_symbols, liquidity_floor, ANALYSIS_END
    )
    baseline = simulate_momentum(
        series,
        panel_symbols,
        liquidity_floor,
        date(2018, 1, 1),
        ANALYSIS_END,
        ranking_cache=ranking_cache,
    )
    parameters = {
        "universe_rule": {
            "candidate_pool": "Alpaca currently tradable us_equity union retained historical panel",
            "as_of_rule": "only bars with date strictly before rebalance date",
            "minimum_prior_sessions": LOOKBACK_SESSIONS,
            "trailing_liquidity_sessions": LIQUIDITY_SESSIONS,
            "trailing_median_close_min": 5.0,
            "liquidity_floor_usd": liquidity_floor,
            "liquidity_floor_calibration_date": CALIBRATION_DATE.isoformat(),
            "liquidity_floor_calibration_target": TARGET_UNIVERSE,
        },
        "momentum": {"lookback": "12-1", "top_n": TOP_N, "allocations": ["equal_weight", "inverse_volatility"]},
        "pead": {"holds": [5, 20], "positive_surprise_only": True, "manual_cost_excluded": True},
        "slippage_each_leg_bps": SLIPPAGE_BPS,
        "catastrophe_stop": STOP_LOSS,
        "starting_equity": STARTING_EQUITY,
        "deployment_cap": 1.0,
        "random_controls": {"iterations": CONTROL_ITERATIONS, "seed": RANDOM_SEED, "matched_size": TOP_N},
        "sgov_parking": "cash-equivalent when no qualifying position; no synthetic return added",
    }
    pass_bar = {
        "pooled_primary_sharpe_min": 0.50,
        "pooled_primary_max_drawdown_max": 0.20,
        "primary_must_beat_momentum_alone": True,
        "primary_expectancy_minimum_derived_from_momentum_alone": baseline["expectancy"],
        "positive_annual_windows_min": 3,
    }
    data_window = {
        "start": ANALYSIS_START.isoformat(),
        "end": ANALYSIS_END.isoformat(),
        "windows": [{"name": name, "start": str(start), "end": str(end)} for name, start, end in WINDOWS],
        "price_table": PRICE_TABLE,
        "price_sources": list(PRICE_SOURCES),
        "earnings_table": EARNINGS_TABLE,
        "mechanical_gate": "four historical parity dates within 20% plus dropout proof",
        "momentum_artifact_threshold": MOMENTUM_ARTEFACT_THRESHOLD,
    }
    ensure_research_tables()
    experiment_id = _find_experiment()
    if experiment_id is None:
        experiment_id = register_experiment(
            strategy_family="bot2_momentum_pead_v3",
            bot_id="bot2_momentum_pead_v3_research",
            hypothesis=(
                "A mechanically screened, liquid price-and-volume universe combined "
                "with 12-1 momentum and positive-surprise PEAD can improve risk-adjusted "
                "returns without implicit leverage or future constituent information."
            ),
            parameters=parameters,
            pass_bar=pass_bar,
            data_window=data_window,
            variations_tested=6,
            sizing_model="cash_constrained",
            went_live=False,
            notes="Development-only research. No orders, live module, runner, or deployment changes.",
        )
        print(f"experiment_registered | experiment_id={experiment_id}")
    else:
        print(f"experiment_registration | experiment_id={experiment_id} | status=resume_uncompleted")

    events = _load_earnings_events()
    all_results: dict[str, Any] = {
        "experiment_id": experiment_id,
        "mechanical_gate": gate_report,
        "earnings_audit": earnings_report,
        "configuration": {"parameters": parameters, "pass_bar": pass_bar, "data_window": data_window},
        "windows": {},
        "controls": {},
        "live_execution": False,
        "orders_placed": 0,
    }
    spy_series = _spy_series()
    for name, start, end in WINDOWS:
        equal = simulate_momentum(
            series, panel_symbols, liquidity_floor, start, end,
            "equal_weight", ranking_cache=ranking_cache
        )
        inverse = simulate_momentum(
            series, panel_symbols, liquidity_floor, start, end,
            "inverse_volatility", ranking_cache=ranking_cache
        )
        pead5 = simulate_pead(events, series, panel_symbols, liquidity_floor, 5, start, end)
        pead20 = simulate_pead(events, series, panel_symbols, liquidity_floor, 20, start, end)
        spy = simulate_spy(spy_series, start, end)
        all_results["windows"][name] = {
            "momentum_equal_weight": equal,
            "momentum_inverse_volatility": inverse,
            "pead_rotation_5": pead5,
            "pead_rotation_20": pead20,
            "pead_alone": pead20,
            "spy_buy_and_hold": spy,
        }
        for label, result in all_results["windows"][name].items():
            print(
                f"result | window={name} | strategy={label} | return={result['return']:.6f} "
                f"| maxDD={result['max_drawdown']:.6f} | sharpe={result['sharpe']:.6f} "
                f"| expectancy={result['expectancy']:.6f} | max_deployment={result['max_deployment']:.6f}"
            )
        all_results["controls"][name] = {"momentum_alone": equal}

    random_result = random_controls(
        series,
        panel_symbols,
        liquidity_floor,
        WINDOWS[-1][1],
        WINDOWS[-1][2],
        ranking_cache,
    )
    all_results["controls"]["pooled_2018_present"]["random_control_1000"] = random_result
    print(
        f"random_control | window=pooled_2018_present | iterations={CONTROL_ITERATIONS} "
        f"| mean={random_result['return_mean']:.6f} "
        f"| p05={random_result['return_p05']:.6f} | p95={random_result['return_p95']:.6f}"
    )

    pooled = all_results["windows"]["pooled_2018_present"]
    primary = pooled["pead_rotation_20"]
    baseline_result = pooled["momentum_equal_weight"]
    annual_primary = [
        simulate_pead(events, series, panel_symbols, liquidity_floor, 20, date(year, 1, 1), date(year, 12, 31))["return"]
        for year in range(2019, ANALYSIS_END.year + 1)
    ]
    checks = {
        "pooled_primary_sharpe": primary["sharpe"] >= pass_bar["pooled_primary_sharpe_min"],
        "pooled_primary_max_drawdown": primary["max_drawdown"] <= pass_bar["pooled_primary_max_drawdown_max"],
        "primary_beats_momentum_alone": primary["return"] > baseline_result["return"],
        "positive_annual_windows": sum(value > 0 for value in annual_primary) >= pass_bar["positive_annual_windows_min"],
        "deployment_cap": all(
            result["max_deployment"] <= 1.0000001
            for window in all_results["windows"].values()
            for result in window.values()
            if isinstance(result, dict) and "max_deployment" in result
        ),
        "random_control_has_dispersion": random_result["dispersion_check"],
    }
    outcome = "PASS" if all(checks.values()) else "FAIL"
    all_results["evaluation"] = {
        "checks": checks,
        "outcome": outcome,
        "annual_primary_returns_2019_present": annual_primary,
        "sharpe_window_caveat": (
            "Sharpe is computed from daily returns within each requested window; "
            "pooled Sharpe concatenates those daily observations and is not a claim "
            "that a single continuously funded account had identical window starts."
        ),
        "no_crash_window_caveat": (
            "The requested annual report includes 2022; no unrequested crash-window "
            "selection or parameter retuning was added."
        ),
    }
    record_results(experiment_id, _jsonable(all_results), outcome)
    print(f"results_recorded | experiment_id={experiment_id} | outcome={outcome} | recorded_once=true")
    print(
        "verification | execution_mode=read_only | orders_placed=0 | "
        "live_strategy_module=0 | bot1_touched=0 | bot3_touched=0 | "
        "vault_touched=0 | monitoring_touched=0 | published=0"
    )
    all_results["status"] = "COMPLETE"
    return all_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--use-stored-assets",
        action="store_true",
        help="Use the previously audited Alpaca asset table instead of refreshing it.",
    )
    parser.add_argument(
        "--ingest-expanded",
        action="store_true",
        help="Explicitly fetch Alpaca bars for the complete asset listing.",
    )
    args = parser.parse_args()
    result = run_research(
        refresh_assets=not args.use_stored_assets,
        ingest_expanded=args.ingest_expanded,
    )
    return 0 if result["status"] != "STOP" and result.get("evaluation", {}).get("outcome") == "PASS" else (
        2 if result["status"] == "STOP" else 4
    )


if __name__ == "__main__":
    raise SystemExit(main())