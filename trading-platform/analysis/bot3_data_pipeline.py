#!/usr/bin/env python3
"""Bot 3 inflation-hedge data ingest and Alpaca capability check.

This is a read-only verification tool apart from its dedicated GLD/SLV
validation table. It deliberately does not import a strategy, runner,
execution engine, migration utility, or any ETF-fleet code.

Sources:
  * Yahoo Finance supplies GLD and SLV daily validation history.
  * BTC and ETH checkpoints are read from the already-verified
    crypto_historical_prices Yahoo table.
  * Alpaca calls below are GET-only and never place an order.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import psycopg2.extras

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "trading-platform") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading-platform"))

from db.postgres import get_conn  # noqa: E402

TABLE_NAME = "bot3_inflation_hedge_prices"
YAHOO_SYMBOLS = ("GLD", "SLV")
ALL_SYMBOLS = ("BTC", "ETH", "GLD", "SLV")
START_DATE = date(2021, 1, 1)
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL CHECK (symbol IN ('GLD', 'SLV')),
    date DATE NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL DEFAULT 'yahoo' CHECK (source = 'yahoo'),
    CONSTRAINT bot3_inflation_hedge_prices_uq UNIQUE (symbol, date, source)
);
CREATE INDEX IF NOT EXISTS idx_bot3_inflation_hedge_prices_symbol_date
    ON {TABLE_NAME} (symbol, date DESC);
"""


def _unix_midnight(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def _yahoo_daily(symbol: str, end_exclusive: date) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "period1": _unix_midnight(START_DATE),
            "period2": _unix_midnight(end_exclusive),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    request = Request(
        f"{YAHOO_CHART_URL}/{symbol}?{query}",
        headers={"User-Agent": "Bot3-Inflation-Hedge-Validation/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo {symbol}: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"Yahoo {symbol}: empty response")
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    columns = {name: quote_data.get(name) or [] for name in ("open", "high", "low", "close", "volume")}
    bars: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        bar_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        values = {
            name: columns[name][index] if index < len(columns[name]) else None
            for name in columns
        }
        if bar_date < START_DATE or bar_date >= end_exclusive:
            continue
        if any(value is None for value in values.values()):
            raise RuntimeError(f"Yahoo {symbol}: null OHLCV value on {bar_date}")
        bars.append(
            {
                "symbol": symbol,
                "date": bar_date,
                **{name: float(value) for name, value in values.items()},
                "source": "yahoo",
            }
        )
    return sorted(bars, key=lambda row: row["date"])


def ingest_metals() -> dict[str, int]:
    """Persist only Yahoo GLD/SLV bars into the dedicated Bot 3 table."""
    ensure_table()
    counts: dict[str, int] = {}
    end_exclusive = datetime.now(timezone.utc).date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in YAHOO_SYMBOLS:
                bars = _yahoo_daily(symbol, end_exclusive)
                if not bars:
                    raise RuntimeError(f"Yahoo {symbol}: no complete bars returned")
                psycopg2.extras.execute_values(
                    cur,
                    f"""
                    INSERT INTO {TABLE_NAME}
                        (symbol, date, open, high, low, close, volume, source)
                    VALUES %s
                    ON CONFLICT (symbol, date, source) DO UPDATE SET
                        open = EXCLUDED.open, high = EXCLUDED.high,
                        low = EXCLUDED.low, close = EXCLUDED.close,
                        volume = EXCLUDED.volume
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
                        )
                        for bar in bars
                    ],
                )
                counts[symbol] = len(bars)
    return counts


def ensure_table() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)


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


def _nyse_holidays(year: int) -> set[date]:
    """Major NYSE closures relevant to the 2021-present validation window."""
    # The NYSE observed a national day of mourning for former President
    # Jimmy Carter on 2025-01-09. It is not a recurring federal holiday.
    holidays = {
        _observed_fixed(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),   # Presidents' Day
        _last_weekday(year, 5, 0),     # Memorial Day
        _observed_fixed(year, 6, 19),  # Juneteenth
        _observed_fixed(year, 7, 4),   # Independence Day
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed(year, 12, 25), # Christmas
    }
    if year == 2025:
        holidays.add(date(2025, 1, 9))
    # Good Friday is an NYSE closure but not a federal holiday.
    easter = _easter_sunday(year)
    holidays.add(easter - timedelta(days=2))
    return holidays


def _easter_sunday(year: int) -> date:
    """Gregorian Easter, using the Meeus/Jones/Butcher algorithm."""
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


def _expected_equity_days(start: date, end: date) -> set[date]:
    days: set[date] = set()
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in _nyse_holidays(cursor.year):
            days.add(cursor)
        cursor += timedelta(days=1)
    return days


def integrity_report() -> bool:
    """Print GLD/SLV integrity and stop on nulls or unexplained gaps."""
    valid = True
    print("symbol | row_count | first_date | last_date | null_count | calendar_gaps")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in YAHOO_SYMBOLS:
                cur.execute(
                    f"""
                    SELECT date, open, high, low, close, volume
                    FROM {TABLE_NAME}
                    WHERE symbol=%s AND source='yahoo'
                    ORDER BY date
                    """,
                    (symbol,),
                )
                rows = cur.fetchall()
                dates = [row[0] for row in rows]
                expected = _expected_equity_days(dates[0], dates[-1]) if dates else set()
                missing = sorted(expected - set(dates))
                null_count = sum(1 for row in rows for value in row[1:] if value is None)
                item = {
                    "symbol": symbol,
                    "row_count": len(rows),
                    "first_date": dates[0].isoformat() if dates else None,
                    "last_date": dates[-1].isoformat() if dates else None,
                    "null_count": null_count,
                    "calendar_gaps": len(missing),
                }
                print(
                    f"{item['symbol']} | {item['row_count']} | {item['first_date']} | "
                    f"{item['last_date']} | {item['null_count']} | {item['calendar_gaps']}"
                )
                if (
                    item["first_date"] != START_DATE.isoformat()
                    or item["row_count"] < 1300
                    or item["null_count"] != 0
                    or missing
                ):
                    valid = False
                    if missing:
                        print(f"  unexplained missing trading dates: {', '.join(map(str, missing[:12]))}")
    print(f"integrity_gate: {'PASS' if valid else 'STOP'}")
    return valid


def _close_from_table(table: str, symbol: str, checkpoint: date) -> float | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT close FROM {table} WHERE symbol=%s AND date=%s AND source='yahoo'",
                (symbol, checkpoint),
            )
            row = cur.fetchone()
    return float(row[0]) if row else None


def inflation_window_check() -> None:
    print("four-asset inflation-window closes (Yahoo source):")
    checkpoints = (date(2021, 6, 1), date(2022, 6, 1), date(2022, 12, 1))
    for symbol in ALL_SYMBOLS:
        table = "crypto_historical_prices" if symbol in ("BTC", "ETH") else TABLE_NAME
        values = [_close_from_table(table, symbol, checkpoint) for checkpoint in checkpoints]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT date, close FROM {table} WHERE symbol=%s AND source='yahoo' ORDER BY date DESC LIMIT 1",
                    (symbol,),
                )
                latest = cur.fetchone()
        formatted = " | ".join(
            f"{checkpoint}={value:.6f}" if value is not None else f"{checkpoint}=MISSING"
            for checkpoint, value in zip(checkpoints, values)
        )
        latest_text = f"{latest[0]}={float(latest[1]):.6f}" if latest else "MISSING"
        print(f"  {symbol} | {formatted} | latest={latest_text}")


def _alpaca_get(path: str, params: dict[str, str] | None = None) -> Any:
    key = os.environ.get("ALPACA_JEROME_API_KEY")
    secret = os.environ.get("ALPACA_JEROME_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("ALPACA_JEROME_API_KEY and ALPACA_JEROME_SECRET_KEY are required")
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{ALPACA_BASE_URL}{path}{query}",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Alpaca GET {path} failed ({exc.code}): {body}") from exc


def alpaca_capability_check() -> None:
    print("Alpaca Jerome account: raw account record")
    account = _alpaca_get("/v2/account")
    print(json.dumps(account, indent=2, sort_keys=True))

    print("Alpaca asset records: BTC/USD, ETH/USD, GLD, SLV")
    for symbol in ("BTC/USD", "ETH/USD", "GLD", "SLV"):
        print(f"--- {symbol} ---")
        print(json.dumps(_alpaca_get(f"/v2/assets/{quote(symbol, safe='')}"), indent=2, sort_keys=True))

    print("Alpaca crypto asset listing (raw, filtered to BTC/USD and ETH/USD)")
    assets = _alpaca_get("/v2/assets", {"asset_class": "crypto"})
    for asset in assets:
        if asset.get("symbol") in ("BTC/USD", "ETH/USD", "BTCUSD", "ETHUSD"):
            print(json.dumps(asset, indent=2, sort_keys=True))

    positions = _alpaca_get("/v2/positions")
    orders = _alpaca_get("/v2/orders", {"status": "open", "direction": "asc", "limit": "500"})
    print("Alpaca current positions (raw)")
    print(json.dumps(positions, indent=2, sort_keys=True))
    print("Alpaca open orders (raw)")
    print(json.dumps(orders, indent=2, sort_keys=True))

    clock = _alpaca_get("/v2/clock")
    print("Alpaca equity clock (raw)")
    print(json.dumps(clock, indent=2, sort_keys=True))

    print("Alpaca crypto capability answer:")
    print("  BTC/USD and ETH/USD tradeability: use each returned asset's tradable/status fields above.")
    print("  Crypto order types: market, limit, and stop_limit are supported; standalone STOP orders are not.")
    print("  Therefore BTC/ETH protective exits cannot be broker-held STOP orders; they require software-managed monitoring.")
    print("  Crypto is long-only: shorting and margin are not available for these crypto assets.")
    print("  Crypto is 24/7. GLD/SLV are US-equity market-hours assets; equity clock is printed above.")
    print("  GLD/SLV whole-share GTC stops: supported by the equity order model when assets are tradable; no order was submitted.")
    print("  Fee structure: the account/asset API does not return a fee schedule; no fee value is inferred by this read-only check.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingest", action="store_true", help="Ingest Yahoo GLD/SLV history")
    parser.add_argument("--verify", action="store_true", help="Run integrity and four-asset sanity checks")
    parser.add_argument("--alpaca-check", action="store_true", help="Run read-only Alpaca account/capability checks")
    parser.add_argument("--print-ddl", action="store_true", help="Print the dedicated table DDL")
    args = parser.parse_args()
    if not any((args.ingest, args.verify, args.alpaca_check, args.print_ddl)):
        parser.error("choose --ingest, --verify, --alpaca-check, or --print-ddl")
    if args.print_ddl or args.ingest:
        print(f"CREATE TABLE DDL for {TABLE_NAME}:")
        print(CREATE_TABLE_SQL.strip())
    if args.ingest:
        print("Yahoo metals ingest (source=yahoo; GLD/SLV only):")
        for symbol, count in ingest_metals().items():
            print(f"  {symbol} | fetched_complete_bars={count}")
    if args.verify:
        if not integrity_report():
            print("STOP: GLD/SLV integrity failed; four-asset sanity check was not run.")
            return 2
        inflation_window_check()
    if args.alpaca_check:
        alpaca_capability_check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())