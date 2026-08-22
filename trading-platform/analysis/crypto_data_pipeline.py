#!/usr/bin/env python3
"""Bot 4 crypto data pipeline — validation history and live-paper connectivity.

This module is intentionally standalone and must be invoked explicitly.

Data-source boundary:
  * Yahoo Finance is the validation source. Its daily history is persisted in
    crypto_historical_prices with source='yahoo'.
  * Kraken public OHLC via ccxt is the live paper feed. Connectivity checks are
    read-only and are never persisted here.

This module does not import paper_engine.py, strategy code, ETF code, migration
code, or runner.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg2.extras

_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402
from analysis.bot4_crypto_universe import (  # noqa: E402
    BOT4_CRYPTO_SYMBOLS,
    BOT4_VALIDATION_START,
    KRAKEN_SYMBOLS,
    YAHOO_SYMBOLS,
)

TABLE_NAME = "crypto_historical_prices"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL DEFAULT 'yahoo' CHECK (source = 'yahoo'),
    CONSTRAINT crypto_historical_prices_uq UNIQUE (symbol, date, source)
);
CREATE INDEX IF NOT EXISTS idx_crypto_historical_prices_symbol_date
    ON {TABLE_NAME} (symbol, date DESC);
"""


def ensure_table() -> None:
    """Create only the dedicated Bot 4 validation table."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)


def _unix_timestamp(value: datetime) -> int:
    return int(value.timestamp())


def _fetch_yahoo_daily(symbol: str, start: date, end_exclusive: date) -> list[dict[str, Any]]:
    """Fetch Yahoo daily bars, excluding today's potentially incomplete bar."""
    yahoo_symbol = YAHOO_SYMBOLS[symbol]
    params = urlencode(
        {
            "period1": _unix_timestamp(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)),
            "period2": _unix_timestamp(
                datetime.combine(end_exclusive, datetime.min.time(), tzinfo=timezone.utc)
            ),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    request = Request(
        f"{YAHOO_CHART_URL}/{yahoo_symbol}?{params}",
        headers={"User-Agent": "Bot4-Crypto-Validation/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo {symbol}: empty chart response")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    fields = {field: quote.get(field) or [] for field in ("open", "high", "low", "close", "volume")}

    bars: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        values = {field: fields[field][index] if index < len(fields[field]) else None for field in fields}
        bar_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        if bar_date < start or bar_date >= end_exclusive:
            continue
        if any(value is None for value in values.values()):
            raise RuntimeError(f"Yahoo {symbol}: null OHLCV value on {bar_date}")
        bars.append({"symbol": symbol, "date": bar_date, **{k: float(v) for k, v in values.items()}, "source": "yahoo"})

    bars.sort(key=lambda row: row["date"])
    return bars


def ingest_yahoo_history() -> dict[str, int]:
    """Persist Yahoo validation history into the isolated crypto table."""
    latest_complete_date = datetime.now(timezone.utc).date()
    all_counts: dict[str, int] = {}
    ensure_table()

    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in BOT4_CRYPTO_SYMBOLS:
                bars = _fetch_yahoo_daily(symbol, BOT4_VALIDATION_START, latest_complete_date)
                if not bars:
                    raise RuntimeError(f"Yahoo {symbol}: no complete daily bars returned")
                psycopg2.extras.execute_values(
                    cur,
                    f"""
                    INSERT INTO {TABLE_NAME}
                        (symbol, date, open, high, low, close, volume, source)
                    VALUES %s
                    ON CONFLICT (symbol, date, source) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                    """,
                    [
                        (
                            row["symbol"],
                            row["date"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                            row["volume"],
                            row["source"],
                        )
                        for row in bars
                    ],
                )
                all_counts[symbol] = len(bars)
    return all_counts


def _calendar_gaps(dates: list[date]) -> int:
    return sum(1 for previous, current in zip(dates, dates[1:]) if current - previous != timedelta(days=1))


def integrity_report() -> tuple[list[dict[str, Any]], bool]:
    """Print and return the six-symbol validation integrity report."""
    report: list[dict[str, Any]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in BOT4_CRYPTO_SYMBOLS:
                cur.execute(
                    f"""
                    SELECT date, open, high, low, close, volume
                    FROM {TABLE_NAME}
                    WHERE symbol = %s AND source = 'yahoo'
                    ORDER BY date
                    """,
                    (symbol,),
                )
                rows = cur.fetchall()
                dates = [row[0] for row in rows]
                null_count = sum(
                    1 for row in rows for value in row[1:] if value is None
                )
                item = {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": dates[0].isoformat() if dates else None,
                    "last_date": dates[-1].isoformat() if dates else None,
                    "null_count": null_count,
                    "calendar_gaps": _calendar_gaps(dates),
                }
                report.append(item)

    latest_complete_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    valid = True
    print("symbol | row_count | first_date | last_date | null_count | calendar_gaps")
    for item in report:
        print(
            f"{item['symbol']} | {item['row_count']} | {item['first_date']} | "
            f"{item['last_date']} | {item['null_count']} | {item['calendar_gaps']}"
        )
        valid = valid and (
            item["row_count"] >= 2000
            and item["first_date"] == BOT4_VALIDATION_START.isoformat()
            and item["last_date"] is not None
            and item["null_count"] == 0
            and item["calendar_gaps"] == 0
            and item["last_date"] <= latest_complete_date.isoformat()
        )

    print(f"integrity_gate: {'PASS' if valid else 'STOP'}")
    return report, valid


def btc_sanity_check() -> None:
    """Print cycle checkpoints and the observed 2021-to-2022 BTC drawdown."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT date, close
                FROM {TABLE_NAME}
                WHERE symbol = 'BTC' AND source = 'yahoo'
                  AND date IN ('2021-11-08', '2022-11-21')
                ORDER BY date
                """
            )
            checkpoints = cur.fetchall()
            cur.execute(
                f"""
                SELECT date, close
                FROM {TABLE_NAME}
                WHERE symbol = 'BTC' AND source = 'yahoo'
                ORDER BY date DESC
                LIMIT 1
                """
            )
            latest = cur.fetchone()
            cur.execute(
                f"""
                SELECT MAX(close), MIN(close)
                FROM {TABLE_NAME}
                WHERE symbol = 'BTC' AND source = 'yahoo'
                  AND date BETWEEN '2021-11-01' AND '2021-11-30'
                """
            )
            peak, trough = cur.fetchone()
            cur.execute(
                f"""
                SELECT MIN(close)
                FROM {TABLE_NAME}
                WHERE symbol = 'BTC' AND source = 'yahoo'
                  AND date BETWEEN '2022-11-01' AND '2022-12-31'
                """
            )
            bear_low = cur.fetchone()[0]

    print("BTC sanity checkpoints:")
    for checkpoint_date, close in checkpoints:
        print(f"  {checkpoint_date} | close={float(close):.2f}")
    if latest:
        print(f"  {latest[0]} | latest_close={float(latest[1]):.2f}")
    drawdown = ((float(bear_low) / float(peak)) - 1.0) * 100.0 if peak and bear_low else None
    print(
        f"  2021-11 peak close={float(peak):.2f} | "
        f"2022 bear low close={float(bear_low):.2f} | "
        f"drawdown={drawdown:.1f}%"
    )


def kraken_read_check() -> None:
    """Print three current Kraken bars per symbol without database writes."""
    import ccxt

    exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 20000})
    print("Kraken live-paper feed check (public read-only; not stored):")
    for symbol in BOT4_CRYPTO_SYMBOLS:
        kraken_symbol = KRAKEN_SYMBOLS[symbol]
        bars = exchange.fetch_ohlcv(kraken_symbol, timeframe="1d", limit=3)
        if len(bars) < 3:
            raise RuntimeError(f"Kraken {kraken_symbol}: expected 3 bars, received {len(bars)}")
        print(f"  {symbol} ({kraken_symbol})")
        for timestamp, open_price, high, low, close, volume in bars:
            bar_date = datetime.fromtimestamp(timestamp / 1000, timezone.utc).date()
            print(
                f"    {bar_date} | open={open_price} high={high} "
                f"low={low} close={close} volume={volume}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingest", action="store_true", help="Fetch and persist Yahoo validation history")
    parser.add_argument("--verify", action="store_true", help="Print the integrity report and BTC sanity checks")
    parser.add_argument("--kraken-check", action="store_true", help="Print current Kraken bars without storing them")
    parser.add_argument("--print-ddl", action="store_true", help="Print the dedicated table DDL")
    args = parser.parse_args()

    if not any((args.ingest, args.verify, args.kraken_check, args.print_ddl)):
        parser.error("choose at least one of --ingest, --verify, --kraken-check, or --print-ddl")

    if args.print_ddl or args.ingest:
        print(f"CREATE TABLE DDL for {TABLE_NAME}:")
        print(CREATE_TABLE_SQL.strip())

    if args.ingest:
        counts = ingest_yahoo_history()
        print("Yahoo validation ingest (source=yahoo):")
        for symbol, count in counts.items():
            print(f"  {symbol} | fetched_complete_bars={count}")

    if args.verify:
        _, valid = integrity_report()
        if not valid:
            print("STOP: validation data failed the integrity gate; no Kraken check will run.")
            return 2
        btc_sanity_check()

    if args.kraken_check:
        kraken_read_check()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())