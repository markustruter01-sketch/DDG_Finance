"""Signal generation + ranking. EMA20/50 + ADX(14) + ATR(14) via ta library."""
import ccxt
import pandas as pd

try:
    import pandas_ta as pta
    _USE_PTA = True
except ImportError:
    import ta
    _USE_PTA = False

from config import EMA_FAST, EMA_SLOW, ADX_PERIOD, ADX_THRESHOLD, ATR_PERIOD

_exchange = ccxt.kucoin({
    "enableRateLimit": True,
})


def fetch_ohlcv(pair: str, limit: int = 60) -> pd.DataFrame:
    candidates = [pair, pair.replace("/USDT", "/USD"), f"1000{pair.split('/')[0]}/USDT"]
    for candidate in candidates:
        try:
            bars = _exchange.fetch_ohlcv(candidate, "1d", limit=limit)
            if bars and len(bars) >= EMA_SLOW + 5:
                df = pd.DataFrame(
                    bars, columns=["ts", "open", "high", "low", "close", "volume"]
                )
                df = df.astype({"open": float, "high": float, "low": float,
                                "close": float, "volume": float})
                return df
        except Exception:
            continue
    return None


def compute_indicators(df: pd.DataFrame) -> dict:
    if _USE_PTA:
        df["ema20"] = pta.ema(df["close"], length=EMA_FAST)
        df["ema50"] = pta.ema(df["close"], length=EMA_SLOW)
        adx_df      = pta.adx(df["high"], df["low"], df["close"], length=ADX_PERIOD)
        df["adx"]   = adx_df[f"ADX_{ADX_PERIOD}"]
        df["atr"]   = pta.atr(df["high"], df["low"], df["close"], length=ATR_PERIOD)
    else:
        df["ema20"] = ta.trend.ema_indicator(df["close"], window=EMA_FAST)
        df["ema50"] = ta.trend.ema_indicator(df["close"], window=EMA_SLOW)
        df["adx"]   = ta.trend.adx(df["high"], df["low"], df["close"], window=ADX_PERIOD)
        df["atr"]   = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=ATR_PERIOD
        )
    last = df.iloc[-1]
    return {
        "close": float(last["close"]),
        "ema20": float(last["ema20"]),
        "ema50": float(last["ema50"]),
        "adx":   float(last["adx"]),
        "atr":   float(last["atr"]),
    }


def score_symbol(ind: dict) -> dict:
    """Returns direction + abs momentum_score. flat if ADX below threshold."""
    if ind["adx"] < ADX_THRESHOLD:
        return {"direction": "flat", "score": 0.0, **ind}
    if ind["ema20"] > ind["ema50"]:
        direction = "long"
    elif ind["ema20"] < ind["ema50"]:
        direction = "short"
    else:
        return {"direction": "flat", "score": 0.0, **ind}
    score = abs((ind["ema20"] - ind["ema50"]) / ind["ema50"])
    return {"direction": direction, "score": score, **ind}


def rank_universe(universe: list) -> list:
    """Returns list of {symbol, direction, score, ...} sorted by score desc.
    Flat (no signal) entries are excluded."""
    ranked = []
    for u in universe:
        df = fetch_ohlcv(u["binance_pair"])
        if df is None:
            continue
        ind = compute_indicators(df)
        if any(pd.isna(ind[k]) for k in ("adx", "ema20", "ema50", "atr")):
            continue
        scored = score_symbol(ind)
        if scored["direction"] == "flat":
            continue
        scored["symbol"]      = u["symbol"]
        scored["binance_pair"] = u["binance_pair"]
        ranked.append(scored)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
