#!/usr/bin/env python3
"""Development-only point-in-time S&P 500 data gate for Bot 2 v3.

This module is deliberately separate from the live runners and the existing
Bot 2 earnings tables.  It stores only research membership events and Alpaca
SIP daily bars in dedicated tables.  No order, portfolio, runner, or
production-database code is imported.

The public membership bundle is pinned to a GitHub commit and extended with
two official S&P Dow Jones announcements that occurred after that snapshot.
The A1 gate fails closed when the bundle is stale, membership reconstruction is
inconsistent, or a historical member lacks complete prices for its membership
interval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import psycopg2.extras
import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402


SOURCE_BUNDLE = (
    Path(__file__).resolve().parent
    / "data"
    / "bot2_sp500_membership_2026-08-27.json"
)
PRICE_TABLE = "bot2_sp500_prices"
EVENT_TABLE = "bot2_sp500_membership_events"
META_TABLE = "bot2_sp500_price_meta"
ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
ANALYSIS_START = date(2018, 1, 1)
DEFAULT_END = date.today() - timedelta(days=1)
PRICE_SOURCE = "alpaca_sip_adjusted"
RECENT_PRICE_SOURCE = "alpaca_iex_adjusted"
PRICE_SOURCES = (PRICE_SOURCE, RECENT_PRICE_SOURCE)
RECENT_SIP_CUTOFF = date(2026, 1, 1)
SLICE_SIZE = 250


DATA_DDL = f"""
CREATE TABLE IF NOT EXISTS {EVENT_TABLE} (
    event_key       TEXT PRIMARY KEY,
    event_date      DATE NOT NULL,
    added           TEXT,
    removed         TEXT,
    source_kind     TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    source_sha256   TEXT,
    UNIQUE (event_date, added, removed)
);

CREATE TABLE IF NOT EXISTS {META_TABLE} (
    symbol          TEXT PRIMARY KEY,
    row_count       INTEGER NOT NULL DEFAULT 0,
    first_date      DATE,
    last_date       DATE,
    source_mix      TEXT,
    status          TEXT NOT NULL,
    error           TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE {META_TABLE} ADD COLUMN IF NOT EXISTS source_mix TEXT;

CREATE TABLE IF NOT EXISTS {PRICE_TABLE} (
    symbol          TEXT NOT NULL,
    date            DATE NOT NULL,
    open            DOUBLE PRECISION NOT NULL,
    high            DOUBLE PRECISION NOT NULL,
    low             DOUBLE PRECISION NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    volume          DOUBLE PRECISION NOT NULL,
    source          TEXT NOT NULL DEFAULT '{PRICE_SOURCE}',
    PRIMARY KEY (symbol, date, source)
);
CREATE INDEX IF NOT EXISTS idx_bot2_sp500_prices_symbol_date
    ON {PRICE_TABLE} (symbol, date);
"""


@dataclass(frozen=True)
class MembershipEvent:
    event_date: date
    added: str | None
    removed: str | None
    source_kind: str
    source_url: str
    source_sha256: str | None


@dataclass(frozen=True)
class MembershipInterval:
    symbol: str
    start: date
    end: date


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = PRICE_SOURCE


def _parse_day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _clean_symbol(value: Any) -> str | None:
    if value is None:
        return None
    symbol = str(value).strip().upper()
    return symbol or None


def price_symbol(bundle: dict[str, Any], symbol: str) -> str:
    """Return the price-provider symbol for a historical ticker alias."""
    aliases = bundle.get("symbol_aliases") or {}
    return _clean_symbol(aliases.get(symbol, symbol)) or symbol


def load_bundle(path: Path = SOURCE_BUNDLE) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"membership source bundle is missing: {path}")
    try:
        bundle = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"membership source bundle is invalid JSON: {exc}") from exc
    current = bundle.get("current")
    changes = bundle.get("changes")
    source = bundle.get("source")
    if not isinstance(current, list) or not isinstance(changes, list) or not isinstance(source, dict):
        raise RuntimeError("membership source bundle is missing current, changes, or source")
    if not current or any(not _clean_symbol(symbol) for symbol in current):
        raise RuntimeError("membership source bundle contains an invalid current symbol")
    if not source.get("coverage_end") or not source.get("membership_url"):
        raise RuntimeError("membership source bundle lacks coverage metadata")
    return bundle


def _events(bundle: dict[str, Any]) -> list[MembershipEvent]:
    source = bundle["source"]
    source_url = str(source["membership_url"])
    source_sha256 = str(source.get("membership_sha256") or "")
    official_by_date = {
        str(item["date"]): item
        for item in source.get("official_extensions", [])
        if isinstance(item, dict)
    }
    output: list[MembershipEvent] = []
    for raw in bundle["changes"]:
        if not isinstance(raw, dict):
            raise RuntimeError("membership source bundle contains a non-object change")
        event_date = _parse_day(raw.get("date"))
        added = _clean_symbol(raw.get("added"))
        removed = _clean_symbol(raw.get("removed"))
        if added is None and removed is None:
            raise RuntimeError(f"membership change has no symbol: {raw}")
        official = official_by_date.get(event_date.isoformat())
        if official and added == _clean_symbol(official.get("added")):
            source_kind = "official_spdj"
            event_url = str(official["source"])
            event_hash = None
        else:
            source_kind = "pinned_wikipedia_reconstruction"
            event_url = source_url
            event_hash = source_sha256
        output.append(
            MembershipEvent(
                event_date=event_date,
                added=added,
                removed=removed,
                source_kind=source_kind,
                source_url=event_url,
                source_sha256=event_hash,
            )
        )
    return sorted(output, key=lambda event: (event.event_date, event.added or "", event.removed or ""))


def source_coverage_end(bundle: dict[str, Any]) -> date:
    return _parse_day(bundle["source"]["coverage_end"])


def members_asof(bundle: dict[str, Any], as_of: date) -> set[str]:
    """Rewind the current snapshot without looking forward beyond coverage."""
    coverage_end = source_coverage_end(bundle)
    if as_of > coverage_end:
        raise RuntimeError(
            f"membership source stops at {coverage_end}; requested {as_of}"
        )
    members = {_clean_symbol(symbol) for symbol in bundle["current"]}
    members.discard(None)
    for event in reversed(_events(bundle)):
        if event.event_date <= as_of:
            break
        if event.added:
            members.discard(event.added)
        if event.removed:
            members.add(event.removed)
    return {symbol for symbol in members if symbol}


def _observed_fixed(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (ordinal - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nyse_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_fixed(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed(year, 12, 25),
        _easter_sunday(year) - timedelta(days=2),
    }
    if year >= 2022:
        holidays.add(_observed_fixed(year, 6, 19))
    if year == 2018:
        holidays.add(date(2018, 12, 5))
    if year == 2025:
        # National Day of Mourning for President Jimmy Carter.
        holidays.add(date(2025, 1, 9))
    return holidays


def expected_sessions(first: date, last: date) -> set[date]:
    output: set[date] = set()
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5 and cursor not in nyse_holidays(cursor.year):
            output.add(cursor)
        cursor += timedelta(days=1)
    return output


def membership_intervals(
    bundle: dict[str, Any],
    start: date = ANALYSIS_START,
    end: date = DEFAULT_END,
) -> list[MembershipInterval]:
    if end < start:
        raise ValueError("membership interval end precedes start")
    if end > source_coverage_end(bundle):
        raise RuntimeError(
            f"membership source stops at {source_coverage_end(bundle)}; "
            f"cannot build intervals through {end}"
        )
    active = {symbol: start for symbol in members_asof(bundle, start - timedelta(days=1))}
    intervals: list[MembershipInterval] = []
    anomalies: list[str] = []
    for event in _events(bundle):
        if event.event_date < start:
            continue
        if event.event_date > end:
            break
        if event.removed:
            opened = active.pop(event.removed, None)
            if opened is None:
                anomalies.append(f"remove_without_open={event.removed}@{event.event_date}")
            else:
                intervals.append(
                    MembershipInterval(event.removed, opened, event.event_date - timedelta(days=1))
                )
        if event.added:
            if event.added in active:
                anomalies.append(f"add_already_active={event.added}@{event.event_date}")
            else:
                active[event.added] = event.event_date
    intervals.extend(
        MembershipInterval(symbol, opened, end)
        for symbol, opened in active.items()
    )
    if anomalies:
        print("membership_anomalies | " + " | ".join(anomalies[:20]))
    return sorted(intervals, key=lambda item: (item.symbol, item.start))


def membership_report(
    bundle: dict[str, Any],
    start: date = ANALYSIS_START,
    end: date = DEFAULT_END,
) -> dict[str, Any]:
    print("=== A1 POINT-IN-TIME S&P 500 MEMBERSHIP ===")
    print(f"membership_source | {bundle['source']['membership_url']}")
    print(f"membership_commit | {bundle['source'].get('commit')}")
    print(f"membership_sha256 | {bundle['source'].get('membership_sha256')}")
    print(f"source_reported_snapshot | {bundle['source'].get('current_snapshot_source_date')}")
    print(f"source_coverage_end | {source_coverage_end(bundle)}")
    print(f"source_date_semantics | {bundle['source'].get('date_semantics')}")
    aliases = bundle.get("symbol_aliases") or {}
    if aliases:
        print(
            "historical_ticker_aliases | "
            + " | ".join(f"{old}->{new}" for old, new in sorted(aliases.items()))
        )
    print("year | membership_count_at_year_end | additions | removals")
    for year in range(start.year, end.year + 1):
        as_of = min(date(year, 12, 31), end)
        members = members_asof(bundle, as_of)
        additions = sum(
            event.added is not None
            for event in _events(bundle)
            if date(year, 1, 1) <= event.event_date <= as_of
        )
        removals = sum(
            event.removed is not None
            for event in _events(bundle)
            if date(year, 1, 1) <= event.event_date <= as_of
        )
        print(f"{year} | {len(members)} | {additions} | {removals}")
    intervals = membership_intervals(bundle, start, end)
    symbols = sorted({interval.symbol for interval in intervals})
    print(f"membership_interval_symbols | {len(symbols)}")
    print(f"membership_interval_count | {len(intervals)}")
    return {
        "source": bundle["source"],
        "symbols": symbols,
        "intervals": intervals,
    }


def ensure_tables() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(DATA_DDL)


def persist_membership(bundle: dict[str, Any]) -> None:
    rows = []
    for event in _events(bundle):
        payload = f"{event.event_date}|{event.added or ''}|{event.removed or ''}|{event.source_url}"
        rows.append(
            (
                hashlib.sha256(payload.encode()).hexdigest(),
                event.event_date,
                event.added,
                event.removed,
                event.source_kind,
                event.source_url,
                event.source_sha256,
            )
        )
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"""
                INSERT INTO {EVENT_TABLE}
                    (event_key, event_date, added, removed, source_kind, source_url, source_sha256)
                VALUES %s
                ON CONFLICT (event_key) DO UPDATE SET
                    event_date=EXCLUDED.event_date,
                    added=EXCLUDED.added,
                    removed=EXCLUDED.removed,
                    source_kind=EXCLUDED.source_kind,
                    source_url=EXCLUDED.source_url,
                    source_sha256=EXCLUDED.source_sha256
                """,
                rows,
            )


def _fetch_feed(
    symbol: str,
    start: date,
    end: date,
    feed: str,
    retries: int = 4,
) -> tuple[list[PriceBar], str | None]:
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return [], "ALPACA_API_KEY/ALPACA_SECRET_KEY are required"
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    }
    params: dict[str, Any] = {
        "symbols": symbol,
        "timeframe": "1Day",
        "start": f"{start.isoformat()}T00:00:00Z",
        "end": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
        "adjustment": "all",
        "feed": feed,
        "limit": 10_000,
    }
    for attempt in range(retries):
        bars: list[PriceBar] = []
        try:
            while True:
                response = requests.get(
                    ALPACA_BARS_URL,
                    headers=headers,
                    params=params,
                    timeout=45,
                )
                if response.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                if response.status_code != 200:
                    return [], f"HTTP {response.status_code}: {response.text[:240]}"
                payload = response.json()
                for raw in (payload.get("bars") or {}).get(symbol, []):
                    try:
                        bars.append(
                            PriceBar(
                                symbol=symbol,
                                day=_parse_day(raw["t"]),
                                open=float(raw["o"]),
                                high=float(raw["h"]),
                                low=float(raw["l"]),
                                close=float(raw["c"]),
                                volume=float(raw["v"]),
                                source=(
                                    PRICE_SOURCE
                                    if feed == "sip"
                                    else RECENT_PRICE_SOURCE
                                ),
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        return [], f"invalid Alpaca bar: {exc}"
                next_page = payload.get("next_page_token")
                if not next_page:
                    break
                params["page_token"] = next_page
            bars.sort(key=lambda bar: bar.day)
            return bars, None
        except requests.RequestException as exc:
            if attempt + 1 == retries:
                return [], f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return [], "unreachable fetch failure"


def _fetch_one_symbol(
    symbol: str,
    start: date,
    end: date,
    retries: int = 4,
) -> tuple[str, list[PriceBar], str | None]:
    """Fetch SIP history, falling back to IEX only for the denied recent slice."""
    bars, error = _fetch_feed(symbol, start, end, "sip", retries)
    if error is None:
        return symbol, bars, None
    if "recent SIP data" not in error or end < RECENT_SIP_CUTOFF:
        return symbol, [], error

    historical_end = RECENT_SIP_CUTOFF - timedelta(days=1)
    historical, historical_error = _fetch_feed(
        symbol, start, min(end, historical_end), "sip", retries
    )
    if historical_error:
        return symbol, [], f"historical SIP fallback failed: {historical_error}"
    recent, recent_error = _fetch_feed(
        symbol, max(start, RECENT_SIP_CUTOFF), end, "iex", retries
    )
    if recent_error:
        return symbol, [], f"recent IEX fallback failed: {recent_error}"
    return symbol, sorted(historical + recent, key=lambda bar: bar.day), None


def ingest_prices(
    bundle: dict[str, Any],
    start: date = ANALYSIS_START,
    end: date = DEFAULT_END,
    symbols: Iterable[str] | None = None,
    workers: int = 4,
) -> dict[str, int]:
    intervals = membership_intervals(bundle, start, end)
    requested = sorted(set(symbols or (interval.symbol for interval in intervals)))
    wanted = sorted({price_symbol(bundle, symbol) for symbol in requested})
    ensure_tables()
    persist_membership(bundle)
    print(
        f"price_ingest_start | symbols={len(wanted)} | start={start} | "
        f"end={end} | feeds=sip_then_iex_recent | adjustment=all | workers={workers}"
    )
    successes = failures = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(_fetch_one_symbol, symbol, start, end): symbol
            for symbol in wanted
        }
        for index, future in enumerate(as_completed(futures), start=1):
            symbol, bars, error = future.result()
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if bars:
                        for offset in range(0, len(bars), SLICE_SIZE):
                            psycopg2.extras.execute_values(
                                cur,
                                f"""
                                INSERT INTO {PRICE_TABLE}
                                    (symbol, date, open, high, low, close, volume, source)
                                VALUES %s
                                ON CONFLICT (symbol, date, source) DO UPDATE SET
                                    open=EXCLUDED.open, high=EXCLUDED.high,
                                    low=EXCLUDED.low, close=EXCLUDED.close,
                                    volume=EXCLUDED.volume
                                """,
                                [
                                    (
                                        bar.symbol,
                                        bar.day,
                                        bar.open,
                                        bar.high,
                                        bar.low,
                                        bar.close,
                                        bar.volume,
                                        bar.source,
                                    )
                                    for bar in bars[offset : offset + SLICE_SIZE]
                                ],
                            )
                        cur.execute(
                            f"""
                            INSERT INTO {META_TABLE}
                                (symbol, row_count, first_date, last_date, source_mix, status, error)
                            VALUES (%s,%s,%s,%s,%s,'ok',NULL)
                            ON CONFLICT (symbol) DO UPDATE SET
                                row_count=EXCLUDED.row_count,
                                first_date=EXCLUDED.first_date,
                                last_date=EXCLUDED.last_date,
                                source_mix=EXCLUDED.source_mix,
                                status='ok', error=NULL, fetched_at=NOW()
                            """,
                            (
                                symbol,
                                len(bars),
                                bars[0].day,
                                bars[-1].day,
                                ",".join(sorted({bar.source for bar in bars})),
                            ),
                        )
                        successes += 1
                        print(
                            f"price_ingest | {index}/{len(wanted)} | {symbol} | "
                            f"rows={len(bars)} | first={bars[0].day} | last={bars[-1].day}"
                        )
                    else:
                        cur.execute(
                            f"""
                            INSERT INTO {META_TABLE}
                                (symbol, row_count, first_date, last_date, source_mix, status, error)
                            VALUES (%s,0,NULL,NULL,NULL,'failed',%s)
                            ON CONFLICT (symbol) DO UPDATE SET
                                row_count=0, first_date=NULL, last_date=NULL, source_mix=NULL,
                                status='failed', error=EXCLUDED.error, fetched_at=NOW()
                            """,
                            (symbol, error or "empty Alpaca response"),
                        )
                        failures += 1
                        print(f"price_ingest | {index}/{len(wanted)} | {symbol} | ERROR={error}")
    print(f"price_ingest_complete | successes={successes} | failures={failures}")
    return {"successes": successes, "failures": failures}


def price_coverage_report(
    bundle: dict[str, Any],
    start: date = ANALYSIS_START,
    end: date = DEFAULT_END,
) -> bool:
    intervals = membership_intervals(bundle, start, end)
    expected_by_symbol: dict[str, set[date]] = defaultdict(set)
    for interval in intervals:
        expected_by_symbol[price_symbol(bundle, interval.symbol)].update(
            expected_sessions(interval.start, interval.end)
        )
    valid = True
    print("=== A2 DAILY OHLCV COVERAGE ===")
    print(
        "symbol | expected_active_sessions | rows | first_date | last_date | "
        "nulls | missing_sessions | source_mix"
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in sorted(expected_by_symbol):
                cur.execute(
                    f"""
                    SELECT date, open, high, low, close, volume, source
                    FROM {PRICE_TABLE}
                    WHERE symbol=%s AND source = ANY(%s)
                    ORDER BY date
                    """,
                    (symbol, list(PRICE_SOURCES)),
                )
                rows = cur.fetchall()
                dates = {row[0] for row in rows}
                expected = expected_by_symbol[symbol]
                missing = sorted(expected - dates)
                nulls = sum(1 for row in rows for value in row[1:6] if value is None)
                source_mix = ",".join(sorted({row[6] for row in rows}))
                first = min(dates) if dates else None
                last = max(dates) if dates else None
                print(
                    f"{symbol} | {len(expected)} | {len(rows)} | {first} | {last} | "
                    f"{nulls} | {len(missing)} | {source_mix}"
                )
                if missing:
                    print(f"  missing_sessions={','.join(map(str, missing[:12]))}")
                if not rows or nulls or missing or len(dates) != len(rows):
                    valid = False
    print(f"price_coverage_gate | {'PASS' if valid else 'STOP'}")
    return valid


def earnings_audit() -> bool:
    """Audit the existing 17-stock earnings dataset without modifying it."""
    from analysis.bot2_data_pipeline import EARNINGS_SYMBOLS

    valid = True
    print("=== A3 EXISTING EARNINGS DATA AUDIT ===")
    print("symbol | rows | null_required | null_eps | manual_rows | cost_manual_excluded")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in EARNINGS_SYMBOLS:
                cur.execute(
                    """
                    SELECT COUNT(*),
                           COUNT(*) FILTER (
                               WHERE fiscal_date_ending IS NULL OR report_time IS NULL OR report_time=''
                           ),
                           COUNT(*) FILTER (
                               WHERE reported_eps IS NULL OR estimated_eps IS NULL
                           ),
                           COUNT(*) FILTER (WHERE source='manual')
                    FROM bot2_earnings_dates
                    WHERE symbol=%s AND reported_date >= %s
                    """,
                    (symbol, ANALYSIS_START),
                )
                rows, required_nulls, eps_nulls, manual_rows = cur.fetchone()
                cost_excluded = symbol == "COST" and manual_rows > 0
                print(
                    f"{symbol} | {rows} | {required_nulls} | {eps_nulls} | "
                    f"{manual_rows} | {cost_excluded}"
                )
                if not rows or required_nulls:
                    valid = False
            cur.execute(
                """
                SELECT COUNT(*)
                FROM bot2_earnings_dates
                WHERE symbol='COST' AND source='manual'
            """
            )
            cost_manual_rows = int(cur.fetchone()[0])
    print(f"earnings_cost_manual_rows | {cost_manual_rows}")
    print("earnings_cost_rule | manual COST rows excluded because surprise is unknown")
    print(f"earnings_audit_gate | {'PASS' if valid else 'STOP'}")
    return valid


def run_a1_gate(
    bundle: dict[str, Any],
    start: date = ANALYSIS_START,
    end: date = DEFAULT_END,
    require_prices: bool = True,
) -> bool:
    print("=== BOT 2 V3 A1 HARD GATE ===")
    valid = True
    coverage_end = source_coverage_end(bundle)
    if coverage_end < end:
        print(f"a1_source_freshness | STOP | coverage_end={coverage_end} requested_end={end}")
        valid = False
    else:
        print(f"a1_source_freshness | PASS | coverage_end={coverage_end} requested_end={end}")
    try:
        membership_report(bundle, start, end)
        intervals = membership_intervals(bundle, start, end)
        if not intervals:
            print("a1_membership_reconstruction | STOP | no intervals")
            valid = False
        else:
            print(
                f"a1_membership_reconstruction | PASS | intervals={len(intervals)} "
                f"symbols={len({item.symbol for item in intervals})}"
            )
    except RuntimeError as exc:
        print(f"a1_membership_reconstruction | STOP | {exc}")
        valid = False
    if require_prices:
        try:
            valid = price_coverage_report(bundle, start, end) and valid
        except Exception as exc:
            print(f"a2_price_coverage | STOP | {type(exc).__name__}: {exc}")
            valid = False
    else:
        print("a2_price_coverage | NOT_RUN | price ingestion not requested")
    print(f"A1_HARD_GATE | {'PASS' if valid else 'STOP'}")
    return valid


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_BUNDLE)
    parser.add_argument("--start", type=date.fromisoformat, default=ANALYSIS_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--ingest-prices", action="store_true")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-earnings", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    bundle = load_bundle(args.source)
    if args.ingest_prices:
        ingest_prices(bundle, args.start, args.end, args.symbols, args.workers)
    ensure_tables()
    persist_membership(bundle)
    gate = run_a1_gate(
        bundle,
        args.start,
        args.end,
        require_prices=not args.skip_prices,
    )
    earnings_ok = True if args.skip_earnings else earnings_audit()
    return 0 if gate and earnings_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())