"""
bot7_market_context.py — Macro context assembler for Bot #7 (Macro Bond Trader).

Fetches fixed income macro data for Groq analysis:
  - Treasury yields (10Y via ^TNX, short-end via SHY performance)
  - 2Y/10Y curve shape (SHY vs TLT price return spread as proxy)
  - Inflation expectations (TIP vs IEF relative performance)
  - Credit conditions (HYG vs LQD spread proxy)
  - USD direction (DXY)
  - Risk sentiment (SPY trend, VIX)
  - Bond universe price history

Uses direct Yahoo Finance v8 HTTP API — no yfinance library.
Follows jerome_market_context.py exactly.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

logger = logging.getLogger("bot7.context")

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

UNIVERSE = ["TLT", "IEF", "SHY", "TIP", "HYG", "LQD", "EMB"]


def get_bond_context(
    open_positions: list[dict],
    universe: list[str] | None = None,
) -> dict:
    """Assemble full macro bond context for Groq analysis."""
    if universe is None:
        universe = UNIVERSE
    return {
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "open_positions":    open_positions,
        "bond_prices":       _fetch_bond_prices(universe),
        "macro_indicators":  _fetch_macro_indicators(),
        "yield_environment": _fetch_yield_environment(),
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
        logger.debug(f"Bot7 | Yahoo fetch failed for {ticker}: {exc}")
        return None


def _fetch_bond_prices(universe: list[str]) -> dict:
    """Fetch price history for all bond ETFs in the universe."""
    result = {}
    for sym in universe:
        closes = _yahoo_daily(sym, days=35)
        if not closes or len(closes) < 5:
            logger.debug(f"Bot7 | No usable data for {sym}")
            continue
        current  = closes[-1]
        high_30d = max(closes[-30:]) if len(closes) >= 30 else max(closes)
        low_30d  = min(closes[-30:]) if len(closes) >= 30 else min(closes)
        result[sym] = {
            "price":        round(current, 2),
            "return_1d":    round((closes[-1] / closes[-2] - 1) * 100, 3) if len(closes) >= 2  else 0,
            "return_5d":    round((closes[-1] / closes[-6] - 1) * 100, 3) if len(closes) >= 6  else 0,
            "return_20d":   round((closes[-1] / closes[-21] - 1) * 100, 3) if len(closes) >= 21 else 0,
            "return_30d":   round((closes[-1] / closes[-31] - 1) * 100, 3) if len(closes) >= 31 else 0,
            "high_30d":     round(high_30d, 2),
            "low_30d":      round(low_30d, 2),
            "vs_30d_range": round(
                (current - low_30d) / (high_30d - low_30d) * 100, 1
            ) if high_30d != low_30d else 50.0,
        }
    logger.info(f"Bot7 | Bond prices fetched: {len(result)}/{len(universe)}")
    return result


def _fetch_macro_indicators() -> dict:
    """
    Fetch broad macro regime indicators — SPY, VIX, DXY, GLD, TNX.
    Same approach as jerome_market_context._fetch_macro_indicators().
    """
    indicators = {
        "DXY":  "DX-Y.NYB",
        "SPY":  "SPY",
        "VIX":  "^VIX",
        "GLD":  "GLD",
        "TNX":  "^TNX",  # 10Y yield * 100 = basis points
    }
    result = {}
    for label, ticker in indicators.items():
        closes = _yahoo_daily(ticker, days=15)
        if not closes or len(closes) < 2:
            logger.debug(f"Bot7 | No macro data for {label}")
            continue
        result[label] = {
            "price":     round(closes[-1], 2),
            "return_1d": round((closes[-1] / closes[-2] - 1) * 100, 2) if len(closes) >= 2 else 0,
            "return_5d": round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else 0,
            "trend":     "up" if len(closes) >= 5 and closes[-1] > closes[-5] else "down",
        }
    logger.info(f"Bot7 | Macro indicators fetched: {len(result)}/{len(indicators)}")
    return result


def _fetch_yield_environment() -> dict:
    """
    Construct yield curve environment from ETF price data:
      - 10Y yield: ^TNX (Yahoo) — value in basis points / 100
      - Curve shape: TLT return vs SHY return — positive = curve steepening
        (long bonds outperforming short = curve bull flattening)
      - Inflation expectations: TIP 20d return vs IEF 20d return
        (TIP outperforming IEF = inflation expectations rising)
      - Credit stress: HYG 20d return vs LQD 20d return
        (HYG underperforming LQD = credit spreads widening = risk-off)
    """
    result = {}

    # 10Y Treasury yield level
    tnx = _yahoo_daily("^TNX", days=35)
    if tnx and len(tnx) >= 2:
        yield_10y    = tnx[-1] / 100      # Yahoo returns yield * 100
        yield_10y_30d_ago = tnx[-min(31, len(tnx))] / 100
        result["yield_10y"] = {
            "current":       round(yield_10y, 3),
            "change_30d_bp": round((yield_10y - yield_10y_30d_ago) * 100, 1),
            "trend":         "rising" if yield_10y > yield_10y_30d_ago else "falling",
        }

    # Curve shape via TLT vs SHY relative return (20d)
    tlt = _yahoo_daily("TLT", days=25)
    shy = _yahoo_daily("SHY", days=25)
    if tlt and shy and len(tlt) >= 21 and len(shy) >= 21:
        tlt_20d = (tlt[-1] / tlt[-21] - 1) * 100
        shy_20d = (shy[-1] / shy[-21] - 1) * 100
        spread  = tlt_20d - shy_20d
        result["curve_shape"] = {
            "tlt_return_20d":  round(tlt_20d, 3),
            "shy_return_20d":  round(shy_20d, 3),
            "tlt_minus_shy":   round(spread, 3),
            "interpretation": (
                "bull_steepening"  if spread > 0.5  else
                "bull_flattening"  if spread < -0.5 else
                "neutral"
            ),
        }

    # Inflation expectations: TIP vs IEF 20d return
    tip = _yahoo_daily("TIP", days=25)
    ief = _yahoo_daily("IEF", days=25)
    if tip and ief and len(tip) >= 21 and len(ief) >= 21:
        tip_20d = (tip[-1] / tip[-21] - 1) * 100
        ief_20d = (ief[-1] / ief[-21] - 1) * 100
        breakeven_proxy = tip_20d - ief_20d
        result["inflation_expectations"] = {
            "tip_return_20d":       round(tip_20d, 3),
            "ief_return_20d":       round(ief_20d, 3),
            "breakeven_proxy_pct":  round(breakeven_proxy, 3),
            "direction":            "rising" if breakeven_proxy > 0.2 else (
                                    "falling" if breakeven_proxy < -0.2 else "stable"),
        }

    # Credit stress: HYG vs LQD 20d return
    hyg = _yahoo_daily("HYG", days=25)
    lqd = _yahoo_daily("LQD", days=25)
    if hyg and lqd and len(hyg) >= 21 and len(lqd) >= 21:
        hyg_20d = (hyg[-1] / hyg[-21] - 1) * 100
        lqd_20d = (lqd[-1] / lqd[-21] - 1) * 100
        credit_spread_proxy = lqd_20d - hyg_20d
        result["credit_conditions"] = {
            "hyg_return_20d":        round(hyg_20d, 3),
            "lqd_return_20d":        round(lqd_20d, 3),
            "spread_proxy_pct":      round(credit_spread_proxy, 3),
            "direction":             "widening" if credit_spread_proxy > 0.3 else (
                                     "tightening" if credit_spread_proxy < -0.3 else "stable"),
            "risk_signal":           "risk_off" if credit_spread_proxy > 0.5 else "risk_on",
        }

    logger.info(f"Bot7 | Yield environment: {list(result.keys())}")
    return result
