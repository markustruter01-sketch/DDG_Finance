"""Price reads for the twins. Read-only market data, nothing else.

- US sessions: Alpaca's data API (data.alpaca.markets), daily bars adjusted for
  splits and dividends, through the same fetcher the G4 shadow uses. It needs
  the Alpaca key, because Alpaca has no separate data-only key; only the data
  endpoint is called and no trading client is ever built here.
- Forex: OANDA hourly mid/bid/ask candles through core.oanda_client (GET only).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from twins.engine import SnapshotError, _candle_time

MAX_CANDLES = 5000          # OANDA's limit per request


def alpaca_daily(symbols: list[str], start: date, now: datetime,
                 fetch: Callable[[list[str], date], dict[str, list[dict[str, Any]]]] | None = None
                 ) -> dict[str, list[dict[str, Any]]]:
    """Finished sessions only, from ``start``. A symbol with no bars or an
    inconsistent bar is left out (logged): the twins that need it then fail
    loudly on their own, and the others still run."""
    from loguru import logger
    from sleeve_runtime.trend_v1b import completed_bars

    if fetch is None:
        from config.settings import settings
        from sleeve_runtime.gear_shadow import alpaca_ohlc_fetcher
        fetch = alpaca_ohlc_fetcher(settings.alpaca_api_key, settings.alpaca_secret_key)
    bars = completed_bars(fetch(sorted(set(symbols)), start), now)
    out = {}
    for sym in sorted(set(symbols)):
        rows = bars.get(sym) or []
        bad = [b["day"] for b in rows
               if min(b["open"], b["high"], b["low"], b["close"]) <= 0
               or b["high"] < max(b["open"], b["close"], b["low"]) or b["low"] > min(b["open"], b["close"])]
        if not rows or bad:
            logger.warning(f"twins | daily bars for {sym} left out: {'none' if not rows else f'bad bar {bad[0]}'}")
            continue
        out[sym] = rows
    return out


def oanda_hourly(pairs: list[str], start: datetime, client_factory: Callable[[], Any] | None = None
                 ) -> dict[str, list[dict[str, Any]]]:
    """Complete hourly candles from ``start`` (UTC) to now, per pair."""
    if client_factory is None:
        from core.oanda_client import OandaClient as client_factory
    out: dict[str, list[dict[str, Any]]] = {}
    with client_factory() as client:
        for pair in sorted(set(pairs)):
            rows: list[dict[str, Any]] = []
            cursor = start.astimezone(timezone.utc)
            while True:
                page = client.hourly_candles(pair, start=cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                             count=MAX_CANDLES)
                rows += page
                if len(page) < MAX_CANDLES - 1:
                    break
                cursor = _candle_time(page[-1]["time"]) + timedelta(hours=1)
            out[pair] = rows
    return out
