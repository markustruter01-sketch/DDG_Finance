"""
jerome_market_context.py — Market data assembler for Jerome commodity bot.
Fetches commodity ETF prices + macro indicators from Yahoo Finance v8 HTTP API.

Uses direct HTTP (not yfinance library — yfinance is unreliable in this environment).
Same approach as forex-engine/market_context.py.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

logger = logging.getLogger("jerome.context")

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_commodity_context(
    open_positions: list[dict],
    universe: list[str],
) -> dict:
    """Assemble full commodity + macro context for Groq analysis."""
    return {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "open_positions":   open_positions,
        "commodity_prices": _fetch_commodity_prices(universe),
        "macro_indicators": _fetch_macro_indicators(),
    }


def _yahoo_daily(ticker: str, days: int = 35) -> list[float] | None:
    """
    Fetch daily closing prices from Yahoo Finance v8 API.
    Returns list of closes (oldest first) or None on failure.
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
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes_raw = quotes.get("close", [])
        closes = [c for c in closes_raw if c is not None]
        return closes if closes else None
    except Exception as exc:
        logger.debug(f"Jerome | Yahoo fetch failed for {ticker}: {exc}")
        return None


def _fetch_commodity_prices(universe: list[str]) -> dict:
    """Fetch price history for all commodity ETFs via direct Yahoo HTTP."""
    result = {}
    for sym in universe:
        closes = _yahoo_daily(sym, days=35)
        if not closes or len(closes) < 5:
            logger.debug(f"Jerome | No usable data for {sym}")
            continue
        current  = closes[-1]
        high_30d = max(closes[-30:]) if len(closes) >= 30 else max(closes)
        low_30d  = min(closes[-30:]) if len(closes) >= 30 else min(closes)
        result[sym] = {
            "price":        round(current, 2),
            "return_1d":    round((closes[-1] / closes[-2] - 1) * 100, 3) if len(closes) >= 2  else 0,
            "return_5d":    round((closes[-1] / closes[-6] - 1) * 100, 3) if len(closes) >= 6  else 0,
            "return_20d":   round((closes[-1] / closes[-21] - 1) * 100, 3) if len(closes) >= 21 else 0,
            "high_30d":     round(high_30d, 2),
            "low_30d":      round(low_30d, 2),
            "vs_30d_range": round(
                (current - low_30d) / (high_30d - low_30d) * 100, 1
            ) if high_30d != low_30d else 50.0,
        }
    logger.info(f"Jerome | Commodity prices fetched: {len(result)}/{len(universe)}")
    return result


def _fetch_macro_indicators() -> dict:
    """Fetch macro regime indicators — DXY, gold, oil, SPY, VIX, 10Y yield, TIPS."""
    indicators = {
        "DXY":  "DX-Y.NYB",
        "GOLD": "GC=F",
        "OIL":  "CL=F",
        "SPY":  "SPY",
        "VIX":  "^VIX",
        "TNX":  "^TNX",
        "TIP":  "TIP",
    }
    result = {}
    for label, ticker in indicators.items():
        closes = _yahoo_daily(ticker, days=15)
        if not closes or len(closes) < 2:
            logger.debug(f"Jerome | No macro data for {label}")
            continue
        result[label] = {
            "price":     round(closes[-1], 2),
            "return_1d": round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else 0,
            "return_5d": round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else 0,
            "trend":     "up" if len(closes) >= 5 and closes[-1] > closes[-5] else "down",
        }
    logger.info(f"Jerome | Macro indicators fetched: {len(result)}/{len(indicators)}")
    return result
