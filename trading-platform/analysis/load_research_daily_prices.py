#!/usr/bin/env python3
"""Load the staged daily price CSVs into the isolated Helium research database.

Run from trading-platform/:
    python3 analysis/load_research_daily_prices.py

This is intentionally a one-time, fail-closed loader. It never connects to the
shared application database, never writes to production, and refuses to append
to a populated research_daily_prices table.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
STAGING_DIR = PROJECT_ROOT / ".local" / "staging"
TABLE = "public.research_daily_prices"
EXPECTED_DATABASE = "heliumdb"
EXPECTED_SYMBOLS = {
    "BIL", "BTC-USD", "BWX", "DBA", "DBB", "DBC", "DBE", "ECH", "EEM",
    "EPOL", "ETH-USD", "EWJ", "EWM", "EWT", "EWW", "EWY", "EWZ", "EZA",
    "FXA", "FXE", "FXF", "FXY", "GLD", "GREK", "IEF", "INDA", "QQQ",
    "SGOV", "SLV", "SPY", "TIP", "TLT", "TUR", "UUP", "VNM",
}
CSV_COLUMNS = (
    "date", "open", "high", "low", "close", "adjusted_close", "volume"
)
SUSPECT_ROWS = {
    ("UUP", date(2007, 6, 20)),
    ("UUP", date(2007, 6, 21)),
    ("DBA", date(2007, 1, 12)),
}

sys.path.insert(0, str(PROJECT_ROOT))
from db.research_postgres import get_research_conn  # noqa: E402


def _host_fingerprint(host: str) -> str:
    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        raise RuntimeError("Could not determine a database host for fingerprinting")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _assert_research_target(conn) -> str:
    production_dsn = os.environ.get("NEON_DATABASE_URL", "").strip()
    production_host = urlsplit(production_dsn).hostname if production_dsn else None
    if not production_host:
        raise RuntimeError(
            "NEON_DATABASE_URL is unavailable; cannot compare the production "
            "host fingerprint, so refusing to write"
        )

    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]

    research_host = conn.get_dsn_parameters().get("host", "")
    research_fingerprint = _host_fingerprint(research_host)
    production_fingerprint = _host_fingerprint(production_host)
    print(f"current_database={database}")
    print(f"research_host_fingerprint=sha256:{research_fingerprint}")
    print(f"production_host_fingerprint=sha256:{production_fingerprint}")
    differs = research_fingerprint != production_fingerprint
    print(f"host_differs_from_production={differs}")

    if database != EXPECTED_DATABASE:
        raise RuntimeError(
            f"STOP: connected to {database!r}, not Helium research database "
            f"{EXPECTED_DATABASE!r}; no data written"
        )
    if not differs:
        raise RuntimeError(
            "STOP: research host fingerprint matches production; no data written"
        )
    return research_fingerprint


def _read_staged_rows():
    if not STAGING_DIR.is_dir():
        raise RuntimeError(f"Staging directory is missing: {STAGING_DIR}")

    csv_paths = sorted(STAGING_DIR.glob("*.csv"))
    found_symbols = {path.stem for path in csv_paths}
    missing = sorted(EXPECTED_SYMBOLS - found_symbols)
    extra = sorted(found_symbols - EXPECTED_SYMBOLS)
    if missing or extra or len(csv_paths) != 35:
        raise RuntimeError(
            "Staged CSV inventory mismatch: "
            f"missing={missing}, extra={extra}, csv_count={len(csv_paths)}"
        )

    rows = []
    counts = {}
    first_dates = {}
    last_dates = {}
    seen_keys = set()

    for path in csv_paths:
        symbol = path.stem
        file_rows = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                raise RuntimeError(
                    f"{path.name}: expected CSV columns {CSV_COLUMNS}, "
                    f"got {reader.fieldnames}"
                )

            for line_number, raw in enumerate(reader, start=2):
                try:
                    row_date = date.fromisoformat(raw["date"])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"{path.name}:{line_number}: invalid date {raw.get('date')!r}"
                    ) from exc

                key = (symbol, row_date)
                if key in seen_keys:
                    raise RuntimeError(
                        f"Duplicate staged (symbol, date) pair: {symbol} {row_date}"
                    )
                seen_keys.add(key)

                values = {}
                for csv_name, target_name in (
                    ("open", "open"),
                    ("high", "high"),
                    ("low", "low"),
                    ("close", "close"),
                    ("adjusted_close", "adj_close"),
                    ("volume", "volume"),
                ):
                    text = (raw.get(csv_name) or "").strip()
                    if not text:
                        if target_name == "adj_close":
                            values[target_name] = None
                            continue
                        raise RuntimeError(
                            f"{path.name}:{line_number}: missing {csv_name}"
                        )
                    try:
                        value = Decimal(text)
                    except InvalidOperation as exc:
                        raise RuntimeError(
                            f"{path.name}:{line_number}: invalid {csv_name}={text!r}"
                        ) from exc
                    if not value.is_finite():
                        raise RuntimeError(
                            f"{path.name}:{line_number}: non-finite {csv_name}={text!r}"
                        )
                    values[target_name] = value

                file_rows.append(
                    (
                        symbol,
                        row_date,
                        values["open"],
                        values["high"],
                        values["low"],
                        values["close"],
                        values["adj_close"],
                        values["volume"],
                        f"staged_csv/{path.name}",
                        (
                            "suspect_bad_print"
                            if key in SUSPECT_ROWS
                            else None
                        ),
                    )
                )

        if not file_rows:
            raise RuntimeError(f"{path.name}: no data rows")
        dates = [row[1] for row in file_rows]
        if dates != sorted(dates):
            raise RuntimeError(f"{path.name}: dates are not in ascending order")
        counts[symbol] = len(file_rows)
        first_dates[symbol] = dates[0]
        last_dates[symbol] = dates[-1]
        rows.extend(file_rows)

    staged_suspects = {
        (row[0], row[1]) for row in rows if row[9] == "suspect_bad_print"
    }
    if staged_suspects != SUSPECT_ROWS:
        raise RuntimeError(
            f"Suspect-row inventory mismatch: expected={sorted(SUSPECT_ROWS)}, "
            f"found={sorted(staged_suspects)}"
        )
    return rows, counts, first_dates, last_dates


def _ensure_empty_target_and_schema(cur) -> None:
    cur.execute(f"SELECT to_regclass('{TABLE}')")
    existing_table = cur.fetchone()[0]
    if existing_table is not None:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        existing_rows = cur.fetchone()[0]
        if existing_rows:
            raise RuntimeError(
                f"STOP: {TABLE} already contains {existing_rows} rows; "
                "refusing to modify or append to an existing price table"
            )

    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            adj_close NUMERIC,
            volume NUMERIC NOT NULL,
            source TEXT NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL,
            quality_flag TEXT,
            PRIMARY KEY (symbol, date)
        )
        """
    )

    cur.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'research_daily_prices'
        ORDER BY ordinal_position
        """
    )
    actual_columns = cur.fetchall()
    expected_columns = [
        ("symbol", "text", "NO"),
        ("date", "date", "NO"),
        ("open", "numeric", "NO"),
        ("high", "numeric", "NO"),
        ("low", "numeric", "NO"),
        ("close", "numeric", "NO"),
        ("adj_close", "numeric", "YES"),
        ("volume", "numeric", "NO"),
        ("source", "text", "NO"),
        ("fetched_at", "timestamp with time zone", "NO"),
        ("quality_flag", "text", "YES"),
    ]
    if actual_columns != expected_columns:
        raise RuntimeError(
            f"Unexpected {TABLE} schema; expected={expected_columns}, "
            f"actual={actual_columns}"
        )

    cur.execute(
        """
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'public.research_daily_prices'::regclass
          AND contype = 'p'
        """
    )
    primary_key = cur.fetchone()
    if primary_key is None or primary_key[0] != "PRIMARY KEY (symbol, date)":
        raise RuntimeError(
            f"Unexpected {TABLE} primary key: "
            f"{primary_key[0] if primary_key else None}"
        )


def _verify(cur, expected_counts, first_dates, last_dates) -> None:
    cur.execute(
        """
        SELECT symbol, COUNT(*), MIN(date), MAX(date)
        FROM public.research_daily_prices
        GROUP BY symbol
        ORDER BY symbol
        """
    )
    actual = {
        symbol: (count, min_date, max_date)
        for symbol, count, min_date, max_date in cur.fetchall()
    }
    if set(actual) != set(expected_counts):
        raise RuntimeError(
            f"Loaded symbol set mismatch: expected={sorted(expected_counts)}, "
            f"actual={sorted(actual)}"
        )

    for symbol in sorted(expected_counts):
        actual_count, actual_first, actual_last = actual[symbol]
        expected = (
            expected_counts[symbol],
            first_dates[symbol],
            last_dates[symbol],
        )
        observed = (actual_count, actual_first, actual_last)
        if observed != expected:
            raise RuntimeError(
                f"{symbol}: loaded count/date range {observed} "
                f"does not match staged file {expected}"
            )
        print(
            f"{symbol}: rows={actual_count} first={actual_first} last={actual_last}"
        )

    cur.execute(
        """
        SELECT COUNT(*)
        FROM public.research_daily_prices
        WHERE quality_flag IS NOT NULL
        """
    )
    flagged_count = cur.fetchone()[0]
    cur.execute(
        """
        SELECT symbol, date, quality_flag
        FROM public.research_daily_prices
        WHERE quality_flag IS NOT NULL
        ORDER BY symbol, date
        """
    )
    flagged_rows = {
        (symbol, flagged_date, quality_flag)
        for symbol, flagged_date, quality_flag in cur.fetchall()
    }
    expected_flagged_rows = {
        (symbol, flagged_date, "suspect_bad_print")
        for symbol, flagged_date in SUSPECT_ROWS
    }
    if flagged_count != 3 or flagged_rows != expected_flagged_rows:
        raise RuntimeError(
            f"Flagged-row verification failed: count={flagged_count}, "
            f"rows={sorted(flagged_rows)}"
        )

    cur.execute(
        """
        SELECT COUNT(*) - COUNT(DISTINCT (symbol, date))
        FROM public.research_daily_prices
        """
    )
    duplicate_count = cur.fetchone()[0]
    if duplicate_count != 0:
        raise RuntimeError(f"Found {duplicate_count} duplicate (symbol, date) pairs")

    cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
    total_count = cur.fetchone()[0]
    expected_total = sum(expected_counts.values())
    if total_count != expected_total:
        raise RuntimeError(
            f"Total row count mismatch: expected={expected_total}, actual={total_count}"
        )

    print(f"flagged_rows={flagged_count}")
    print(f"duplicate_symbol_date_pairs={duplicate_count}")
    print(f"total_rows={total_count}")


def main() -> None:
    fetched_at = datetime.now(timezone.utc)
    with get_research_conn() as conn:
        fingerprint = _assert_research_target(conn)
        rows, expected_counts, first_dates, last_dates = _read_staged_rows()
        print(
            f"staged_csv_files={len(expected_counts)} "
            f"staged_rows={len(rows)} research_host_fingerprint=sha256:{fingerprint}"
        )

        with conn.cursor() as cur:
            _ensure_empty_target_and_schema(cur)
            from psycopg2.extras import execute_values

            execute_values(
                cur,
                f"""
                INSERT INTO {TABLE} (
                    symbol, date, open, high, low, close, adj_close, volume,
                    source, fetched_at, quality_flag
                ) VALUES %s
                """,
                [
                    (
                        *row[:9],
                        fetched_at,
                        row[9],
                    )
                    for row in rows
                ],
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                page_size=3000,
            )
            _verify(cur, expected_counts, first_dates, last_dates)

    print("transaction=committed")


if __name__ == "__main__":
    main()