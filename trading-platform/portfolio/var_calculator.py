"""
var_calculator.py  —  Historical Simulation Value-at-Risk
==========================================================
Computes the portfolio-level 1-day VaR using the historical simulation
method (empirical distribution of past P&L — no parametric assumptions).

Only symbols with a price history in yfinance are included; missing symbols
are silently skipped so the function always returns gracefully.

Design
------
1. Extract held symbols from ``positions``.
2. Fetch ``lookback_days`` of daily closes via yfinance.
3. Compute per-position daily P&L series weighted by ``market_value``.
4. Aggregate to a single portfolio P&L series by summing across positions.
5. Return ``-np.percentile(pnl_series, (1 - confidence) * 100)`` as the VaR.
   Negative loss (i.e. the extreme downside) is returned as a positive number.

Returns 0.0 gracefully when:
  * ``positions`` is empty.
  * yfinance returns no data for any held symbol.
  * Fewer than 5 observations are available.
"""

from __future__ import annotations

import datetime
from typing import Any

from loguru import logger


def compute_daily_var(
    positions: list[dict],
    confidence: float = 0.95,
    lookback_days: int = 30,
) -> float:
    """
    Compute 1-day portfolio VaR via historical simulation.

    Parameters
    ----------
    positions : list[dict]
        Each dict must have ``"symbol"`` (str) and ``"market_value"`` (float).
        Crypto pairs like ``"BTCUSD"`` are automatically mapped to yfinance
        tickers (e.g. ``"BTC-USD"``).
        Zero or negative ``market_value`` entries are skipped.
    confidence : float
        Confidence level, e.g. 0.95 for 95 % VaR (default 0.95).
    lookback_days : int
        Calendar days of history to fetch (default 30 → ~21 trading days).

    Returns
    -------
    float
        VaR as a fraction of total portfolio value, e.g. 0.03 = 3 %.
        Returns 0.0 on empty positions or insufficient data.
    """
    if not positions:
        return 0.0

    # ── Filter to positive-value positions ───────────────────────────────────
    valid = [
        p for p in positions
        if float(p.get("market_value", 0.0) or 0.0) > 0
    ]
    if not valid:
        return 0.0

    total_value = sum(float(p["market_value"]) for p in valid)
    if total_value <= 0:
        return 0.0

    # ── Map symbols to yfinance tickers ──────────────────────────────────────
    symbol_map = {}
    for p in valid:
        raw = str(p["symbol"]).upper()
        yf_ticker = _to_yfinance_ticker(raw)
        symbol_map[raw] = yf_ticker

    yf_tickers = list(set(symbol_map.values()))
    if not yf_tickers:
        return 0.0

    # ── Fetch historical closes ───────────────────────────────────────────────
    end_date   = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days + 10)

    try:
        import yfinance as yf
        raw_data = yf.download(
            tickers=yf_tickers,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            progress=False,
            auto_adjust=True,
        )
        if raw_data is None or raw_data.empty:
            logger.debug("VarCalculator | yfinance returned no data — VaR=0.0")
            return 0.0
    except Exception as exc:
        logger.warning(f"VarCalculator | yfinance fetch failed (non-fatal): {exc} — VaR=0.0")
        return 0.0

    # ── Extract closing prices per ticker ────────────────────────────────────
    # yfinance returns a multi-level column DataFrame when multiple tickers are
    # requested, or a single-level DataFrame for one ticker.
    closes: dict[str, list[float]] = {}
    try:
        import pandas as pd
        if isinstance(raw_data.columns, pd.MultiIndex):
            close_df = raw_data["Close"] if "Close" in raw_data else raw_data.iloc[:, 0]
        else:
            # Single ticker: column is just "Close"
            close_df = raw_data[["Close"]] if "Close" in raw_data.columns else raw_data
            if len(yf_tickers) == 1:
                close_df.columns = yf_tickers

        for ticker in yf_tickers:
            if ticker in close_df.columns:
                series = close_df[ticker].dropna()
                if len(series) >= 2:
                    closes[ticker] = series.tolist()
    except Exception as exc:
        logger.warning(f"VarCalculator | Close extraction failed: {exc} — VaR=0.0")
        return 0.0

    if not closes:
        logger.debug("VarCalculator | No usable price series — VaR=0.0")
        return 0.0

    # ── Build portfolio daily P&L series ─────────────────────────────────────
    portfolio_pnl: list[float] = []

    # Align series lengths: use the minimum available
    lengths = [len(v) for v in closes.values()]
    min_len = min(lengths) - 1 if lengths else 0
    if min_len < 5:
        logger.debug(
            f"VarCalculator | Only {min_len} daily returns available "
            f"(need ≥ 5) — VaR=0.0"
        )
        return 0.0

    for i in range(min_len):
        day_pnl = 0.0
        for p in valid:
            raw        = str(p["symbol"]).upper()
            yf_ticker  = symbol_map.get(raw)
            if yf_ticker not in closes:
                continue
            price_series = closes[yf_ticker]
            ret          = (price_series[i + 1] - price_series[i]) / price_series[i]
            weight       = float(p["market_value"]) / total_value
            day_pnl     += ret * weight
        portfolio_pnl.append(day_pnl)

    if len(portfolio_pnl) < 5:
        return 0.0

    # ── Historical simulation VaR ─────────────────────────────────────────────
    sorted_pnl  = sorted(portfolio_pnl)
    cutoff_idx  = max(0, int((1.0 - confidence) * len(sorted_pnl)) - 1)
    var_return  = -sorted_pnl[cutoff_idx]   # loss = negative of return
    var_pct     = max(0.0, var_return)

    logger.debug(
        f"VarCalculator | Historical simulation VaR "
        f"({confidence*100:.0f}% conf, {len(portfolio_pnl)} obs) = {var_pct*100:.2f}% "
        f"of portfolio (${var_pct * total_value:,.2f})"
    )
    return round(var_pct, 6)


def _to_yfinance_ticker(symbol: str) -> str:
    """Map broker symbol to yfinance ticker string."""
    _MAP = {
        "BTCUSD":  "BTC-USD",
        "ETHUSD":  "ETH-USD",
        "BTC/USD": "BTC-USD",
        "ETH/USD": "ETH-USD",
        "XBTUSD":  "BTC-USD",
        "SOLUSD":  "SOL-USD",
        "SOL/USD": "SOL-USD",
        "ADAUSD":  "ADA-USD",
        "ADA/USD": "ADA-USD",
        "DOTUSD":  "DOT-USD",
        "DOT/USD": "DOT-USD",
        "LINKUSD": "LINK-USD",
        "AVAXUSD": "AVAX-USD",
        "MATICUSD":"MATIC-USD",
        "UNIUSD":  "UNI-USD",
    }
    mapped = _MAP.get(symbol)
    if mapped:
        return mapped
    # If already contains "-" (e.g. BTC-USD from Alpaca), use as-is
    if "-" in symbol:
        return symbol
    # Fallback: assume it's a standard equity ticker
    return symbol
