"""
Market Data Client — Regime-Switching Architecture
----------------------------------------------------
Fetches OHLCV price data, trailing returns, moving averages, and momentum
signals for the FIXED asset universe.

Fixed universe (16 instruments + SGOV):
  Equities (Sectors): SPY, QQQ, XLK, XLF, XLV, XLE, IWM
  Safe Havens/Bonds : TLT, IEF, GLD, SLV
  Commodities       : USO, PDBC
  Crypto Spot       : BTC/USD, ETH/USD
  Cash Equiv        : SGOV

Momentum signals (key for regime-switching allocation):
  - 3-month MA (≈63 trading days): price vs MA → "positive" / "negative"
  - 6-month MA (≈126 trading days): price vs MA → "positive" / "negative"
  - These are passed to the LLM to enforce trend-following (Bull/Bear)
    or mean-reversion (Sideways) rules.

PRIMARY: Alpaca Market Data API (free tier, no IP restrictions)
FALLBACK: graceful error handling with partial data allowed
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
ALPACA_CRYPTO_BASE_URL = "https://data.alpaca.markets/v1beta3/crypto/us"

UNIVERSE: dict[str, list[str]] = {
    "equity":      ["SPY", "QQQ", "XLK", "XLF", "XLV", "XLE", "IWM"],
    "safe_haven":  ["TLT", "IEF", "GLD", "SLV"],
    "commodity":   ["USO", "PDBC"],
    "crypto_spot": ["BTC/USD", "ETH/USD"],
    "cash":        ["SGOV"],
}

ETF_CATEGORIES = ["equity", "safe_haven", "commodity", "cash"]
ALL_TICKERS: list[str] = [t for tickers in UNIVERSE.values() for t in tickers]
ETF_TICKERS: list[str] = [t for cat in ETF_CATEGORIES for t in UNIVERSE[cat]]
CRYPTO_SPOT_TICKERS: list[str] = UNIVERSE["crypto_spot"]

MA_3MO_BARS  = 63
MA_6MO_BARS  = 126
MA_200D_BARS = 200
RSI_PERIOD   = 14

_cached_market_data: dict | None = None


def get_cached_market_data() -> dict | None:
    """Return the most-recently fetched market data (or None on first boot)."""
    return _cached_market_data


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder's RSI using simple average seed (standard for quant systems)."""
    if len(closes) < period + 1:
        return None
    recent = closes[-(period + 1):]
    gains, losses = [], []
    for i in range(1, len(recent)):
        diff = recent[i] - recent[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1 + rs)))


def _is_retryable_http_error(exc: BaseException) -> bool:
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
    if settings.alpaca_api_key and settings.alpaca_api_key != "dummy":
        return {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
    return {}


def _compute_metrics(ticker: str, bars: list[dict]) -> dict[str, Any]:
    if not bars:
        return {"ticker": ticker, "error": "no data"}

    closes = [float(b["c"]) for b in bars]

    latest_price = closes[-1]
    latest_date_str = bars[-1]["t"][:10]

    def pct_chg(n: int) -> float | None:
        return float((closes[-1] / closes[-n] - 1) * 100) if len(closes) >= n else None

    ret_1d  = pct_chg(2)
    ret_5d  = pct_chg(5)
    ret_20d = pct_chg(20)
    ret_60d = pct_chg(60)

    daily_returns = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
    if len(daily_returns) >= 20:
        last20 = daily_returns[-20:]
        mean = sum(last20) / len(last20)
        variance = sum((r - mean) ** 2 for r in last20) / len(last20)
        volatility_20d = float((variance ** 0.5) * (252 ** 0.5) * 100)
    else:
        volatility_20d = None

    ma_3mo: float | None = None
    ma_6mo: float | None = None
    momentum_3mo: str = "insufficient_data"
    momentum_6mo: str = "insufficient_data"

    if len(closes) >= MA_3MO_BARS:
        ma_3mo = float(np.mean(closes[-MA_3MO_BARS:]))
        momentum_3mo = "positive" if latest_price > ma_3mo else "negative"

    if len(closes) >= MA_6MO_BARS:
        ma_6mo = float(np.mean(closes[-MA_6MO_BARS:]))
        momentum_6mo = "positive" if latest_price > ma_6mo else "negative"

    z_score_200d: float | None = None
    if len(closes) >= MA_200D_BARS:
        window_200 = closes[-MA_200D_BARS:]
        sma_200  = float(np.mean(window_200))
        std_200  = float(np.std(window_200, ddof=0))
        z_score_200d = round((latest_price - sma_200) / std_200, 3) if std_200 > 0 else 0.0

    rsi_14d: float | None = _compute_rsi(closes)
    if rsi_14d is not None:
        rsi_14d = round(rsi_14d, 2)

    is_overheated = bool(
        (z_score_200d is not None and z_score_200d > 2.0) or
        (rsi_14d is not None and rsi_14d > 75)
    )

    return {
        "ticker":                       ticker,
        "latest_price":                 latest_price,
        "latest_date":                  latest_date_str,
        "return_1d_pct":                ret_1d,
        "return_5d_pct":                ret_5d,
        "return_20d_pct":               ret_20d,
        "return_60d_pct":               ret_60d,
        "annualized_volatility_20d_pct": volatility_20d,
        "volatility_20d_annualised_pct": volatility_20d,
        "ma_3mo":                       round(ma_3mo, 4) if ma_3mo else None,
        "ma_6mo":                       round(ma_6mo, 4) if ma_6mo else None,
        "momentum_3mo":                 momentum_3mo,
        "momentum_6mo":                 momentum_6mo,
        "z_score_200d":                 z_score_200d,
        "rsi_14d":                      rsi_14d,
        "is_overheated":                is_overheated,
        "data_points":                  len(closes),
        "closes":                       closes,
        "bars":                         bars,
    }


async def _fetch_bars_alpaca(
    client: httpx.AsyncClient,
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    @_make_retry_decorator()
    async def _request() -> list[dict]:
        url = f"{ALPACA_DATA_BASE_URL}/stocks/{ticker}/bars"
        params = {
            "timeframe": "1Day",
            "start": start_date,
            "end": end_date,
            "limit": 400,
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

    return _compute_metrics(ticker, bars)


async def _fetch_bars_crypto(
    client: httpx.AsyncClient,
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    @_make_retry_decorator()
    async def _request() -> list[dict]:
        url = f"{ALPACA_CRYPTO_BASE_URL}/bars"
        params = {
            "symbols": ticker,
            "timeframe": "1Day",
            "start": start_date + "T00:00:00Z",
            "end": end_date + "T23:59:59Z",
        }
        response = await client.get(
            url,
            params=params,
            headers=_alpaca_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("bars", {}).get(ticker, [])

    try:
        bars = await _request()
    except Exception as exc:
        logger.warning(f"Alpaca Crypto Data | {ticker}: {exc}")
        return {"ticker": ticker, "error": str(exc)}

    return _compute_metrics(ticker, bars)


async def fetch_market_data(period: str = "6mo", crypto_only: bool = False) -> dict[str, Any]:
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 180)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=period_days)).isoformat()

    if crypto_only:
        tickers_to_fetch = CRYPTO_SPOT_TICKERS
        categories = {"crypto_spot": CRYPTO_SPOT_TICKERS}
    else:
        tickers_to_fetch = ALL_TICKERS
        categories = UNIVERSE

    logger.info(
        f"Market Data | Fetching {len(tickers_to_fetch)} tickers via Alpaca "
        f"({'crypto-only' if crypto_only else 'full universe'}) "
        f"({start_date} → {end_date})"
    )

    async with httpx.AsyncClient() as client:
        tasks = []
        for ticker in tickers_to_fetch:
            if "/" in ticker:
                tasks.append(_fetch_bars_crypto(client, ticker, start_date, end_date))
            else:
                tasks.append(_fetch_bars_alpaca(client, ticker, start_date, end_date))
        results_list = await asyncio.gather(*tasks)

    by_ticker: dict[str, Any] = {r["ticker"]: r for r in results_list}
    by_category: dict[str, dict[str, Any]] = {
        cat: {t: by_ticker.get(t, {"ticker": t, "error": "missing"}) for t in tickers}
        for cat, tickers in categories.items()
    }

    fetched = sum(1 for v in by_ticker.values() if "error" not in v)
    logger.info(
        f"Market Data | Complete — {fetched}/{len(tickers_to_fetch)} tickers fetched successfully"
    )

    result = {"by_ticker": by_ticker, "by_category": by_category}

    global _cached_market_data
    _cached_market_data = result

    return result


async def fetch_single_ticker(ticker: str, period: str = "6mo") -> dict[str, Any]:
    period_days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}.get(period, 180)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=period_days)).isoformat()
    logger.info(f"Market Data | Fetching single ticker: {ticker}")
    async with httpx.AsyncClient() as client:
        if "/" in ticker:
            return await _fetch_bars_crypto(client, ticker, start_date, end_date)
        return await _fetch_bars_alpaca(client, ticker, start_date, end_date)
