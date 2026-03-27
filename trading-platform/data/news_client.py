"""
NewsAPI Data Ingestion Client
------------------------------
Fetches recent financial / macroeconomic news headlines relevant to the
platform's trading universe. Headlines are returned as structured dicts and
will later be fed as context to the LLM analysis layer.

Queries:
  - General macro: "Federal Reserve interest rates inflation economy"
  - Crypto:        "bitcoin ethereum crypto market"
  - Commodities:   "gold oil commodities futures"
  - Currencies:    "dollar euro yen forex exchange rate"
  - Markets:       "stock market S&P 500 recession bear bull"

Uses async httpx with tenacity exponential backoff.
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

NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"

NEWS_QUERIES: dict[str, str] = {
    "macro": "Federal Reserve interest rates inflation economy recession",
    "crypto": "bitcoin ethereum crypto market digital asset",
    "commodities": "gold oil crude WTI commodities futures",
    "currencies": "dollar euro yen forex exchange rate DXY",
    "markets": "stock market S&P 500 Nasdaq bonds yield curve",
}

MAX_ARTICLES_PER_QUERY = 5


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


async def _fetch_query(
    client: httpx.AsyncClient,
    category: str,
    query: str,
    from_date: str,
    to_date: str,
) -> dict[str, Any]:
    """
    Fetch news articles for a single query. Returns structured article summaries.
    """

    @_make_retry_decorator()
    async def _request() -> dict[str, Any]:
        params = {
            "q": query,
            "from": from_date,
            "to": to_date,
            "language": "en",
            "sortBy": "relevancy",
            "pageSize": MAX_ARTICLES_PER_QUERY,
            "apiKey": settings.news_api_key,
        }
        response = await client.get(NEWSAPI_BASE_URL, params=params, timeout=30.0)
        response.raise_for_status()
        return response.json()

    data = await _request()
    articles = data.get("articles", [])

    parsed: list[dict[str, str]] = []
    for article in articles:
        title = article.get("title") or ""
        description = article.get("description") or ""
        if title and "[Removed]" not in title:
            parsed.append(
                {
                    "title": title.strip(),
                    "description": description.strip(),
                    "source": article.get("source", {}).get("name", "Unknown"),
                    "published_at": article.get("publishedAt", ""),
                    "url": article.get("url", ""),
                }
            )

    logger.debug(
        f"NewsAPI | [{category}] fetched {len(parsed)} articles "
        f"(total results: {data.get('totalResults', 0)})"
    )
    return {"category": category, "query": query, "articles": parsed}


async def fetch_news(lookback_days: int = 3) -> dict[str, Any]:
    """
    Fetch financial news across all topic categories concurrently.

    Args:
        lookback_days: How many calendar days of news to retrieve (max 30 on free plan).

    Returns:
        Dict mapping category -> list of article summaries, plus a flat
        'all_headlines' list for easy LLM prompt injection.
    """
    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    logger.info(
        f"NewsAPI | Fetching {len(NEWS_QUERIES)} topic categories "
        f"({from_date} → {to_date})"
    )

    results: dict[str, Any] = {}

    async with httpx.AsyncClient() as client:
        tasks = {
            category: _fetch_query(client, category, query, from_date, to_date)
            for category, query in NEWS_QUERIES.items()
        }
        completed = await asyncio.gather(*tasks.values(), return_exceptions=True)

    for category, result in zip(tasks.keys(), completed):
        if isinstance(result, Exception):
            logger.error(f"NewsAPI | Failed to fetch [{category}]: {result}")
            results[category] = {
                "category": category,
                "articles": [],
                "error": str(result),
            }
        else:
            results[category] = result

    all_headlines: list[str] = []
    for cat_data in results.values():
        for article in cat_data.get("articles", []):
            headline = article["title"]
            if article.get("description"):
                headline += f" — {article['description']}"
            all_headlines.append(f"[{cat_data['category'].upper()}] {headline}")

    total_articles = sum(len(v.get("articles", [])) for v in results.values())
    logger.info(
        f"NewsAPI | Complete — {total_articles} articles fetched "
        f"across {len(NEWS_QUERIES)} categories"
    )

    return {"by_category": results, "all_headlines": all_headlines}
