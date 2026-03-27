"""
Market Data Client
--------------------
Fetches OHLCV price data, trailing returns, and volatility for the trading universe.

PRIMARY: Alpaca Market Data API (free tier, no IP restrictions, real-time for US ETFs)
FALLBACK: yfinance (works in local/residential environments, blocked on cloud IPs)

Why Alpaca instead of yfinance in production:
  Yahoo Finance blocks requests from shared-IP cloud environments (AWS, GCP, Replit, etc.)
  Alpaca Market Data API is free for all users, reliable from any IP, and covers
  all US-listed ETFs and most crypto tickers needed by this platform.

Universe:
  Crypto ETFs   : BITO, IBIT, GBTC, ETHA
  Commodity ETFs: GLD, SLV, USO, DBA, PDBC, CPER
  Currency ETFs : UUP, FXE, FXY, FXB, EUO, YCS
  Wildcard      : QQQ, SPY, TLT, HYG, EEM
  Cash Equiv    : SGOV
"""

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx
import numpy as np
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from config.settings import settings

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"

UNIVERSE: dict[str, list[str]] = {
    "crypto": ["BITO", "IBIT", "GBTC", "ETHA"],
    "commodity": ["GLD", "SLV", "USO", "DBA", "PDBC", "CPER"],
    "currency": ["UUP", "FXE", "FXY", "FXB", "EUO", "YCS"],
    "wildcard": ["QQQ", "SPY", "TLT", "HYG", "EEM"],
    "cash_equivalent": ["SGOV"],
}

ALL_TICKERS: list[str] = [t for tickers in UNIVERSE.values() for t in tickers]


def _is_retryable_http_error(exc: BaseException) -> bool:
    """Only retry on 429 (rate limit) or 5xx (server errors), not 401/403/404."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.RequestError)


def _make_retry_decorator():
    return retry(
        retry=retry_if_exception(_is_retryable_http_error),
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(
            multiplier=1,
            min=settings.backoff_min_wait,
            max=settings.backoff_max_wait,
        ),
        before_sleep=before_sleep_log(logging.getLogger("tenacity"), logging.WARNING),
        reraise=True,
    )


def _alpaca_headers() -> dict[str, str]:
    """
    Alpaca API headers. Uses paper trading keys (same keys work for market data).
    If no Alpaca keys are configured, uses unauthenticated access (limited rate).
    """
    if settings.alpaca_api_key and settings.alpaca_api_key != "dummy":
        return {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
    return {}


async def _fetch_bars_alpaca(
    client: httpx.AsyncClient,
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    Fetch daily bars for a single ticker from Alpaca Market Data API.
    Returns computed metrics or an error dict.
    """

    @_make_retry_decorator()
    async def _request() -> list[dict]:
        url = f"{ALPACA_DATA_BASE_URL}/stocks/{ticker}/bars"
        params = {
            "timeframe": "1Day",
            "start": start_date,
            "end": end_date,
            "limit": 200,
            "feed": "iex",
            "adjustment": "all",
        }
        response = await client.get(
            url,
            params=params,
            headers=_alpaca_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("bars", [])

    try:
        bars = await _request()
    except Exception as exc:
        logger.warning(f"Alpaca Market Data | {ticker}: {exc}")
        return {"ticker": ticker, "error": str(exc)}

    if not bars:
        logger.warning(f"Alpaca Market Data | No bars returned for {ticker}")
        return {"ticker": ticker, "error": "no data"}

    closes = [float(b["c"]) for b in bars]

    latest_price = closes[-1]
    latest_date_str = bars[-1]["t"][:10]

    def pct_chg(n: int) -> float | None:
        return float((closes[-1] / closes[-n] - 1) * 100) if len(closes) >= n else None

    ret_1d = pct_chg(2)
    ret_5d = pct_chg(5)
    ret_20d = pct_chg(20)
    ret_60d = pct_chg(60)

    daily_returns = [
        (closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))
    ]
    if len(daily_returns) >= 20:
        last20 = daily_returns[-20:]
        mean = sum(last20) / len(last20)
        variance = sum((r - mean) ** 2 for r in last20) / len(last20)
        volatility_20d = float((variance ** 0.5) * (252 ** 0.5) * 100)
    else:
        volatility_20d = None

    return {
        "ticker": ticker,
        "latest_price": latest_price,
        "latest_date": latest_date_str,
        "return_1d_pct": ret_1d,
        "return_5d_pct": ret_5d,
        "return_20d_pct": ret_20d,
        "return_60d_pct": ret_60d,
        "annualized_volatility_20d_pct": volatility_20d,
        "data_points": len(closes),
    }


async def fetch_market_data(period: str = "3mo") -> dict[str, Any]:
    """
    Asynchronously fetch price data for the full trading universe via Alpaca Market Data.

    Args:
        period: Lookback period string — '1mo', '3mo', '6mo', '1y'.

    Returns:
        Dict with 'by_ticker' (flat lookup) and 'by_category' (grouped).
    """
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 90)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=period_days)).isoformat()

    logger.info(
        f"Market Data | Fetching {len(ALL_TICKERS)} tickers via Alpaca "
        f"({start_date} → {end_date})"
    )

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_bars_alpaca(client, ticker, start_date, end_date)
            for ticker in ALL_TICKERS
        ]
        results_list = await asyncio.gather(*tasks)

    by_ticker: dict[str, Any] = {r["ticker"]: r for r in results_list}
    by_category: dict[str, dict[str, Any]] = {
        cat: {t: by_ticker.get(t, {"ticker": t, "error": "missing"}) for t in tickers}
        for cat, tickers in UNIVERSE.items()
    }

    fetched = sum(1 for v in by_ticker.values() if "error" not in v)
    logger.info(
        f"Market Data | Complete — {fetched}/{len(ALL_TICKERS)} tickers fetched successfully"
    )

    return {"by_ticker": by_ticker, "by_category": by_category}


async def fetch_single_ticker(ticker: str, period: str = "3mo") -> dict[str, Any]:
    """Fetch data for a single ticker. Useful for runtime lookups."""
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 90)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=period_days)).isoformat()
    logger.info(f"Market Data | Fetching single ticker: {ticker}")
    async with httpx.AsyncClient() as client:
        return await _fetch_bars_alpaca(client, ticker, start_date, end_date)
