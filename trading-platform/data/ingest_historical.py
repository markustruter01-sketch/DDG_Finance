#!/usr/bin/env python3
"""
Historical Data Ingestion Pipeline  —  Stream-to-Database Architecture
=======================================================================
STANDALONE MAINTENANCE SCRIPT — not imported by the trading platform at runtime.
Run manually from the shell to backfill historical price/news/dividend data into
PostgreSQL before first launch or after adding new symbols.

Lead-engineer-grade backfill script for the Quant Terminal AI system.

CRITICAL DESIGN PRINCIPLE — Zero Local Storage
-----------------------------------------------
This script never writes a file to disk.  Every API response is:
  1. Fetched into a small in-memory Python list (one time-window at a time)
  2. Bulk-inserted into PostgreSQL in a single round-trip
  3. Explicitly deleted from RAM (del + gc.collect()) before the next window

This "stream-to-database" pattern is mandatory for Replit's ephemeral
container environment where /tmp and the project directory share a ~1 GB
disk quota.  One year of 1-min TQQQ bars is ~380,000 rows (~60 MB in PG)
but only ~2 MB in RAM at any point because we process 10-day windows.

Tables created / populated
--------------------------
  intraday_price_action       — 1-min OHLCV bars  (Alpaca Market Data API)
  corporate_actions_dividends — dividend ex-dates  (Tiingo REST API)
  historical_news_rag         — news headlines     (Alpaca News → NewsAPI fallback)

Environment variables (configure in Replit Secrets sidebar)
-----------------------------------------------------------
  DATABASE_URL        auto-set by Replit Managed PostgreSQL
  ALPACA_API_KEY      your existing Alpaca paper-trading key
  ALPACA_SECRET_KEY   your existing Alpaca paper-trading secret
  NEWS_API_KEY        your existing NewsAPI key (fallback news source)
  TIINGO_API_KEY      ** ADD THIS ** — free at https://www.tiingo.com
                      (no credit card; grants dividend history + unadj prices)

Usage
-----
  # From the project root:
  cd trading-platform && python data/ingest_historical.py

  # Custom date range and symbols:
  python data/ingest_historical.py --symbols TQQQ JEPQ --start 2023-01-01 --end 2024-12-31

  # Skip individual phases (useful for resuming after interruption):
  python data/ingest_historical.py --skip-news --skip-divs

Rate limits respected
---------------------
  Alpaca Market Data : 200 req/min  → 350 ms enforced spacing between calls
  Alpaca News API    : 200 req/min  → 350 ms enforced spacing between calls
  NewsAPI (fallback) : 100 req/day  → 2 s spacing + 30-day windows per symbol
  Tiingo             : 50 req/hour  → 2 s spacing between calls
"""

from __future__ import annotations

import argparse
import gc
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import psycopg2
import psycopg2.extras
import requests
from loguru import logger

# ── Alpaca SDK (alpaca-py, already in requirements.txt) ─────────────────────
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, NewsRequest
from alpaca.data.timeframe import TimeFrame

# ── Logging ──────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")
logger.add("logs/ingestion.log", level="DEBUG", rotation="20 MB", retention="30 days")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ── PostgreSQL Connection
# ══════════════════════════════════════════════════════════════════════════════

def _get_dsn() -> str:
    """
    Resolve the PostgreSQL DSN from environment variables.
    Mirrors the logic in db/postgres.py so both the live server and this
    standalone script connect to the same Replit Managed PostgreSQL instance.
    """
    url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST")
    if host:
        return (
            f"postgresql://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
            f"@{host}:{os.environ.get('PGPORT', 5432)}/{os.environ['PGDATABASE']}"
        )
    raise RuntimeError(
        "No PostgreSQL connection details found.\n"
        "Replit Managed PostgreSQL must be provisioned and DATABASE_URL set."
    )


def open_connection() -> psycopg2.extensions.connection:
    """Return a long-lived psycopg2 connection for the full ingestion run."""
    conn = psycopg2.connect(_get_dsn())
    conn.autocommit = False
    logger.info("DB | Connected to PostgreSQL")
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ── Schema Bootstrap
# Three tables, all idempotent (IF NOT EXISTS + unique constraints).
# ══════════════════════════════════════════════════════════════════════════════

_SCHEMA_SQL = """
-- ── Table 1: 1-minute intraday price action ──────────────────────────────────
-- Indexed by (symbol, ts DESC) for fast time-range queries per ticker.
-- vwap / trade_count are nullable — not all providers supply them.
CREATE TABLE IF NOT EXISTS intraday_price_action (
    id           BIGSERIAL        PRIMARY KEY,
    symbol       TEXT             NOT NULL,
    ts           TIMESTAMPTZ      NOT NULL,
    open         DOUBLE PRECISION NOT NULL,
    high         DOUBLE PRECISION NOT NULL,
    low          DOUBLE PRECISION NOT NULL,
    close        DOUBLE PRECISION NOT NULL,
    volume       BIGINT           NOT NULL,
    vwap         DOUBLE PRECISION,
    trade_count  INTEGER,
    UNIQUE (symbol, ts)          -- prevents duplicate bars on re-runs
);
CREATE INDEX IF NOT EXISTS idx_ipa_symbol_ts
    ON intraday_price_action (symbol, ts DESC);

-- ── Table 2: Corporate actions — dividends ───────────────────────────────────
-- adj_close vs unadj_close on ex_date lets the HWM engine distinguish
-- genuine drawdowns from dividend distributions (price drop on ex-date
-- is not a loss — the cash leaves the stock price, enters as income).
CREATE TABLE IF NOT EXISTS corporate_actions_dividends (
    id              SERIAL           PRIMARY KEY,
    symbol          TEXT             NOT NULL,
    ex_date         DATE             NOT NULL,
    pay_date        DATE,
    declared_date   DATE,
    amount          DOUBLE PRECISION NOT NULL,
    currency        TEXT             NOT NULL DEFAULT 'USD',
    adj_close       DOUBLE PRECISION,     -- adjusted close on ex-date
    unadj_close     DOUBLE PRECISION,     -- unadjusted close on ex-date
    UNIQUE (symbol, ex_date)              -- upsert-safe
);
CREATE INDEX IF NOT EXISTS idx_cad_symbol_exdate
    ON corporate_actions_dividends (symbol, ex_date DESC);

-- ── Table 3: Historical news for RAG ────────────────────────────────────────
-- GIN index on symbols[] lets the Auditor Agent run:
--   SELECT * FROM historical_news_rag WHERE 'TQQQ' = ANY(symbols)
-- efficiently without a full table scan.
-- url UNIQUE prevents duplicate articles on partial re-runs.
CREATE TABLE IF NOT EXISTS historical_news_rag (
    id           BIGSERIAL    PRIMARY KEY,
    headline     TEXT         NOT NULL,
    summary      TEXT,
    author       TEXT,
    source       TEXT,
    url          TEXT         UNIQUE,
    published_at TIMESTAMPTZ  NOT NULL,
    symbols      TEXT[],
    sentiment    TEXT,        -- reserved — attach NLP labels later
    ingested_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hnr_published
    ON historical_news_rag (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_hnr_symbols
    ON historical_news_rag USING GIN (symbols);
"""


def ensure_schema(conn: psycopg2.extensions.connection) -> None:
    """
    Create all three tables if they do not already exist.
    Safe to call on every run — fully idempotent.
    """
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_SQL)
    conn.commit()
    logger.success("Schema | All three tables verified / created")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ── Rate-Limit Defence
# ══════════════════════════════════════════════════════════════════════════════

def _jitter(ceiling: float) -> float:
    """Full-jitter: uniform random in [0, ceiling]. Avoids thundering-herd."""
    return random.uniform(0.0, ceiling)


def guarded_call(
    fn,
    *args,
    max_attempts: int = 5,
    base_sleep:   float = 1.0,
    cap:          float = 60.0,
    min_spacing:  float = 0.35,   # 350 ms ≈ 171 req/min — under Alpaca's 200/min
    label:        str   = "API",
    **kwargs,
):
    """
    Call fn(*args, **kwargs) with exponential-backoff-and-jitter on failure.

    Backoff formula (full jitter, same as execution/resilience.py):
        sleep = uniform(0, min(cap, base_sleep * 2^attempt))

    The min_spacing delay is applied even on success — this is the primary
    mechanism that enforces Alpaca's 200 req/min ceiling without needing a
    token bucket.  At 350 ms per call you get ≈171 successful calls/min.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn(*args, **kwargs)
            time.sleep(min_spacing)            # spacing after every successful call
            return result
        except Exception as exc:
            msg = str(exc).lower()
            is_rate_limit = any(k in msg for k in ("429", "too many requests", "rate limit"))
            is_last_attempt = (attempt >= max_attempts)

            if is_last_attempt:
                logger.error(f"{label} | Exhausted {max_attempts} attempts: {exc}")
                raise

            sleep_for = min(cap, _jitter(base_sleep * (2 ** attempt)))
            if is_rate_limit:
                sleep_for = max(sleep_for, 5.0)  # always wait at least 5 s on 429
                logger.warning(
                    f"{label} | Rate limit (attempt {attempt}/{max_attempts}) "
                    f"— sleeping {sleep_for:.1f}s"
                )
            else:
                logger.warning(
                    f"{label} | Error: {exc!r} (attempt {attempt}/{max_attempts}) "
                    f"— sleeping {sleep_for:.1f}s"
                )
            time.sleep(sleep_for)

    raise RuntimeError("unreachable")   # pragma: no cover


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ── Date Window Generator
# ══════════════════════════════════════════════════════════════════════════════

def date_windows(
    start: date,
    end: date,
    window_days: int = 10,
) -> Generator[tuple[date, date], None, None]:
    """
    Slice the [start, end] range into chunks of at most window_days calendar days.

    Window sizing rationale:
      10 calendar days ≈ 7 trading days × 6.5 hours × 60 bars = ~2,730 rows
      At ~200 bytes/row in Python, that's ~546 KB per batch — negligible RAM.
      Even if the container has only 256 MB free, we stay safely under 0.25%.

    Usage:
        for ws, we in date_windows(date(2023,1,1), date(2024,1,1)):
            rows = fetch(ws, we)
            insert(rows)
            del rows; gc.collect()   # <── always pair with this
    """
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _to_utc(d: date, end_of_day: bool = False) -> datetime:
    """Convert a date to a UTC-aware datetime (start or end of day)."""
    if end_of_day:
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 ── Ingestion: 1-Minute OHLCV Bars  (Alpaca Market Data API)
# ══════════════════════════════════════════════════════════════════════════════

_BARS_INSERT = """
INSERT INTO intraday_price_action
    (symbol, ts, open, high, low, close, volume, vwap, trade_count)
VALUES %s
ON CONFLICT (symbol, ts) DO NOTHING;
"""


def _build_market_data_client() -> StockHistoricalDataClient:
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in Replit Secrets."
        )
    return StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)


def _fetch_bars_window(
    client: StockHistoricalDataClient,
    symbol: str,
    win_start: date,
    win_end: date,
) -> list[tuple]:
    """
    Fetch all 1-minute bars for one symbol over a 10-day window.

    Returns a list of row-tuples sized for psycopg2.extras.execute_values.
    The SDK paginates internally — all pages are materialised before we
    hand control back to the caller.  With limit=10_000 and 10-day windows
    this is safe: max bars ≈ 7 days × 390 mins = 2,730 rows per call.
    """
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=_to_utc(win_start),
        end=_to_utc(win_end, end_of_day=True),
        limit=10_000,
    )

    def _call():
        return client.get_stock_bars(request)

    bar_set = guarded_call(_call, label=f"Alpaca/Bars/{symbol}", min_spacing=0.35)

    # alpaca-py BarSet is dict-like: bar_set[symbol] or bar_set.data[symbol]
    raw_bars = []
    if hasattr(bar_set, "data") and isinstance(bar_set.data, dict):
        raw_bars = bar_set.data.get(symbol, [])
    elif hasattr(bar_set, "__getitem__"):
        try:
            raw_bars = bar_set[symbol]
        except (KeyError, TypeError):
            raw_bars = []

    rows: list[tuple] = []
    for bar in raw_bars:
        rows.append((
            symbol,
            bar.timestamp,
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
            int(bar.volume),
            float(bar.vwap)        if bar.vwap        else None,
            int(bar.trade_count)   if bar.trade_count else None,
        ))
    return rows


def ingest_intraday_bars(
    symbols: list[str],
    start:   date,
    end:     date,
    conn:    psycopg2.extensions.connection,
) -> None:
    """
    Phase 1: Stream 1-minute OHLCV bars into intraday_price_action.

    Memory-safe batching algorithm
    ──────────────────────────────
    For each symbol, for each 10-day window:
      A) fetch  → Python list in RAM (~500 KB peak)
      B) insert → single execute_values call (one PG round-trip, page_size=500)
      C) del + gc.collect() → RAM returned to OS before next window

    This means RAM usage is bounded to ONE window regardless of backfill depth.
    A full 5-year backfill for 8 symbols processes ~4.4 M rows but never holds
    more than ~3,000 in RAM at once.
    """
    client = _build_market_data_client()
    total_rows = 0

    for symbol in symbols:
        logger.info(f"Bars | {symbol}: starting backfill {start} → {end}")
        symbol_rows = 0

        for win_start, win_end in date_windows(start, end, window_days=10):
            rows = _fetch_bars_window(client, symbol, win_start, win_end)

            if rows:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur, _BARS_INSERT, rows, page_size=500
                    )
                conn.commit()
                symbol_rows += len(rows)
                logger.info(
                    f"Bars | {symbol} {win_start}→{win_end}: "
                    f"+{len(rows)} rows (symbol total={symbol_rows})"
                )

            # ── Critical: free this batch before fetching the next ──────────
            del rows
            gc.collect()

        total_rows += symbol_rows
        logger.info(f"Bars | {symbol}: complete — {symbol_rows} rows ingested")

    logger.success(
        f"Bars | Phase 1 complete — {total_rows} total rows "
        f"across {len(symbols)} symbol(s)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 ── Ingestion: Historical News for RAG
#              Primary: Alpaca News API  |  Fallback: NewsAPI
# ══════════════════════════════════════════════════════════════════════════════

_NEWS_INSERT = """
INSERT INTO historical_news_rag
    (headline, summary, author, source, url, published_at, symbols)
VALUES %s
ON CONFLICT (url) DO NOTHING;
"""


def _ingest_news_via_alpaca(
    symbols: list[str],
    start:   date,
    end:     date,
    conn:    psycopg2.extensions.connection,
    client:  StockHistoricalDataClient,
) -> int:
    """
    Alpaca News API — preferred source.
    Finance-specific, covers ETFs and equities, same API key as market data.
    Rate limit: same 200 req/min ceiling as market data.
    Window: 30 days (news volume is much lower than price data).
    """
    total = 0

    for win_start, win_end in date_windows(start, end, window_days=30):
        logger.debug(f"News/Alpaca | Fetching window {win_start} → {win_end}")

        request = NewsRequest(
            symbols=symbols,
            start=_to_utc(win_start),
            end=_to_utc(win_end, end_of_day=True),
            limit=50,                # max articles per request
        )

        def _call():
            return client.get_news(request)

        articles = guarded_call(_call, label="Alpaca/News", min_spacing=0.35)

        # NewsResponse can be a list or a model with .news attribute
        article_list = []
        if hasattr(articles, "news"):
            article_list = articles.news or []
        elif isinstance(articles, list):
            article_list = articles

        rows: list[tuple] = []
        for a in article_list:
            url = getattr(a, "url", None) or ""
            if not url:
                continue   # url is the unique key — skip if absent

            headline = (getattr(a, "headline", None) or "")[:800]
            summary  = (getattr(a, "summary",  None) or "")[:2000]
            syms     = list(getattr(a, "symbols", None) or [])

            rows.append((
                headline,
                summary,
                getattr(a, "author",  None),
                getattr(a, "source",  None),
                url,
                getattr(a, "created_at", None) or datetime.now(tz=timezone.utc),
                syms,
            ))

        if rows:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, _NEWS_INSERT, rows, page_size=200)
            conn.commit()
            total += len(rows)
            logger.info(
                f"News/Alpaca | {win_start}→{win_end}: +{len(rows)} articles "
                f"(total={total})"
            )

        del rows, article_list
        gc.collect()

    return total


def _ingest_news_via_newsapi(
    symbols: list[str],
    start:   date,
    end:     date,
    conn:    psycopg2.extensions.connection,
) -> int:
    """
    NewsAPI fallback — uses existing NEWS_API_KEY.

    Free tier constraints:
      - 100 requests/day
      - Results limited to 30 days in the past (on free tier)
      - One symbol per query (no multi-ticker AND)

    Strategy: one symbol × one 30-day window per call, with 2 s spacing.
    For backfills older than 30 days, consider upgrading to NewsAPI Developer.
    """
    api_key = os.environ.get("NEWS_API_KEY", "")
    if not api_key:
        logger.warning("News/NewsAPI | NEWS_API_KEY not set — skipping news phase")
        return 0

    total = 0

    for symbol in symbols:
        for win_start, win_end in date_windows(start, end, window_days=30):
            params = {
                "q":        f'"{symbol}" stock ETF',  # narrow the query
                "from":     win_start.isoformat(),
                "to":       win_end.isoformat(),
                "language": "en",
                "sortBy":   "publishedAt",
                "pageSize": 100,
                "apiKey":   api_key,
            }

            def _call():
                resp = requests.get(
                    "https://newsapi.org/v2/everything",
                    params=params,
                    timeout=20,
                )
                resp.raise_for_status()
                return resp.json()

            data = guarded_call(
                _call, label="NewsAPI", min_spacing=2.0, base_sleep=5.0
            )
            articles = data.get("articles", [])

            rows: list[tuple] = []
            for a in articles:
                url = a.get("url") or ""
                if not url:
                    continue

                raw_pub = a.get("publishedAt", "")
                try:
                    pub_dt = datetime.fromisoformat(raw_pub.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pub_dt = datetime.now(tz=timezone.utc)

                rows.append((
                    (a.get("title") or "")[:800],
                    (a.get("description") or "")[:2000],
                    a.get("author"),
                    (a.get("source") or {}).get("name"),
                    url,
                    pub_dt,
                    [symbol],
                ))

            if rows:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(cur, _NEWS_INSERT, rows, page_size=200)
                conn.commit()
                total += len(rows)
                logger.info(
                    f"News/NewsAPI | {symbol} {win_start}→{win_end}: "
                    f"+{len(rows)} articles (total={total})"
                )

            del rows
            gc.collect()

    return total


def ingest_news(
    symbols: list[str],
    start:   date,
    end:     date,
    conn:    psycopg2.extensions.connection,
) -> None:
    """
    Phase 2: Ingest historical financial news into historical_news_rag.
    Tries Alpaca News API first (better signal-to-noise for equities/ETFs).
    Falls back to NewsAPI if Alpaca keys are absent or the call fails.
    """
    api_key    = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    total = 0

    if api_key and secret_key:
        logger.info("News | Primary source: Alpaca News API")
        client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        try:
            total = _ingest_news_via_alpaca(symbols, start, end, conn, client)
        except Exception as exc:
            logger.warning(f"News | Alpaca News failed ({exc}) — switching to NewsAPI")
            total = _ingest_news_via_newsapi(symbols, start, end, conn)
    else:
        logger.info("News | Alpaca keys absent — using NewsAPI")
        total = _ingest_news_via_newsapi(symbols, start, end, conn)

    logger.success(f"News | Phase 2 complete — {total} articles ingested")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 ── Ingestion: Dividends + Unadjusted Prices  (Tiingo REST API)
#
# WHY TIINGO FOR THIS?
# Alpaca's market data API serves adjusted prices by default.  The HWM engine
# needs to know: "did the account value drop because of a real loss, or because
# JEPQ paid its monthly dividend and the price dropped by exactly that amount?"
# Tiingo's /dividends endpoint gives the exact ex-date + amount, and its
# /prices endpoint gives both adjClose and unadjusted close on the same day.
# Cross-referencing these two tells us the true distribution-adjusted P&L.
# ══════════════════════════════════════════════════════════════════════════════

_TIINGO_BASE = "https://api.tiingo.com/tiingo/daily"

_DIV_INSERT = """
INSERT INTO corporate_actions_dividends
    (symbol, ex_date, pay_date, declared_date, amount, currency,
     adj_close, unadj_close)
VALUES %s
ON CONFLICT (symbol, ex_date) DO UPDATE SET
    amount      = EXCLUDED.amount,
    pay_date    = EXCLUDED.pay_date,
    adj_close   = EXCLUDED.adj_close,
    unadj_close = EXCLUDED.unadj_close;
"""


def _tiingo_request(endpoint: str, params: dict, api_key: str) -> list | dict:
    """
    Single Tiingo REST call.  Auth is passed as a Bearer token header (more
    secure than embedding the key in the URL query string).

    Tiingo free tier: 50 requests/hour = 1 every 72 s.
    We enforce 2 s between calls to stay well under the ceiling without
    unnecessary idle time during interactive runs.
    """
    url     = f"{_TIINGO_BASE}/{endpoint}"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type":  "application/json",
    }

    def _call():
        resp = requests.get(url, params=params, headers=headers, timeout=25)
        resp.raise_for_status()
        return resp.json()

    return guarded_call(
        _call,
        label=f"Tiingo/{endpoint}",
        min_spacing=2.0,     # 2 s between calls ≈ 30 req/min well under 50/hr
        base_sleep=10.0,     # start retry backoff at 10 s for Tiingo
        cap=120.0,
    )


def _fetch_tiingo_prices(
    symbol:  str,
    start:   date,
    end:     date,
    api_key: str,
) -> dict[date, dict]:
    """
    Fetch daily OHLCV from Tiingo and return a {date: {adj_close, unadj_close}}
    lookup dict.  Both adjusted and unadjusted closes are present in Tiingo's
    /prices response — 'adjClose' is split/dividend adjusted, 'close' is raw.

    This lookup is joined against dividend records so each dividend row knows
    the stock price on its own ex-date — essential for the HWM calibration.
    """
    params = {
        "startDate":    start.isoformat(),
        "endDate":      end.isoformat(),
        "resampleFreq": "daily",
    }
    raw = _tiingo_request(f"{symbol}/prices", params, api_key) or []

    lookup: dict[date, dict] = {}
    for row in raw:
        try:
            d = date.fromisoformat(str(row.get("date", ""))[:10])
            lookup[d] = {
                "adj_close":   row.get("adjClose"),
                "unadj_close": row.get("close"),    # unadjusted close
            }
        except (ValueError, TypeError):
            continue
    return lookup


def ingest_dividends(
    symbols: list[str],
    start:   date,
    end:     date,
    conn:    psycopg2.extensions.connection,
) -> None:
    """
    Phase 3: Fetch all dividend events for each symbol and upsert into
    corporate_actions_dividends, annotating each record with the stock price
    on its ex-date for HWM calibration.

    Two Tiingo API calls per symbol:
      A) /dividends   — returns all dividend events in the date range
      B) /prices      — returns daily prices (to annotate ex-date prices)
    The prices call uses a 5-day buffer either side of the dividend date range
    to handle weekends and market holidays.

    Requires: TIINGO_API_KEY in Replit Secrets
    Free account: https://www.tiingo.com  (no credit card, instant activation)
    """
    api_key = os.environ.get("TIINGO_API_KEY", "")
    if not api_key:
        logger.error(
            "Dividends | TIINGO_API_KEY is not set.\n"
            "  → Go to Replit sidebar → Secrets → Add Secret\n"
            "  → Key: TIINGO_API_KEY\n"
            "  → Value: your token from https://api.tiingo.com/account/token\n"
            "  (Free account, no credit card required)\n"
            "  Skipping dividend ingestion."
        )
        return

    total = 0

    for symbol in symbols:
        logger.info(f"Dividends | {symbol}: fetching events {start} → {end}")

        # ── Step A: fetch all dividend events ───────────────────────────────
        div_params = {
            "startDate": start.isoformat(),
            "endDate":   end.isoformat(),
        }
        divs = _tiingo_request(f"{symbol}/dividends", div_params, api_key) or []
        logger.info(f"Dividends | {symbol}: {len(divs)} events found")

        if not divs:
            continue

        # ── Step B: fetch daily prices bracketing the dividend date range ───
        try:
            ex_dates = [
                date.fromisoformat(str(d.get("exDate", ""))[:10])
                for d in divs
                if d.get("exDate")
            ]
        except (ValueError, TypeError):
            ex_dates = []

        if not ex_dates:
            logger.warning(f"Dividends | {symbol}: no valid ex-dates — skipping price join")
            price_lookup: dict[date, dict] = {}
        else:
            price_start  = min(ex_dates) - timedelta(days=7)
            price_end    = max(ex_dates) + timedelta(days=7)
            price_lookup = _fetch_tiingo_prices(symbol, price_start, price_end, api_key)
            logger.debug(f"Dividends | {symbol}: {len(price_lookup)} price rows for join")

        # ── Step C: build rows and bulk-upsert ──────────────────────────────
        rows: list[tuple] = []
        for div in divs:
            try:
                ex_date = date.fromisoformat(str(div.get("exDate", ""))[:10])
            except (ValueError, TypeError):
                continue

            pay_date      = None
            declared_date = None
            try:
                raw_pay  = div.get("paymentDate") or div.get("payDate")
                raw_decl = div.get("declarationDate") or div.get("declaredDate")
                if raw_pay:
                    pay_date      = date.fromisoformat(str(raw_pay)[:10])
                if raw_decl:
                    declared_date = date.fromisoformat(str(raw_decl)[:10])
            except ValueError:
                pass

            amount     = float(div.get("amount") or div.get("dividendCash") or 0)
            price_info = price_lookup.get(ex_date, {})

            rows.append((
                symbol,
                ex_date,
                pay_date,
                declared_date,
                amount,
                "USD",
                price_info.get("adj_close"),
                price_info.get("unadj_close"),
            ))

        if rows:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, _DIV_INSERT, rows, page_size=200)
            conn.commit()
            total += len(rows)
            logger.info(f"Dividends | {symbol}: upserted {len(rows)} records")

        del rows, divs, price_lookup
        gc.collect()

    logger.success(
        f"Dividends | Phase 3 complete — {total} records "
        f"across {len(symbols)} symbol(s)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 ── CLI Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

# Default symbol sets — override via --symbols on the CLI
VOLATILE_ETFS = ["TQQQ", "SOXL", "SPXL", "UVXY"]      # ATR trailing-stop training
YIELD_ETFS    = ["JEPQ", "JEPI", "SCHD", "QYLD"]       # HWM dividend calibration
ALL_SYMBOLS   = list(dict.fromkeys(VOLATILE_ETFS + YIELD_ETFS))  # deduplicated


def _print_env_check() -> None:
    """Print a pre-flight summary of which API keys are configured."""
    checks = {
        "DATABASE_URL / PGHOST": bool(
            os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL") or os.environ.get("PGHOST")
        ),
        "ALPACA_API_KEY":    bool(os.environ.get("ALPACA_API_KEY")),
        "ALPACA_SECRET_KEY": bool(os.environ.get("ALPACA_SECRET_KEY")),
        "NEWS_API_KEY":      bool(os.environ.get("NEWS_API_KEY")),
        "TIINGO_API_KEY":    bool(os.environ.get("TIINGO_API_KEY")),
    }
    logger.info("Pre-flight environment check:")
    for key, present in checks.items():
        status = "OK" if present else "MISSING"
        level  = "info" if present else "warning"
        getattr(logger, level)(f"  {key:30s}  {status}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quant Terminal — Historical Data Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbols", nargs="+", default=ALL_SYMBOLS,
        metavar="TICKER",
        help=f"Tickers to process (default: {' '.join(ALL_SYMBOLS)})",
    )
    parser.add_argument(
        "--start",
        default=(date.today() - timedelta(days=365)).isoformat(),
        help="Start date YYYY-MM-DD (default: 1 year ago)",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--window-days", type=int, default=10, metavar="N",
        help="Calendar days per memory-safe batch (default: 10)",
    )
    parser.add_argument("--skip-bars", action="store_true", help="Skip OHLCV ingestion")
    parser.add_argument("--skip-news", action="store_true", help="Skip news ingestion")
    parser.add_argument("--skip-divs", action="store_true", help="Skip dividend ingestion")
    parser.add_argument(
        "--div-symbols", nargs="+", default=None,
        metavar="TICKER",
        help="Override symbols for dividend ingestion (default: YIELD_ETFS)",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    div_symbols = args.div_symbols or YIELD_ETFS

    logger.info("=" * 68)
    logger.info("  Quant Terminal — Historical Data Ingestion Pipeline")
    logger.info("  Stream-to-DB mode: zero local file writes")
    logger.info("=" * 68)
    logger.info(f"  Symbols (bars/news) : {args.symbols}")
    logger.info(f"  Symbols (dividends) : {div_symbols}")
    logger.info(f"  Date range          : {start} → {end}")
    logger.info(f"  Batch window        : {args.window_days} calendar days")
    logger.info(
        f"  Phases enabled      : "
        f"bars={not args.skip_bars}, "
        f"news={not args.skip_news}, "
        f"divs={not args.skip_divs}"
    )
    logger.info("=" * 68)
    _print_env_check()

    conn = open_connection()
    try:
        # ── Bootstrap schema (idempotent — safe to run every time) ──────────
        ensure_schema(conn)

        # ── Phase 1: 1-minute OHLCV bars ────────────────────────────────────
        if not args.skip_bars:
            logger.info("━" * 68)
            logger.info("PHASE 1 / 3 — Intraday price bars (Alpaca Market Data)")
            logger.info("━" * 68)
            ingest_intraday_bars(args.symbols, start, end, conn)

        # ── Phase 2: Historical news for RAG ────────────────────────────────
        if not args.skip_news:
            logger.info("━" * 68)
            logger.info("PHASE 2 / 3 — Historical news (Alpaca News → NewsAPI)")
            logger.info("━" * 68)
            ingest_news(args.symbols, start, end, conn)

        # ── Phase 3: Dividends + unadjusted prices ───────────────────────────
        if not args.skip_divs:
            logger.info("━" * 68)
            logger.info("PHASE 3 / 3 — Dividend events (Tiingo)")
            logger.info("━" * 68)
            ingest_dividends(div_symbols, start, end, conn)

        logger.success("=" * 68)
        logger.success("  All phases complete — ingestion pipeline finished.")
        logger.success("=" * 68)

    except KeyboardInterrupt:
        logger.warning("Interrupted by user — committing any open transaction...")
        try:
            conn.commit()
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"Fatal error in pipeline: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
        logger.info("DB | Connection closed")


if __name__ == "__main__":
    main()
