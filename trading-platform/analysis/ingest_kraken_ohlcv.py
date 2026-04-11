"""
ingest_kraken_ohlcv.py — Kraken Historical OHLCV Data Pipeline
==============================================================
Fetches historical candle data from Kraken's public REST API and stores
it in the `historical_prices` PostgreSQL table.

Two timeframes are fetched per pair:
  • interval=1440 (daily, 1d)  — ~720 candles ≈ 2 years of history.
    This is the primary dataset for the true price-based backtester because
    it covers the period BEFORE the live trading start (March 29, 2026).
  • interval=60  (hourly, 1h) — ~720 candles ≈ 30 days of history.
    This overlaps with the live trading period but is stored so users can
    verify granular recent-period data (as requested).

Five trading pairs:
  BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD

No authentication required — Kraken's OHLCV endpoint is public.

API constraint (documented and verified):
  The Kraken public OHLC endpoint always returns the MOST RECENT ~720
  candles for a given timeframe, regardless of the `since` parameter.
  There is no way to paginate further back using the free public API.
  For 1h candles this means ~30 days; for 1d candles this means ~2 years.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── Pair configuration ────────────────────────────────────────────────────────

PAIRS = [
    {
        "display": "BTC/USD",
        "kraken_pair": "XBTUSD",
    },
    {
        "display": "ETH/USD",
        "kraken_pair": "ETHUSD",
    },
    {
        "display": "SOL/USD",
        "kraken_pair": "SOLUSD",
    },
    {
        "display": "ADA/USD",
        "kraken_pair": "ADAUSD",
    },
    {
        "display": "AVAX/USD",
        "kraken_pair": "AVAXUSD",
    },
]

TIMEFRAMES = [
    {"interval": 1440, "label": "1d"},
    {"interval": 60,   "label": "1h"},
]

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
MAX_RETRIES     = 3
RETRY_BACKOFF   = [5, 10, 15]


# ── DB helpers ────────────────────────────────────────────────────────────────

def _pg_conn():
    from db.postgres import get_conn
    return get_conn()


def _ensure_table() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS historical_prices (
        id        BIGSERIAL PRIMARY KEY,
        pair      TEXT             NOT NULL,
        timeframe TEXT             NOT NULL DEFAULT '1d',
        ts        TIMESTAMPTZ      NOT NULL,
        open      DOUBLE PRECISION NOT NULL,
        high      DOUBLE PRECISION NOT NULL,
        low       DOUBLE PRECISION NOT NULL,
        close     DOUBLE PRECISION NOT NULL,
        volume    DOUBLE PRECISION NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_prices_uq
        ON historical_prices (pair, timeframe, ts);
    CREATE INDEX IF NOT EXISTS idx_historical_prices_pair_ts
        ON historical_prices (pair, timeframe, ts DESC);
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
        logger.debug("OHLCV | historical_prices table ensured")
    except Exception as exc:
        logger.error(f"OHLCV | Table creation failed: {exc}")
        raise


def _count_rows(pair: str, timeframe: str) -> int:
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM historical_prices WHERE pair=%s AND timeframe=%s",
                    (pair, timeframe),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
    except Exception:
        return 0


def _upsert_candles(pair: str, timeframe: str, candles: list[dict]) -> int:
    """Upsert candle rows, return number of rows inserted (conflicts skipped)."""
    if not candles:
        return 0
    sql = """
        INSERT INTO historical_prices (pair, timeframe, ts, open, high, low, close, volume)
        VALUES (%(pair)s, %(tf)s, to_timestamp(%(ts)s), %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
        ON CONFLICT (pair, timeframe, ts) DO NOTHING
    """
    inserted = 0
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                for c in candles:
                    cur.execute(sql, {
                        "pair":   pair,
                        "tf":     timeframe,
                        "ts":     c["ts"],
                        "open":   c["open"],
                        "high":   c["high"],
                        "low":    c["low"],
                        "close":  c["close"],
                        "volume": c["volume"],
                    })
                    inserted += cur.rowcount
        return inserted
    except Exception as exc:
        logger.error(f"OHLCV | Upsert failed for {pair}/{timeframe}: {exc}")
        return 0


def _get_date_range(pair: str, timeframe: str) -> tuple[str, str] | None:
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MIN(ts), MAX(ts)
                    FROM historical_prices
                    WHERE pair=%s AND timeframe=%s
                    """,
                    (pair, timeframe),
                )
                row = cur.fetchone()
                if row and row[0] and row[1]:
                    return (
                        row[0].strftime("%Y-%m-%d"),
                        row[1].strftime("%Y-%m-%d"),
                    )
    except Exception:
        pass
    return None


# ── Kraken API fetch ──────────────────────────────────────────────────────────

def _fetch_ohlcv(kraken_pair: str, interval: int, since: int | None = None) -> list[dict]:
    """
    Fetch OHLCV candles from Kraken's public REST API.
    Returns a list of dicts with keys: ts, open, high, low, close, volume.
    """
    url = f"{KRAKEN_OHLC_URL}?pair={kraken_pair}&interval={interval}"
    if since is not None:
        url += f"&since={since}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AlgoEdge-Backtester/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            if data.get("error"):
                logger.warning(f"OHLCV | Kraken API error for {kraken_pair}: {data['error']}")
                return []

            result = data.get("result", {})
            # The pair key in the response may differ (e.g. XBTUSD → XXBTZUSD)
            candle_key = next((k for k in result if k != "last"), None)
            if not candle_key:
                return []

            raw = result[candle_key]
            candles = []
            for row in raw:
                # Kraken OHLC row: [time, open, high, low, close, vwap, volume, count]
                candles.append({
                    "ts":     int(row[0]),
                    "open":   float(row[1]),
                    "high":   float(row[2]),
                    "low":    float(row[3]),
                    "close":  float(row[4]),
                    "volume": float(row[6]),
                })
            return candles

        except Exception as exc:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[attempt - 1]
                logger.warning(f"OHLCV | Attempt {attempt} failed for {kraken_pair}: {exc} — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"OHLCV | Failed after {MAX_RETRIES} attempts for {kraken_pair}: {exc}")
                return []
    return []


# ── Main ingest logic ─────────────────────────────────────────────────────────

def ingest_pair(pair_cfg: dict, tf_cfg: dict) -> dict:
    """Ingest one pair × one timeframe. Returns summary dict."""
    display   = pair_cfg["display"]
    kpair     = pair_cfg["kraken_pair"]
    interval  = tf_cfg["interval"]
    tf_label  = tf_cfg["label"]

    logger.info(f"OHLCV | Fetching {display} [{tf_label}] from Kraken …")

    # Kraken only returns most-recent ~720 candles regardless of since,
    # so one call is sufficient.
    candles = _fetch_ohlcv(kpair, interval)

    if not candles:
        logger.warning(f"OHLCV | No candles returned for {display} [{tf_label}]")
        return {"pair": display, "timeframe": tf_label, "inserted": 0, "total": 0, "range": None}

    # Remove the last (incomplete/current) candle to avoid partial data
    if len(candles) > 1:
        candles = candles[:-1]

    inserted = _upsert_candles(display, tf_label, candles)
    total    = _count_rows(display, tf_label)
    date_rng = _get_date_range(display, tf_label)

    logger.info(
        f"OHLCV | {display} [{tf_label}]: {len(candles)} fetched, "
        f"{inserted} new rows → {total} total | "
        f"range: {date_rng[0] if date_rng else '?'} → {date_rng[1] if date_rng else '?'}"
    )

    # Brief pause to be polite to Kraken's servers
    time.sleep(0.5)

    return {
        "pair":      display,
        "timeframe": tf_label,
        "fetched":   len(candles),
        "inserted":  inserted,
        "total":     total,
        "range":     date_rng,
    }


def run_ingest(pairs: list[dict] | None = None, timeframes: list[dict] | None = None) -> dict:
    """
    Run the full ingest pipeline for all pairs and timeframes.
    Returns a summary dict keyed by (pair, timeframe).
    """
    _ensure_table()

    pairs_to_use = pairs or PAIRS
    tfs_to_use   = timeframes or TIMEFRAMES
    results = {}

    for pair_cfg in pairs_to_use:
        for tf_cfg in tfs_to_use:
            key = f"{pair_cfg['display']}_{tf_cfg['label']}"
            try:
                result = ingest_pair(pair_cfg, tf_cfg)
                results[key] = result
            except Exception as exc:
                logger.error(f"OHLCV | Ingest failed for {pair_cfg['display']}/{tf_cfg['label']}: {exc}")
                results[key] = {"error": str(exc)}

    return results


def get_coverage_status() -> list[dict]:
    """Return current data coverage per pair/timeframe."""
    _ensure_table()
    rows = []
    for pair_cfg in PAIRS:
        for tf_cfg in TIMEFRAMES:
            display  = pair_cfg["display"]
            tf_label = tf_cfg["label"]
            total    = _count_rows(display, tf_label)
            date_rng = _get_date_range(display, tf_label)
            rows.append({
                "pair":      display,
                "timeframe": tf_label,
                "total_candles": total,
                "from": date_rng[0] if date_rng else None,
                "to":   date_rng[1] if date_rng else None,
            })
    return rows


def needs_ingest() -> bool:
    """Return True if the historical_prices table is empty for the primary (1d) dataset."""
    try:
        _ensure_table()
        total = 0
        for pair_cfg in PAIRS:
            total += _count_rows(pair_cfg["display"], "1d")
        return total == 0
    except Exception:
        return True


if __name__ == "__main__":
    logger.info("OHLCV | Manual ingest starting …")
    summary = run_ingest()
    logger.info("OHLCV | Ingest complete:")
    for key, res in summary.items():
        if "error" in res:
            logger.error(f"  {key}: ERROR — {res['error']}")
        else:
            rng = res.get("range")
            rng_str = f"{rng[0]} → {rng[1]}" if rng else "N/A"
            logger.info(f"  {key}: {res['total']} candles | {rng_str}")
