"""
Trading Platform — FastAPI Entry Point
Phase 1 stub: exposes a /data/snapshot endpoint to verify data ingestion.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from config.settings import settings
from data.fred_client import fetch_macro_data
from data.yfinance_client import fetch_market_data
from data.news_client import fetch_news


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.add(
        settings.log_file,
        level=settings.log_level,
        rotation="1 day",
        retention="30 days",
        compression="gz",
    )
    logger.info("Trading platform starting up...")
    yield
    logger.info("Trading platform shutting down.")


app = FastAPI(
    title="Quantitative Trading Platform",
    description="AI-driven macro quantitative trading system",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/data/snapshot")
async def data_snapshot():
    """
    Phase 1 test endpoint: fetches macro, market, and news data concurrently
    and returns a combined snapshot. Used to validate all three data clients.
    """
    logger.info("Data snapshot requested — running all three ingestion clients...")

    macro_task = fetch_macro_data(lookback_days=14)
    market_task = fetch_market_data(period="1mo")
    news_task = fetch_news(lookback_days=2)

    macro_data, market_data, news_data = await asyncio.gather(
        macro_task, market_task, news_task
    )

    return {
        "macro": macro_data,
        "market": market_data,
        "news_headlines": news_data["all_headlines"],
        "news_by_category": {
            cat: len(v.get("articles", [])) for cat, v in news_data["by_category"].items()
        },
    }
