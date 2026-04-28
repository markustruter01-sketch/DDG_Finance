"""
market_context.py — Assembles market context for Groq/Gemini investment decisions.
Fetches prices, returns, macro indicators, and current positions.
Called once per Groq cycle (twice daily: 08:00 UTC and 20:00 UTC).

Uses direct HTTP requests to Yahoo Finance v8 API (same approach as indicators.py)
rather than the yfinance library, which is unreliable in this environment.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("navigator.market_context")

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_market_context(open_positions: list[dict]) -> dict:
    """
    Assembles full market context for Groq/Gemini analysis.

    Parameters
    ----------
    open_positions : list of position dicts with keys:
        pair, direction, entry_price, unrealised_pnl_usd, hours_held

    Returns a structured dict ready to be serialised into a prompt.
    """
    errors: list[str] = []

    forex_pairs     = _get_forex_prices(errors)
    macro_indicators = _get_macro_indicators(errors)

    context = {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "open_positions":   open_positions,
        "forex_pairs":      forex_pairs,
        "macro_indicators": macro_indicators,
        "errors":           errors,
    }
    return context


def _yahoo_daily(ticker: str, days: int = 30) -> list[float] | None:
    """
    Fetch up to `days` daily closing prices from Yahoo Finance v8 API.
    Returns a list of closes (oldest first) or None on failure.
    Mirrors _fetch_yahoo_direct() in indicators.py.
    """
    import requests
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        r = result[0]
        quotes = r.get("indicators", {}).get("quote", [{}])[0]
        closes_raw = quotes.get("close", [])
        closes = [c for c in closes_raw if c is not None]
        return closes if closes else None
    except Exception as exc:
        logger.debug(f"market_context | Yahoo fetch failed for {ticker}: {exc}")
        return None


def _get_forex_prices(errors: list[str]) -> dict:
    """Fetch current prices and recent returns for all Navigator pairs."""
    pairs = {
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
        "AUD/USD": "AUDUSD=X",
        "USD/CAD": "CAD=X",
        "USD/CHF": "CHF=X",
        "EUR/GBP": "EURGBP=X",
        "EUR/JPY": "EURJPY=X",
        "GBP/JPY": "GBPJPY=X",
        "AUD/JPY": "AUDJPY=X",
    }
    result = {}
    for label, ticker in pairs.items():
        closes = _yahoo_daily(ticker, days=30)
        if not closes or len(closes) < 2:
            logger.debug(f"market_context | No usable data for {label}")
            errors.append(f"price_{label}: no data")
            continue
        current   = closes[-1]
        high_30d  = max(closes)
        low_30d   = min(closes)
        result[label] = {
            "price":        round(current, 5),
            "return_1d":    round((closes[-1] / closes[-2] - 1) * 100, 3) if len(closes) >= 2 else None,
            "return_5d":    round((closes[-1] / closes[-6] - 1) * 100, 3) if len(closes) >= 6 else None,
            "return_20d":   round((closes[-1] / closes[-21] - 1) * 100, 3) if len(closes) >= 21 else None,
            "high_30d":     round(high_30d, 5),
            "low_30d":      round(low_30d, 5),
            "vs_30d_range": round(
                (current - low_30d) / (high_30d - low_30d) * 100, 1
            ) if high_30d != low_30d else 50.0,
        }
    return result


def _get_macro_indicators(errors: list[str]) -> dict:
    """Fetch macro context — DXY, gold, S&P, VIX, oil as regime indicators."""
    indicators = {
        "DXY":  "DX-Y.NYB",
        "GOLD": "GC=F",
        "SPY":  "SPY",
        "VIX":  "^VIX",
        "OIL":  "CL=F",
    }
    result = {}
    for label, ticker in indicators.items():
        closes = _yahoo_daily(ticker, days=10)
        if not closes or len(closes) < 2:
            logger.debug(f"market_context | No usable macro data for {label}")
            errors.append(f"macro_{label}: no data")
            continue
        result[label] = {
            "price":     round(closes[-1], 2),
            "return_5d": round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None,
            "trend":     (
                "up"   if len(closes) >= 5 and closes[-1] > closes[-5] else
                "down" if len(closes) >= 5 else
                "unknown"
            ),
        }
    return result
