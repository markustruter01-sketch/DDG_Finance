"""
Fear & Greed Index — Dual Sentiment Layer
-------------------------------------------
Fetches two sentiment indicators:
  1. Crypto Fear & Greed Index (alternative.me — free, no key)
  2. CNN Fear & Greed proxy (computed from VIX + market momentum)

Both are cached for 1 hour to avoid rate limits.
Used by:
  - System prompt injection (feedback_injection.py)
  - GET /sentiment API endpoint
  - Dashboard sentiment gauge
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

_cache: dict[str, Any] = {
    "crypto_fg": None,
    "market_fg": None,
    "ts": 0,
}
_CACHE_TTL = 3600


def _fetch_crypto_fear_greed() -> dict:
    try:
        r = httpx.get("https://api.alternative.me/fng/?limit=1&format=json", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        return {
            "value": int(data["value"]),
            "label": data["value_classification"],
            "timestamp": data["timestamp"],
        }
    except Exception as exc:
        logger.warning(f"Sentiment | Crypto Fear & Greed fetch failed: {exc}")
        return {"value": None, "label": "unavailable", "error": str(exc)}


def _compute_market_fear_greed() -> dict:
    try:
        from data.yfinance_client import get_cached_market_data
        market_data = get_cached_market_data()
        if not market_data:
            return {"value": 50, "label": "Neutral", "source": "default_no_data"}

        by_ticker = market_data.get("by_ticker", {})
        spy = by_ticker.get("SPY", {})

        spy_mom_3 = spy.get("momentum_3mo", "insufficient_data")
        spy_mom_6 = spy.get("momentum_6mo", "insufficient_data")
        spy_rsi = spy.get("rsi_14d")
        spy_z = spy.get("z_score_200d")
        spy_vol = spy.get("volatility_20d_annualised_pct")

        score = 50.0

        if spy_mom_3 == "positive":
            score += 10
        elif spy_mom_3 == "negative":
            score -= 10

        if spy_mom_6 == "positive":
            score += 10
        elif spy_mom_6 == "negative":
            score -= 10

        if spy_rsi is not None:
            if spy_rsi > 70:
                score += 15
            elif spy_rsi > 60:
                score += 5
            elif spy_rsi < 30:
                score -= 15
            elif spy_rsi < 40:
                score -= 5

        if spy_z is not None:
            if spy_z > 2.0:
                score += 10
            elif spy_z > 1.0:
                score += 5
            elif spy_z < -1.0:
                score -= 10
            elif spy_z < -2.0:
                score -= 15

        if spy_vol is not None:
            if spy_vol > 30:
                score -= 10
            elif spy_vol > 20:
                score -= 5
            elif spy_vol < 12:
                score += 5

        score = max(0, min(100, score))
        value = int(score)

        if value <= 20:
            label = "Extreme Fear"
        elif value <= 40:
            label = "Fear"
        elif value <= 60:
            label = "Neutral"
        elif value <= 80:
            label = "Greed"
        else:
            label = "Extreme Greed"

        return {
            "value": value,
            "label": label,
            "source": "computed_from_spy",
            "components": {
                "momentum_3mo": spy_mom_3,
                "momentum_6mo": spy_mom_6,
                "rsi_14d": spy_rsi,
                "z_score_200d": spy_z,
                "volatility_20d": spy_vol,
            },
        }
    except Exception as exc:
        logger.warning(f"Sentiment | Market F&G computation failed: {exc}")
        return {"value": 50, "label": "Neutral", "error": str(exc)}


def get_sentiment(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["ts"] > 0 and (now - _cache["ts"]) < _CACHE_TTL:
        return {
            "crypto_fear_greed": _cache["crypto_fg"],
            "market_fear_greed": _cache["market_fg"],
            "cached": True,
            "cache_age_seconds": int(now - _cache["ts"]),
        }

    crypto_fg = _fetch_crypto_fear_greed()
    market_fg = _compute_market_fear_greed()

    _cache["crypto_fg"] = crypto_fg
    _cache["market_fg"] = market_fg
    _cache["ts"] = now

    logger.info(
        f"Sentiment | Crypto F&G: {crypto_fg.get('value')} ({crypto_fg.get('label')}) | "
        f"Market F&G: {market_fg.get('value')} ({market_fg.get('label')})"
    )

    return {
        "crypto_fear_greed": crypto_fg,
        "market_fear_greed": market_fg,
        "cached": False,
        "cache_age_seconds": 0,
    }


def get_sentiment_prompt_block(crypto_only: bool = False) -> str:
    sentiment = get_sentiment()
    crypto_fg = sentiment["crypto_fear_greed"]
    market_fg = sentiment["market_fear_greed"]

    lines = ["\n=== SENTIMENT INTELLIGENCE (FEAR & GREED INDICES) ==="]

    if crypto_fg.get("value") is not None:
        lines.append(
            f"Crypto Fear & Greed Index: {crypto_fg['value']}/100 ({crypto_fg['label']})"
        )
        if crypto_fg["value"] <= 20:
            lines.append("  -> EXTREME FEAR: contrarian buy signal if technicals align")
        elif crypto_fg["value"] >= 80:
            lines.append("  -> EXTREME GREED: consider reducing crypto exposure or parking in SGOV")

    if not crypto_only and market_fg.get("value") is not None:
        lines.append(
            f"Market Fear & Greed Index: {market_fg['value']}/100 ({market_fg['label']})"
        )
        if market_fg["value"] <= 20:
            lines.append("  -> EXTREME FEAR in equities: contrarian opportunity if momentum confirms")
        elif market_fg["value"] >= 80:
            lines.append("  -> EXTREME GREED in equities: tighten stops, consider defensive positioning")

    lines.append("")
    return "\n".join(lines)
