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
        VaR expressed as a **fraction of the total invested value of
        ``positions``** (i.e. the sum of all ``market_value`` entries),
        not as a fraction of total account equity.

        Examples:
          * ``0.03`` means a 1-day 95% loss of 3% of the invested positions.
          * If ``$50k`` is invested and VaR is 3%, the dollar loss is ``$1,500``.

        Callers that compare against an equity-relative limit (e.g.
        ``daily_loss_limit_pct * total_equity``) must first scale:
        ``var_usd = var_pct * invested_usd`` and then compare
        ``var_usd > daily_loss_limit_pct * total_equity``.

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

    # ── Extract closing prices and build date-indexed return series ──────────
    # yfinance returns a multi-level column DataFrame when multiple tickers are
    # requested, or a single-level DataFrame for one ticker.
    # We keep the date index on each series so that the portfolio P&L can be
    # computed via an outer join with fillna(0) — each asset contributes its OWN
    # full history rather than being truncated to the shortest asset's history.
    try:
        import pandas as pd

        if isinstance(raw_data.columns, pd.MultiIndex):
            close_df = raw_data["Close"] if "Close" in raw_data else raw_data.iloc[:, 0]
        else:
            # Single ticker: column is just "Close"
            close_df = raw_data[["Close"]] if "Close" in raw_data.columns else raw_data
            if len(yf_tickers) == 1:
                close_df.columns = yf_tickers

        # Build per-asset daily return Series with the yfinance DATE index intact.
        # pct_change() preserves the date index; dropna() removes the first NaN row.
        return_series: dict[str, "pd.Series[float]"] = {}
        for ticker in yf_tickers:
            if ticker in close_df.columns:
                prices = close_df[ticker].dropna()
                if len(prices) >= 2:
                    return_series[ticker] = prices.pct_change().dropna()

    except Exception as exc:
        logger.warning(f"VarCalculator | Close extraction failed: {exc} — VaR=0.0")
        return 0.0

    if not return_series:
        logger.debug("VarCalculator | No usable price series — VaR=0.0")
        return 0.0

    # ── Build portfolio daily P&L series (date-aligned outer join) ───────────
    # Each asset contributes returns over its OWN available history.
    # pd.concat with join="outer" preserves every date where ANY asset has data.
    # NaN entries (days an asset was not yet listed or not held) are filled with
    # 0.0, which is correct: a non-held asset contributes $0 P&L on that day.
    # This ensures a newly listed stock does not truncate older assets' histories.
    try:
        frames: list["pd.Series[float]"] = []
        for p in valid:
            raw       = str(p["symbol"]).upper()
            yf_ticker = symbol_map.get(raw)
            if yf_ticker not in return_series:
                continue
            weight = float(p["market_value"]) / total_value
            frames.append(return_series[yf_ticker] * weight)

        if not frames:
            return 0.0

        # Outer join: union of all dates. Fill missing returns with 0.0
        # (asset not held / not yet listed → zero daily contribution).
        combined = pd.concat(frames, axis=1, join="outer").fillna(0.0)
        portfolio_pnl = combined.sum(axis=1).tolist()

    except Exception as exc:
        logger.warning(f"VarCalculator | Date-aligned P&L build failed: {exc} — VaR=0.0")
        return 0.0

    if len(portfolio_pnl) < 5:
        # Portfolio has insufficient price history — compute ATR-based proxy VaR
        # by summing per-position estimates. Prevents circuit breaker blindness
        # on day-1 or newly-added positions.
        proxy_var_total = 0.0
        try:
            import yfinance as _yf_proxy
            confidence_z = 1.645 if confidence >= 0.95 else 1.282
            for p in valid:
                ticker = p.get("symbol") or p.get("ticker") or ""
                position_value = abs(float(p.get("market_value") or 0))
                if not ticker or position_value <= 0:
                    continue
                try:
                    _hist = _yf_proxy.Ticker(ticker).history(period="30d", interval="1d")
                    if len(_hist) < 14:
                        continue
                    _closes = _hist["Close"].tolist()
                    _highs  = _hist["High"].tolist()
                    _lows   = _hist["Low"].tolist()
                    # Wilder ATR
                    _trs = []
                    for _i in range(1, len(_closes)):
                        _tr = max(
                            _highs[_i] - _lows[_i],
                            abs(_highs[_i] - _closes[_i - 1]),
                            abs(_lows[_i]  - _closes[_i - 1]),
                        )
                        _trs.append(_tr)
                    if len(_trs) >= 14:
                        _atr = sum(_trs[:14]) / 14
                        for _j in range(14, len(_trs)):
                            _atr = (_atr * 13 + _trs[_j]) / 14
                        if _atr > 0 and _closes[-1] > 0:
                            atr_pct = _atr / _closes[-1]
                            proxy_var_total += position_value * atr_pct * confidence_z
                            logger.debug(
                                f"VaR | {ticker} ATR proxy: "
                                f"atr_pct={atr_pct:.4f} "
                                f"contribution=${position_value * atr_pct * confidence_z:,.2f}"
                            )
                except Exception as _pe:
                    logger.debug(f"VaR | ATR proxy failed for {ticker}: {_pe}")
        except Exception as _ve:
            logger.debug(f"VaR | ATR proxy block failed: {_ve}")

        if proxy_var_total > 0:
            proxy_var_pct = proxy_var_total / total_value
            logger.info(
                f"VaR | ATR proxy VaR={proxy_var_pct:.4f} "
                f"(${proxy_var_total:,.2f} / ${total_value:,.2f} portfolio)"
            )
            return round(proxy_var_pct, 6)
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
