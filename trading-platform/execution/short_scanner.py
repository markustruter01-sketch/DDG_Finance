"""
Algorithmic Short Scanner — Bear Market Profit Engine
------------------------------------------------------
v1.0 — Standalone mean-reversion short scanner for equity ETFs.

Activated ONLY when the Alpaca platform's current regime is Bear/RISK-OFF.
Mirrors the Kraken bot's mean-reversion signal logic on hourly equity data.

Signal Logic
------------
  Universe: SPY, QQQ, XLK, XLF, XLE, IWM (hardcoded — no LLM)
  Entry: Z-score > 2.0 AND RSI(14) > 68 on last 20 hourly bars
  Sizing: 1% equity risk / ATR stop-distance; hard cap 15% equity per position
  Borrow: check_shortable() must return (True, True)
  Margin: buying_power >= notional required; no debt allowed
  Double-dip: no QQQ short if SQQQ held; no SPY short if SPXS held; no IWM if SRTY held
  Max exposure: sum of algo short market values ≤ 35% of equity

Exit Logic
----------
  Mean-reversion: Z-score < 0.3 (price returned to mean)
  Trailing 5%: if price rises 5% above best (lowest) price since entry → cover
  Hard stop: ATR-based stop-buy order placed at fill (via ratchet_stop.initialise_ratchet_stop)

Integration
-----------
  Called from pipeline.py after execute_allocations(), passing:
    - regime str
    - allocation RegimeAnalysisOutput (for double-dip check)
    - dry_run bool
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from loguru import logger

# ── Constants ────────────────────────────────────────────────────────────────

SHORT_UNIVERSE: list[str] = ["SPY", "QQQ", "XLK", "XLF", "XLE", "IWM"]

# Regime labels that activate the scanner
_BEAR_REGIMES: frozenset[str] = frozenset(
    {"Bear", "RISK-OFF", "Risk-Off", "bear", "risk-off"}
)

ZSCORE_ENTRY_THRESHOLD: float = 2.0    # Z-score above this signals over-extension
RSI_ENTRY_THRESHOLD:    float = 68.0   # RSI above this confirms overbought
ZSCORE_EXIT_THRESHOLD:  float = 0.3    # Z-score below this → mean reversion complete
TRAILING_EXIT_PCT:      float = 0.05   # Exit if price rises 5% above best entry low
MAX_SHORT_EXPOSURE_PCT: float = 0.35   # Max 35% of equity in algo shorts combined
RISK_PER_TRADE_PCT:     float = 0.01   # 1% of equity at risk per short trade
MAX_POSITION_PCT:       float = 0.15   # 15% of equity max per short position
LOOKBACK_HOURS:         int   = 20     # Hourly bars for signal calculation
ATR_PERIOD:             int   = 14     # ATR lookback for stop placement

# Double-dip prevention: if LLM holds inverse ETF, skip shorting its underlying
_DOUBLE_DIP_MAP: dict[str, str] = {
    "QQQ": "SQQQ",
    "SPY": "SPXS",
    "IWM": "SRTY",
}


# ── State tracking for open algo shorts ─────────────────────────────────────
# In-memory tracking of algo short positions; survives individual scan calls
# but resets on process restart. The Alpaca positions list is the authoritative
# source of truth — we use this dict for best-price tracking (trailing exit).

_algo_short_state: dict[str, dict] = {}
# Format: { "SPY": { "entry_price": float, "qty": int, "best_price": float, "entered_at": str } }


# ── Signal computation ───────────────────────────────────────────────────────

def _fetch_hourly_bars(ticker: str, n_bars: int = LOOKBACK_HOURS) -> Optional[list[float]]:
    """
    Fetch the last n_bars of hourly close prices from Alpaca's data API.
    Returns a list of floats (oldest first), or None on failure.
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from datetime import timedelta
        from config.settings import settings

        client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=n_bars * 3)  # extra buffer for market closed hours

        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Hour,
            start=start,
            end=end,
        )
        bars = client.get_stock_bars(req)
        if not bars or ticker not in bars:
            return None

        closes = [float(b.close) for b in bars[ticker]]
        if len(closes) < n_bars:
            logger.debug(f"ShortScanner | {ticker}: only {len(closes)} hourly bars (need {n_bars})")
            return None
        return closes[-n_bars:]   # last n_bars only
    except Exception as exc:
        logger.warning(f"ShortScanner | Hourly bar fetch failed for {ticker}: {exc}")
        return None


def _compute_zscore(closes: list[float]) -> float:
    """Z-score of the last close relative to the window."""
    arr = np.array(closes, dtype=float)
    mean = np.mean(arr)
    std  = np.std(arr)
    if std < 1e-8:
        return 0.0
    return float((arr[-1] - mean) / std)


def _compute_rsi(closes: list[float], period: int = ATR_PERIOD) -> float:
    """Wilder RSI."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)

    avg_gain = float(np.mean(gains[-period:]))
    avg_loss = float(np.mean(losses[-period:]))
    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_atr(closes: list[float]) -> float:
    """Simple ATR approximation using daily closes (hourly here)."""
    if len(closes) < 2:
        return 0.0
    tr_list = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    if not tr_list:
        return 0.0
    period = min(ATR_PERIOD, len(tr_list))
    return float(np.mean(tr_list[-period:]))


def _compute_signals(ticker: str) -> Optional[dict]:
    """
    Compute Z-score, RSI, and ATR for a ticker using the last 20 hourly bars.
    Returns None if data is unavailable.
    """
    closes = _fetch_hourly_bars(ticker, LOOKBACK_HOURS)
    if closes is None:
        return None

    zscore = _compute_zscore(closes)
    rsi    = _compute_rsi(closes, ATR_PERIOD)
    atr    = _compute_atr(closes)

    return {
        "ticker":        ticker,
        "close":         closes[-1],
        "zscore":        round(zscore, 3),
        "rsi":           round(rsi, 2),
        "atr":           round(atr, 4),
        "entry_signal":  zscore > ZSCORE_ENTRY_THRESHOLD and rsi > RSI_ENTRY_THRESHOLD,
        "exit_signal":   zscore < ZSCORE_EXIT_THRESHOLD,
    }


# ── Position sizing ──────────────────────────────────────────────────────────

def _compute_short_size(equity: float, price: float, atr: float) -> int:
    """
    Risk-based position sizing for a short entry.
    Risk per trade = 1% of equity.
    Stop distance = 2× ATR (the buy-to-cover stop is placed 2× ATR above fill).
    Returns whole number of shares (math.floor), minimum 1.
    """
    stop_distance = max(2.0 * atr, price * 0.01)   # guard: at least 1% of price
    risk_dollars = equity * RISK_PER_TRADE_PCT
    notional = risk_dollars / (stop_distance / price)  # notional = risk / (stop_pct)
    max_notional = equity * MAX_POSITION_PCT
    notional = min(notional, max_notional)
    qty = math.floor(notional / price)
    return max(1, qty)


# ── Double-dip prevention ────────────────────────────────────────────────────

def _check_double_dip(ticker: str, llm_tickers: set[str]) -> bool:
    """
    Returns True if shorting *ticker* would double-dip with an inverse ETF
    already held by the LLM portfolio.
    """
    inverse = _DOUBLE_DIP_MAP.get(ticker)
    if inverse and inverse in llm_tickers:
        logger.info(
            f"ShortScanner | Skipping SHORT {ticker} — LLM holds {inverse} "
            f"(double-dip prevention)"
        )
        return True
    return False


# ── Exposure check ───────────────────────────────────────────────────────────

def _get_short_exposure(positions: list[dict], equity: float) -> tuple[float, float]:
    """
    Returns (total_short_usd, short_pct) for currently open short positions.
    Includes ALL short positions in the Alpaca account (algo + any others).
    """
    short_positions = [
        p for p in positions
        if str(p.get("side", "long")).lower() == "short"
    ]
    total_short_usd = sum(abs(float(p.get("market_value", 0.0))) for p in short_positions)
    short_pct = total_short_usd / max(equity, 1.0)
    return total_short_usd, short_pct


# ── Entry logic ──────────────────────────────────────────────────────────────

def _try_enter_short(
    ticker: str,
    signals: dict,
    equity: float,
    positions: list[dict],
    llm_tickers: set[str],
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Attempt to open a short position on *ticker*.
    Returns result dict on success, None if skipped.
    """
    price = signals["close"]
    atr   = signals["atr"]

    # Guard: skip if already short this ticker
    current_shorts = {
        p["symbol"] for p in positions
        if str(p.get("side", "long")).lower() == "short"
    }
    if ticker in current_shorts:
        logger.debug(f"ShortScanner | {ticker} already held short — skipping re-entry")
        return None

    # Guard: double-dip
    if _check_double_dip(ticker, llm_tickers):
        return None

    # Guard: max short exposure
    total_short_usd, short_pct = _get_short_exposure(positions, equity)
    if short_pct >= MAX_SHORT_EXPOSURE_PCT:
        logger.warning(
            f"ShortScanner | {ticker} — short exposure cap reached "
            f"({short_pct:.1%} ≥ {MAX_SHORT_EXPOSURE_PCT:.0%}) — skipping"
        )
        return None

    # Borrow check
    from execution.broker import check_shortable, get_account
    shortable, easy_to_borrow = check_shortable(ticker)
    if not shortable or not easy_to_borrow:
        logger.info(
            f"ShortScanner | {ticker} not shortable "
            f"(shortable={shortable}, etb={easy_to_borrow}) — skipping"
        )
        return None

    # Margin check
    acct = get_account()
    buying_power = float(acct.get("buying_power", 0.0))
    qty = _compute_short_size(equity, price, atr)
    notional_required = qty * price
    if buying_power < notional_required:
        logger.warning(
            f"ShortScanner | {ticker} — insufficient buying power "
            f"(need ${notional_required:,.0f}, have ${buying_power:,.0f}) — skipping"
        )
        return None

    # Pre-exposure check (would adding this breach the cap?)
    if (total_short_usd + notional_required) / equity > MAX_SHORT_EXPOSURE_PCT:
        logger.warning(
            f"ShortScanner | {ticker} — would breach exposure cap after entry — skipping"
        )
        return None

    logger.info(
        f"ShortScanner | ENTRY {ticker} SHORT qty={qty} price=${price:.2f} "
        f"z={signals['zscore']:.2f} rsi={signals['rsi']:.1f} atr={atr:.4f} "
        f"{'[DRY-RUN]' if dry_run else ''}"
    )

    if dry_run:
        _algo_short_state[ticker] = {
            "entry_price": price,
            "qty":         qty,
            "best_price":  price,
            "entered_at":  datetime.now(timezone.utc).isoformat(),
            "dry_run":     True,
        }
        return {
            "action":  "short_entry",
            "ticker":  ticker,
            "qty":     qty,
            "price":   price,
            "dry_run": True,
        }

    try:
        from execution.broker import place_short_order
        order = place_short_order(ticker, qty)
        fill_price = float(order.get("fill_price") or price)

        _algo_short_state[ticker] = {
            "entry_price": fill_price,
            "qty":         qty,
            "best_price":  fill_price,
            "entered_at":  datetime.now(timezone.utc).isoformat(),
            "order_id":    order.get("id"),
        }

        # Place ATR stop-buy above fill
        from execution.ratchet_stop import initialise_ratchet_stop
        stop_result = initialise_ratchet_stop(
            ticker=ticker,
            fill_price=fill_price,
            qty=float(qty),
            dry_run=False,
            side="short",
        )

        # Log to trade journal
        try:
            from analysis.trade_journal import log_trade
            log_trade(
                ticker=ticker,
                asset_class="direct_short",
                conviction_score=0.0,
                kelly_fraction=round(notional_required / equity, 4),
                fill_price=fill_price,
                intended_price=price,
                notional_usd=notional_required,
                thesis=(
                    f"Algo short entry: Z-score={signals['zscore']:.2f} "
                    f"RSI={signals['rsi']:.1f} (entry thresholds Z>{ZSCORE_ENTRY_THRESHOLD} RSI>{RSI_ENTRY_THRESHOLD})"
                ),
            )
        except Exception as log_exc:
            logger.warning(f"ShortScanner | Journal log failed for {ticker}: {log_exc}")

        logger.info(
            f"ShortScanner | SHORT {ticker} entered: qty={qty} fill=${fill_price:.2f} "
            f"stop=${stop_result.get('stop_price', 'n/a'):.4f}"
        )
        return {
            "action":      "short_entry",
            "ticker":      ticker,
            "qty":         qty,
            "fill_price":  fill_price,
            "stop_result": stop_result,
        }

    except Exception as exc:
        logger.error(f"ShortScanner | Short entry failed for {ticker}: {exc}")
        return None


# ── Exit logic ───────────────────────────────────────────────────────────────

def _try_exit_short(
    ticker: str,
    signals: dict,
    positions: list[dict],
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Check exit conditions for an open algo short on *ticker*.
    Returns result dict if exit was triggered, None if position should be held.
    """
    pos = next(
        (p for p in positions
         if p["symbol"] == ticker and str(p.get("side", "long")).lower() == "short"),
        None,
    )
    if pos is None:
        # Position no longer exists (may have been stopped out by GTC stop order)
        if ticker in _algo_short_state:
            logger.info(f"ShortScanner | {ticker} short position gone — removing state")
            _algo_short_state.pop(ticker, None)
        return None

    current_price = float(pos.get("current_price", signals["close"]))
    qty = abs(int(float(pos.get("qty", 1))))

    # Update best (lowest) price seen since entry
    state = _algo_short_state.get(ticker, {})
    best_price = state.get("best_price", current_price)
    if current_price < best_price:
        best_price = current_price
        _algo_short_state.setdefault(ticker, {})["best_price"] = best_price

    # Exit condition 1: Mean-reversion complete (Z-score returned to mean)
    mean_revert = signals["zscore"] < ZSCORE_EXIT_THRESHOLD

    # Exit condition 2: Trailing stop — price rose 5% above best (lowest) price
    trailing_triggered = current_price >= best_price * (1.0 + TRAILING_EXIT_PCT)

    reason = None
    if mean_revert:
        reason = f"mean-reversion (Z={signals['zscore']:.2f} < {ZSCORE_EXIT_THRESHOLD})"
    elif trailing_triggered:
        reason = f"trailing exit (price ${current_price:.2f} ≥ best ${best_price:.2f} + {TRAILING_EXIT_PCT:.0%})"

    if reason is None:
        logger.debug(
            f"ShortScanner | {ticker} SHORT holding — "
            f"Z={signals['zscore']:.2f} price=${current_price:.2f} best=${best_price:.2f}"
        )
        return None

    logger.warning(
        f"ShortScanner | EXIT {ticker} SHORT — {reason} "
        f"{'[DRY-RUN]' if dry_run else ''}"
    )

    if dry_run:
        _algo_short_state.pop(ticker, None)
        return {"action": "short_exit", "ticker": ticker, "reason": reason, "dry_run": True}

    try:
        from execution.broker import buy_to_cover
        from execution.ratchet_stop import delete_stop
        order = buy_to_cover(ticker, qty)
        delete_stop(ticker)
        _algo_short_state.pop(ticker, None)
        logger.info(f"ShortScanner | {ticker} covered: {reason}")
        return {
            "action":  "short_exit",
            "ticker":  ticker,
            "reason":  reason,
            "order":   order,
        }
    except Exception as exc:
        logger.error(f"ShortScanner | buy_to_cover failed for {ticker}: {exc}")
        return None


# ── Main entry point ─────────────────────────────────────────────────────────

def run_scan(
    regime: Optional[str],
    allocation,   # RegimeAnalysisOutput or None
    dry_run: bool = False,
) -> dict:
    """
    Main scanner entry point, called from pipeline.py after execute_allocations().

    Parameters
    ----------
    regime     : current regime string (e.g. "Bear", "Bull", "Sideways")
    allocation : RegimeAnalysisOutput from the LLM (for double-dip check); may be None
    dry_run    : if True, log but do not place real orders

    Returns
    -------
    dict with scan summary: { regime, activated, entries, exits, skips, errors }
    """
    regime_str = str(regime) if regime else "unknown"

    result: dict = {
        "regime":    regime_str,
        "activated": False,
        "entries":   [],
        "exits":     [],
        "skips":     [],
        "errors":    [],
    }

    # Activation gate: scanner ONLY runs in Bear/RISK-OFF
    if regime_str not in _BEAR_REGIMES:
        logger.debug(
            f"ShortScanner | regime='{regime_str}' — scanner inactive "
            f"(only activates in Bear/RISK-OFF)"
        )
        return result

    result["activated"] = True
    logger.info(f"ShortScanner | ACTIVATED — regime='{regime_str}' (Bear/RISK-OFF)")

    # Collect LLM-held tickers for double-dip prevention
    llm_tickers: set[str] = set()
    if allocation is not None:
        try:
            llm_tickers = {a.ticker for a in allocation.allocations}
        except Exception:
            pass

    # Fetch current Alpaca state
    try:
        from execution.broker import get_positions, get_account
        positions = get_positions()
        acct      = get_account()
        equity    = float(acct.get("equity", 0.0))
    except Exception as exc:
        logger.error(f"ShortScanner | Failed to fetch Alpaca state: {exc}")
        result["errors"].append(f"account fetch: {exc}")
        return result

    if equity < 1000.0:
        logger.warning("ShortScanner | Equity too low — scanner skipped")
        return result

    logger.info(
        f"ShortScanner | equity=${equity:,.0f} | "
        f"scanning {len(SHORT_UNIVERSE)} tickers: {SHORT_UNIVERSE}"
    )

    # ── Scan each ticker ──────────────────────────────────────────────────────
    for ticker in SHORT_UNIVERSE:
        try:
            signals = _compute_signals(ticker)
            if signals is None:
                result["skips"].append({"ticker": ticker, "reason": "no data"})
                continue

            logger.debug(
                f"ShortScanner | {ticker}: Z={signals['zscore']:.2f} "
                f"RSI={signals['rsi']:.1f} price=${signals['close']:.2f}"
            )

            # ── Exit check for existing shorts ────────────────────────────────
            exit_result = _try_exit_short(ticker, signals, positions, dry_run=dry_run)
            if exit_result is not None:
                result["exits"].append(exit_result)
                # Refresh positions after exit
                if not dry_run:
                    try:
                        positions = get_positions()
                    except Exception:
                        pass
                continue

            # ── Entry check ───────────────────────────────────────────────────
            if signals["entry_signal"]:
                entry_result = _try_enter_short(
                    ticker, signals, equity, positions, llm_tickers, dry_run=dry_run
                )
                if entry_result is not None:
                    result["entries"].append(entry_result)
                    # Refresh positions and equity after entry
                    if not dry_run:
                        try:
                            positions = get_positions()
                            acct_fresh = get_account()
                            equity = float(acct_fresh.get("equity", equity))
                        except Exception:
                            pass
                else:
                    result["skips"].append({"ticker": ticker, "reason": "entry blocked"})
            else:
                result["skips"].append({
                    "ticker": ticker,
                    "reason": "signal not met",
                    "z":      signals["zscore"],
                    "rsi":    signals["rsi"],
                })

        except Exception as exc:
            logger.error(f"ShortScanner | Unexpected error on {ticker}: {exc}")
            result["errors"].append(f"{ticker}: {exc}")

    total_short_usd, short_pct = _get_short_exposure(positions, equity)
    logger.info(
        f"ShortScanner | Scan complete — "
        f"entries={len(result['entries'])} exits={len(result['exits'])} "
        f"skips={len(result['skips'])} errors={len(result['errors'])} "
        f"short_exposure=${total_short_usd:,.0f} ({short_pct:.1%})"
    )
    result["short_exposure_usd"] = round(total_short_usd, 2)
    result["short_exposure_pct"] = round(short_pct * 100, 2)

    return result


def get_algo_short_state() -> dict:
    """Return a copy of the current in-memory algo short state (for API/dashboard)."""
    return dict(_algo_short_state)
