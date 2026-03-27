"""
FRED API Data Ingestion Client
--------------------------------
Fetches macroeconomic series from the Federal Reserve Economic Data (FRED) API.
Uses async execution via httpx + tenacity exponential backoff to handle rate limits.

Key series collected:
  - DFF      : Federal Funds Rate (overnight rate)
  - T10YIE   : 10-Year Breakeven Inflation Rate
  - T10Y2Y   : 10-Year minus 2-Year Treasury Yield Spread (recession signal)
  - UNRATE   : Unemployment Rate
  - CPIAUCSL : CPI (Consumer Price Index, All Items)
  - PPIACO   : Producer Price Index (All Commodities)
  - DCOILWTICO: WTI Crude Oil Price
  - GOLDAMGBD228NLBM: Gold Fixing Price (London)
  - DEXUSEU  : USD/EUR Exchange Rate
  - VIXCLS   : CBOE VIX (Fear Index)
"""

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx
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

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

MACRO_SERIES: dict[str, str] = {
    "DFF": "Federal Funds Rate",
    "T10YIE": "10Y Breakeven Inflation Rate",
    "T10Y2Y": "10Y-2Y Yield Spread",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI All Items",
    "PPIACO": "PPI All Commodities",
    "DCOILWTICO": "WTI Crude Oil Price",
    "GOLDAMGBD228NLBM": "Gold Price (London Fix)",
    "DEXUSEU": "USD/EUR Exchange Rate",
    "VIXCLS": "CBOE VIX",
}


def _make_retry_decorator():
    return retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(
            multiplier=1,
            min=settings.backoff_min_wait,
            max=settings.backoff_max_wait,
        ),
        before_sleep=before_sleep_log(logging.getLogger("tenacity"), logging.WARNING),
        reraise=True,
    )


async def _fetch_series(
    client: httpx.AsyncClient,
    series_id: str,
    observation_start: str,
    observation_end: str,
) -> dict[str, Any]:
    """
    Fetch a single FRED series. Returns the most recent non-null observation.
    Retried automatically on network or HTTP errors.
    """

    @_make_retry_decorator()
    async def _request() -> dict[str, Any]:
        params = {
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "observation_start": observation_start,
            "observation_end": observation_end,
            "sort_order": "desc",
            "limit": 5,
        }
        response = await client.get(FRED_BASE_URL, params=params, timeout=30.0)
        response.raise_for_status()
        return response.json()

    data = await _request()
    observations = data.get("observations", [])

    for obs in observations:
        if obs.get("value") != ".":
            return {
                "series_id": series_id,
                "name": MACRO_SERIES.get(series_id, series_id),
                "value": float(obs["value"]),
                "date": obs["date"],
            }

    logger.warning(f"FRED | No valid observations found for series: {series_id}")
    return {
        "series_id": series_id,
        "name": MACRO_SERIES.get(series_id, series_id),
        "value": None,
        "date": None,
    }


async def fetch_macro_data(lookback_days: int = 30) -> dict[str, Any]:
    """
    Fetch all macro series concurrently.

    Args:
        lookback_days: How many days back to request observations from FRED.

    Returns:
        Dict mapping series_id -> {name, value, date}
    """
    observation_end = date.today().isoformat()
    observation_start = (date.today() - timedelta(days=lookback_days)).isoformat()

    logger.info(
        f"FRED | Fetching {len(MACRO_SERIES)} series "
        f"({observation_start} → {observation_end})"
    )

    results: dict[str, Any] = {}

    async with httpx.AsyncClient() as client:
        tasks = {
            series_id: _fetch_series(client, series_id, observation_start, observation_end)
            for series_id in MACRO_SERIES
        }
        completed = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for series_id, result in zip(tasks.keys(), completed):
            if isinstance(result, Exception):
                logger.error(f"FRED | Failed to fetch {series_id}: {result}")
                results[series_id] = {
                    "series_id": series_id,
                    "name": MACRO_SERIES[series_id],
                    "value": None,
                    "date": None,
                    "error": str(result),
                }
            else:
                results[series_id] = result
                logger.debug(
                    f"FRED | {series_id} ({MACRO_SERIES[series_id]}): "
                    f"{result['value']} on {result['date']}"
                )

    fetched = sum(1 for v in results.values() if v.get("value") is not None)
    logger.info(f"FRED | Complete — {fetched}/{len(MACRO_SERIES)} series fetched successfully")
    return results
