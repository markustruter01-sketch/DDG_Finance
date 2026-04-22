"""
indicators.py — Pure Python/pandas technical indicators for Forex H4 data.
No LLM involvement. All math is algorithmic.
"""

import pandas as pd
import numpy as np


def calculate_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(highs)):
        h = highs[i]
        l = lows[i]
        c_prev = closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    # Wilder's EMA smoothing: seed with SMA of first `period` true ranges,
    # then apply the recursive filter atr = (atr * (period-1) + tr) / period.
    # Matches math_auditor.verified_atr() exactly — do NOT use np.mean() here.
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """
    RSI using Wilder's EMA smoothing — identical algorithm to kraken-bot/logic.py.
    Simple-average (SMA) RSI gives different values; Wilder's is the industry standard.
    """
    if len(closes) < period + 1:
        return 50.0

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains   = [max(c, 0.0) for c in changes]
    losses  = [abs(min(c, 0.0)) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0

    rs  = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def calculate_ema(prices: list[float], period: int) -> float:
    """Calculate EMA for trend direction filter."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 6)


def fetch_h4_candles(symbol: str, count: int = 100) -> pd.DataFrame:
    df = _fetch_yahoo_direct(symbol)
    if df is None or df.empty:
        df = _fetch_yfinance_fallback(symbol)
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.reset_index()
    if "Datetime" in df.columns:
        df = df.rename(columns={"Datetime": "Date"})

    df["Date"] = pd.to_datetime(df["Date"], utc=True)

    df = df.set_index("Date")
    h4 = df.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    h4 = h4.reset_index()
    return h4.tail(count)


def _fetch_yahoo_direct(symbol: str) -> pd.DataFrame | None:
    import requests as _req
    from datetime import datetime, timezone

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "60d", "interval": "1h"}
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = _req.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None

        r = result[0]
        timestamps = r.get("timestamp", [])
        quotes = r.get("indicators", {}).get("quote", [{}])[0]

        if not timestamps or not quotes:
            return None

        df = pd.DataFrame({
            "Date": pd.to_datetime(timestamps, unit="s", utc=True),
            "Open": quotes.get("open", []),
            "High": quotes.get("high", []),
            "Low": quotes.get("low", []),
            "Close": quotes.get("close", []),
            "Volume": quotes.get("volume", [0] * len(timestamps)),
        })
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return df if not df.empty else None
    except Exception:
        return None


def _fetch_yfinance_fallback(symbol: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="60d", interval="1h")
        return df if not df.empty else None
    except Exception:
        return None
