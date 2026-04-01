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

    atr = np.mean(true_ranges[-period:])
    return float(atr)


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period):]

    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]

    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi)


def fetch_h4_candles(symbol: str, count: int = 100) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    df = ticker.history(period="60d", interval="1h")

    if df.empty:
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
