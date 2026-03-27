"""
yfinance Market Data Client
-----------------------------
Fetches OHLCV price data, trailing returns, and volatility for a universe
of tickers that map to the platform's allocation categories:

  Crypto ETFs   : BITO, IBIT, GBTC, ETHA
  Commodity ETFs: GLD, SLV, USO, DBA, PDBC, CPER
  Currency ETFs : UUP, FXE, FXY, FXB, EUO, YCS
  Wildcard      : QQQ, SPY, TLT, HYG, EEM
  Cash Equiv    : SGOV

Uses run_in_executor to offload blocking yfinance calls to a thread pool,
wrapped in tenacity exponential backoff for transient failures.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

import yfinance as yf
import numpy as np
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from config.settings import settings

UNIVERSE: dict[str, list[str]] = {
    "crypto": ["BITO", "IBIT", "GBTC", "ETHA"],
    "commodity": ["GLD", "SLV", "USO", "DBA", "PDBC", "CPER"],
    "currency": ["UUP", "FXE", "FXY", "FXB", "EUO", "YCS"],
    "wildcard": ["QQQ", "SPY", "TLT", "HYG", "EEM"],
    "cash_equivalent": ["SGOV"],
}

ALL_TICKERS: list[str] = [t for tickers in UNIVERSE.values() for t in tickers]

_thread_pool = ThreadPoolExecutor(max_workers=4)


def _retry_decorator():
    return retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(
            multiplier=1,
            min=settings.backoff_min_wait,
            max=settings.backoff_max_wait,
        ),
        before_sleep=before_sleep_log(logging.getLogger("tenacity"), logging.WARNING),
        reraise=True,
    )


def _download_blocking(tickers: list[str], period: str = "3mo") -> dict[str, Any]:
    """
    Blocking yfinance download. Runs in a thread pool to avoid blocking the event loop.
    Returns per-ticker OHLCV summary + computed metrics.
    """
    @_retry_decorator()
    def _fetch():
        raw = yf.download(
            tickers=tickers,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        return raw

    raw = _fetch()

    results: dict[str, Any] = {}

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                close = raw["Close"]
            else:
                close = raw["Close"][ticker]

            close = close.dropna()

            if close.empty:
                logger.warning(f"yfinance | No data for {ticker}")
                results[ticker] = {"ticker": ticker, "error": "no data"}
                continue

            latest_price = float(close.iloc[-1])
            ret_1d = float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) >= 2 else None
            ret_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 else None
            ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else None
            ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else None

            daily_returns = close.pct_change().dropna()
            volatility_20d = float(daily_returns.tail(20).std() * np.sqrt(252) * 100) if len(daily_returns) >= 20 else None

            results[ticker] = {
                "ticker": ticker,
                "latest_price": latest_price,
                "latest_date": close.index[-1].strftime("%Y-%m-%d"),
                "return_1d_pct": ret_1d,
                "return_5d_pct": ret_5d,
                "return_20d_pct": ret_20d,
                "return_60d_pct": ret_60d,
                "annualized_volatility_20d_pct": volatility_20d,
                "data_points": len(close),
            }

        except Exception as exc:
            logger.error(f"yfinance | Error processing {ticker}: {exc}")
            results[ticker] = {"ticker": ticker, "error": str(exc)}

    return results


async def fetch_market_data(period: str = "3mo") -> dict[str, Any]:
    """
    Asynchronously fetch price data for the full trading universe.

    Args:
        period: yfinance period string (e.g. '3mo', '6mo', '1y').

    Returns:
        Dict with 'by_ticker' (flat lookup) and 'by_category' (grouped).
    """
    logger.info(f"yfinance | Fetching data for {len(ALL_TICKERS)} tickers (period={period})")

    loop = asyncio.get_event_loop()
    by_ticker: dict[str, Any] = await loop.run_in_executor(
        _thread_pool,
        _download_blocking,
        ALL_TICKERS,
        period,
    )

    by_category: dict[str, dict[str, Any]] = {}
    for category, tickers in UNIVERSE.items():
        by_category[category] = {t: by_ticker.get(t, {"ticker": t, "error": "missing"}) for t in tickers}

    fetched = sum(1 for v in by_ticker.values() if "error" not in v)
    logger.info(
        f"yfinance | Complete — {fetched}/{len(ALL_TICKERS)} tickers fetched successfully"
    )

    return {"by_ticker": by_ticker, "by_category": by_category}


async def fetch_single_ticker(ticker: str, period: str = "3mo") -> dict[str, Any]:
    """
    Fetch data for a single ticker. Useful for runtime lookups.
    """
    logger.info(f"yfinance | Fetching single ticker: {ticker}")
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        _thread_pool,
        _download_blocking,
        [ticker],
        period,
    )
    return results.get(ticker, {"ticker": ticker, "error": "not found"})
