#!/usr/bin/env python3
"""Bot 2 earnings and price-data ingestion/validation.

This module is deliberately isolated from all strategies, runners, broker
execution, the ETF fleet, Bot 3, and migration utilities.  It creates and
populates only the two dedicated Bot 2 tables when --ingest is requested.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg2.extras

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402

EARNINGS_TABLE = "bot2_earnings_dates"
PRICES_TABLE = "bot2_prices"
START_DATE = date(2021, 1, 1)
STOCKS = ("BRK-B", "BLK", "V", "MA", "PYPL", "LMT", "RTX", "NVDA", "TSM", "JPM")
ETFS = ("SCHD", "VYM", "DGRO", "VIG", "HDV", "VYMI", "SPHD", "VNQ", "PFF", "SGOV")
ALL_SYMBOLS = STOCKS + ETFS
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

EARNINGS_DDL = f"""
CREATE TABLE IF NOT EXISTS {EARNINGS_TABLE} (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL CHECK (symbol IN ({", ".join(repr(s) for s in STOCKS)})),
    reported_date       DATE NOT NULL,
    fiscal_date_ending  DATE,
    reported_eps        DOUBLE PRECISION,
    estimated_eps       DOUBLE PRECISION,
    surprise            DOUBLE PRECISION,
    surprise_percentage DOUBLE PRECISION,
    report_time         TEXT,
    CONSTRAINT bot2_earnings_dates_uq
        UNIQUE (symbol, fiscal_date_ending, reported_date)
);
CREATE INDEX IF NOT EXISTS idx_bot2_earnings_symbol_date
    ON {EARNINGS_TABLE} (symbol, reported_date);
"""

PRICES_DDL = f"""
CREATE TABLE IF NOT EXISTS {PRICES_TABLE} (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL CHECK (symbol IN ({", ".join(repr(s) for s in ALL_SYMBOLS)})),
    date        DATE NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL,
    source      TEXT NOT NULL DEFAULT 'yahoo' CHECK (source = 'yahoo'),
    asset_type  TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    CONSTRAINT bot2_prices_uq UNIQUE (symbol, date, source)
);
CREATE INDEX IF NOT EXISTS idx_bot2_prices_symbol_date
    ON {PRICES_TABLE} (symbol, date DESC);
"""


def _unix_midnight(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def _json_get(url: str, params: dict[str, Any], user_agent: str) -> dict[str, Any]:
    query = urlencode(params)
    request = Request(
        f"{url}?{query}",
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_tables() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(EARNINGS_DDL)
            cur.execute(PRICES_DDL)


def _number(value: Any) -> float | None:
    if value in (None, "", "None", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fetch_earnings(symbol: str) -> list[dict[str, Any]]:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY is required")
    payload = _json_get(
        ALPHA_VANTAGE_URL,
        {"function": "EARNINGS", "symbol": symbol, "apikey": key},
        "Bot2-Earnings-Pipeline/1.0",
    )
    if payload.get("Note") or payload.get("Information") or payload.get("Error Message"):
        raise RuntimeError(
            f"Alpha Vantage {symbol}: "
            f"{payload.get('Note') or payload.get('Information') or payload.get('Error Message')}"
        )
    rows: list[dict[str, Any]] = []
    for item in payload.get("quarterlyEarnings") or []:
        reported_date = _parse_date(item.get("reportedDate"))
        if reported_date is None or reported_date < START_DATE:
            continue
        rows.append(
            {
                "symbol": symbol,
                "reported_date": reported_date,
                "fiscal_date_ending": _parse_date(item.get("fiscalDateEnding")),
                "reported_eps": _number(item.get("reportedEPS")),
                "estimated_eps": _number(item.get("estimatedEPS")),
                "surprise": _number(item.get("surprise")),
                "surprise_percentage": _number(item.get("surprisePercentage")),
                "report_time": item.get("reportTime") or None,
            }
        )
    return rows


def ingest_earnings() -> dict[str, int]:
    counts: dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for index, symbol in enumerate(STOCKS):
                if index:
                    time.sleep(12.5)
                rows = fetch_earnings(symbol)
                if not rows:
                    raise RuntimeError(f"Alpha Vantage {symbol}: no qualifying quarterly rows")
                psycopg2.extras.execute_values(
                    cur,
                    f"""
                    INSERT INTO {EARNINGS_TABLE}
                        (symbol, reported_date, fiscal_date_ending, reported_eps,
                         estimated_eps, surprise, surprise_percentage, report_time)
                    VALUES %s
                    ON CONFLICT (symbol, fiscal_date_ending, reported_date)
                    DO UPDATE SET
                        reported_eps = EXCLUDED.reported_eps,
                        estimated_eps = EXCLUDED.estimated_eps,
                        surprise = EXCLUDED.surprise,
                        surprise_percentage = EXCLUDED.surprise_percentage,
                        report_time = EXCLUDED.report_time
                    """,
                    [
                        (
                            row["symbol"],
                            row["reported_date"],
                            row["fiscal_date_ending"],
                            row["reported_eps"],
                            row["estimated_eps"],
                            row["surprise"],
                            row["surprise_percentage"],
                            row["report_time"],
                        )
                        for row in rows
                    ],
                )
                counts[symbol] = len(rows)
                print(f"earnings_ingest | {symbol} | fetched={len(rows)}")
    return counts


def fetch_yahoo_daily(symbol: str, end_exclusive: date) -> list[dict[str, Any]]:
    payload = _json_get(
        f"{YAHOO_CHART_URL}/{symbol}",
        {
            "period1": _unix_midnight(START_DATE),
            "period2": _unix_midnight(end_exclusive),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
        "Bot2-Price-Pipeline/1.0",
    )
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo {symbol}: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo {symbol}: empty response")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    columns = {name: quote.get(name) or [] for name in ("open", "high", "low", "close", "volume")}
    asset_type = "stock" if symbol in STOCKS else "etf"
    bars: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        bar_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        if bar_date < START_DATE or bar_date >= end_exclusive:
            continue
        values = {
            name: columns[name][index] if index < len(columns[name]) else None
            for name in columns
        }
        if any(value is None for value in values.values()):
            raise RuntimeError(f"Yahoo {symbol}: null OHLCV value on {bar_date}")
        bars.append(
            {
                "symbol": symbol,
                "date": bar_date,
                **{name: float(value) for name, value in values.items()},
                "source": "yahoo",
                "asset_type": asset_type,
            }
        )
    return sorted(bars, key=lambda row: row["date"])


def ingest_prices() -> dict[str, int]:
    counts: dict[str, int] = {}
    end_exclusive = date.today() + timedelta(days=1)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in ALL_SYMBOLS:
                bars = fetch_yahoo_daily(symbol, end_exclusive)
                if not bars:
                    raise RuntimeError(f"Yahoo {symbol}: no complete bars returned")
                psycopg2.extras.execute_values(
                    cur,
                    f"""
                    INSERT INTO {PRICES_TABLE}
                        (symbol, date, open, high, low, close, volume, source, asset_type)
                    VALUES %s
                    ON CONFLICT (symbol, date, source)
                    DO UPDATE SET
                        open = EXCLUDED.open, high = EXCLUDED.high,
                        low = EXCLUDED.low, close = EXCLUDED.close,
                        volume = EXCLUDED.volume, asset_type = EXCLUDED.asset_type
                    """,
                    [
                        (
                            bar["symbol"],
                            bar["date"],
                            bar["open"],
                            bar["high"],
                            bar["low"],
                            bar["close"],
                            bar["volume"],
                            bar["source"],
                            bar["asset_type"],
                        )
                        for bar in bars
                    ],
                )
                counts[symbol] = len(bars)
                print(f"price_ingest | {symbol} | fetched={len(bars)}")
    return counts


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (ordinal - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed_fixed(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


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


def _nyse_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_fixed(year, 6, 19),
        _observed_fixed(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed(year, 12, 25),
        _easter_sunday(year) - timedelta(days=2),
    }
    if year == 2025:
        holidays.add(date(2025, 1, 9))
    return holidays


def _expected_trading_days(first: date, last: date) -> set[date]:
    expected: set[date] = set()
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5 and cursor not in _nyse_holidays(cursor.year):
            expected.add(cursor)
        cursor += timedelta(days=1)
    return expected


def integrity_report() -> bool:
    valid = True
    print("symbol | row_count | first_date | last_date | null_count | unexplained_gaps")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in ALL_SYMBOLS:
                cur.execute(
                    f"""
                    SELECT date, open, high, low, close, volume
                    FROM {PRICES_TABLE}
                    WHERE symbol=%s AND source='yahoo'
                    ORDER BY date
                    """,
                    (symbol,),
                )
                rows = cur.fetchall()
                dates = [row[0] for row in rows]
                expected = _expected_trading_days(dates[0], dates[-1]) if dates else set()
                missing = sorted(expected - set(dates))
                null_count = sum(1 for row in rows for value in row[1:] if value is None)
                print(
                    f"{symbol} | {len(rows)} | "
                    f"{dates[0] if dates else None} | {dates[-1] if dates else None} | "
                    f"{null_count} | {len(missing)}"
                )
                if not dates or dates[0] != date(2021, 1, 4) or null_count or missing:
                    valid = False
                    if missing:
                        print(f"  unexplained_gaps={', '.join(map(str, missing[:20]))}")
    print(f"integrity_gate | {'PASS' if valid else 'STOP'}")
    return valid


def earnings_report_time_breakdown() -> None:
    print("symbol | post_market | pre_market | unknown_other")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in STOCKS:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE LOWER(COALESCE(report_time, '')) = 'post-market'),
                        COUNT(*) FILTER (WHERE LOWER(COALESCE(report_time, '')) = 'pre-market'),
                        COUNT(*) FILTER (
                            WHERE LOWER(COALESCE(report_time, '')) NOT IN ('post-market', 'pre-market')
                        )
                    FROM {EARNINGS_TABLE}
                    WHERE symbol=%s
                    """,
                    (symbol,),
                )
                post_market, pre_market, unknown_other = cur.fetchone()
                print(f"{symbol} | {post_market} | {pre_market} | {unknown_other}")


def _nearest_price(cur: Any, symbol: str, reported_date: date) -> tuple[date, int] | None:
    cur.execute(
        f"""
        SELECT date, ABS(date - %s) AS distance
        FROM {PRICES_TABLE}
        WHERE symbol=%s AND source='yahoo'
          AND date BETWEEN %s AND %s
        ORDER BY distance, date
        LIMIT 1
        """,
        (reported_date, symbol, reported_date - timedelta(days=3), reported_date + timedelta(days=3)),
    )
    row = cur.fetchone()
    return (row[0], int(row[1])) if row else None


def earnings_price_crosscheck() -> bool:
    mismatches: list[tuple[str, date]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in STOCKS:
                cur.execute(
                    f"SELECT reported_date FROM {EARNINGS_TABLE} WHERE symbol=%s ORDER BY reported_date",
                    (symbol,),
                )
                for (reported_date,) in cur.fetchall():
                    nearest = _nearest_price(cur, symbol, reported_date)
                    if nearest is None:
                        mismatches.append((symbol, reported_date))
    print("earnings_price_mismatches")
    if mismatches:
        for symbol, reported_date in mismatches:
            print(f"  {symbol} | reported_date={reported_date} | no_price_within_3_days")
    else:
        print("  NONE")
    return not mismatches


def sanity_samples() -> None:
    samples = (("NVDA", date(2024, 5, 22)), ("JPM", date(2024, 4, 12)), ("LMT", date(2024, 4, 23)))
    print("symbol | report_date | prior_close | next_session | next_open | gap_pct")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol, report_date in samples:
                cur.execute(
                    f"""
                    SELECT date, close FROM {PRICES_TABLE}
                    WHERE symbol=%s AND date < %s AND source='yahoo'
                    ORDER BY date DESC LIMIT 1
                    """,
                    (symbol, report_date),
                )
                prior = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT date, open FROM {PRICES_TABLE}
                    WHERE symbol=%s AND date > %s AND source='yahoo'
                    ORDER BY date ASC LIMIT 1
                    """,
                    (symbol, report_date),
                )
                following = cur.fetchone()
                gap = ((float(following[1]) / float(prior[1])) - 1) * 100 if prior and following else None
                print(
                    f"{symbol} | {report_date} | "
                    f"{prior[1] if prior else None} | {following[0] if following else None} | "
                    f"{following[1] if following else None} | "
                    f"{gap:.2f}%"
                    if gap is not None
                    else f"{symbol} | {report_date} | missing checkpoint"
                )


def earnings_counts() -> None:
    print("earnings_rows_per_symbol")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in STOCKS:
                cur.execute(f"SELECT COUNT(*) FROM {EARNINGS_TABLE} WHERE symbol=%s", (symbol,))
                print(f"{symbol} | {cur.fetchone()[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--print-ddl", action="store_true")
    args = parser.parse_args()
    if not any((args.ingest, args.verify, args.print_ddl)):
        parser.error("choose --ingest, --verify, or --print-ddl")

    if args.print_ddl:
        print(f"CREATE TABLE {EARNINGS_TABLE}:")
        print(EARNINGS_DDL.strip())
        print(f"CREATE TABLE {PRICES_TABLE}:")
        print(PRICES_DDL.strip())

    if args.ingest:
        ensure_tables()
        print("Bot 2 earnings ingest: Alpha Vantage, 10 paced requests")
        ingest_earnings()
        print("Bot 2 price ingest: Yahoo Chart API, 20 symbols")
        ingest_prices()

    if args.verify:
        ensure_tables()
        if not integrity_report():
            print("STOP: price integrity failed; earnings cross-check and sanity checks skipped.")
            return 2
        earnings_counts()
        earnings_report_time_breakdown()
        if not earnings_price_crosscheck():
            print("STOP: earnings/price cross-check failed.")
            return 3
        sanity_samples()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())